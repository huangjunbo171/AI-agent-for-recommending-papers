"""提供英文检测、DeepSeek 论文分析和响应校验。"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import httpx
from langdetect import DetectorFactory, LangDetectException, detect_langs

from config import DEEPSEEK_INFO
from paper_agent.prompts_test import (
    analyze_paper_metadata_prompt,
    analyze_paper_metadata_user_prompt,
)
from utils.arxiv_source import IngestError, Paper, normalize_text


ARRAY_FIELDS = (
    "keywords",
    "research_topics",
    "datasets",
    "main_contributions",
    "main_results",
    "limitations",
)
SCALAR_FIELDS = (
    "core_method",
    "code_status",
    "code_url",
    "code_evidence",
    "venue",
    "venue_evidence",
)
CODE_STATUSES = {"yes", "no", "unknown"}
CJK_PATTERN = re.compile(r"[\u3400-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]")
MARKDOWN_HEADING_PATTERN = re.compile(r"^\s*(#{1,6})\s+(.+?)\s*$")
SECTION_NUMBER_PATTERN = re.compile(
    r"^\s*(?:(?:\d+(?:\.\d+)*)|(?:[ivxlcdm]+))(?=[.)\s:–—-])"
    r"[.)]?\s*[-:–—.]?\s*",
    re.IGNORECASE,
)
PLAIN_REFERENCES_PATTERN = re.compile(
    r"(?im)^\s*(?:references|bibliography|works cited|literature cited)\s*$"
)
REFERENCE_SECTION_TITLES = {
    "references",
    "bibliography",
    "works cited",
    "literature cited",
}
RELATED_WORK_SECTION_PATTERN = re.compile(
    r"\b(?:related works?|literature review|previous works?|prior works?)\b",
    re.IGNORECASE,
)
GITHUB_REPOSITORY_PATTERN = re.compile(
    r"https?://(?:www\.)?github\.com/"
    r"(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.\\-]+)",
    re.IGNORECASE,
)
VENUE_ACCEPTANCE_PATTERN = re.compile(
    r"\b(?:accepted\s+(?:at|to)|published\s+(?:in|at)|"
    r"to\s+appear\s+in|appearing\s+in)\b",
    re.IGNORECASE,
)
VENUE_REJECTION_PATTERN = re.compile(
    r"\b(?:submitted\s+to|under\s+review)\b", re.IGNORECASE
)
CODE_POSITIVE_PATTERN = re.compile(
    r"(?i)(?:code|implementation|repository).{0,100}"
    r"(?:open[- ]source|publicly\s+available|available\s+(?:at|here)|github\.com)"
    r"|(?:open[- ]source|publicly\s+available).{0,100}"
    r"(?:code|implementation|repository)"
)
CODE_NEGATIVE_PATTERN = re.compile(
    r"(?i)(?:(?:code|implementation|repository).{0,120}"
    r"(?:not\s+(?:publicly\s+)?available|not\s+released|private|"
    r"available\s+upon\s+request|will\s+(?:be\s+)?release|plan\s+to\s+release)"
    r"|(?:not\s+(?:publicly\s+)?available|not\s+released|private|"
    r"available\s+upon\s+request|will\s+(?:be\s+)?release|plan\s+to\s+release)"
    r".{0,120}(?:code|implementation|repository))"
)
DetectorFactory.seed = 0
DEFAULT_MAX_FULL_TEXT_CHARS = 240_000


class AuthenticationError(IngestError):
    """DeepSeek 拒绝当前认证信息时抛出。"""


@dataclass(frozen=True)
class LanguageResult:
    """保存语言检测结果和英文判定。"""

    language: str
    confidence: float
    is_english: bool


def detect_english_text(text: str, threshold: float = 0.80) -> LanguageResult:
    """检测文本是否为达到置信度阈值的英文。"""
    normalized = normalize_text(text)[:10000]
    if not normalized or CJK_PATTERN.search(normalized):
        return LanguageResult("unknown", 0.0, False)
    try:
        probabilities = detect_langs(normalized)
    except LangDetectException:
        return LanguageResult("unknown", 0.0, False)
    best = probabilities[0]
    return LanguageResult(
        language=best.lang,
        confidence=float(best.prob),
        is_english=best.lang == "en" and float(best.prob) >= threshold,
    )


def validate_english_paper(paper: Paper) -> LanguageResult:
    """检测论文最终标题和摘要是否为英文。"""
    return detect_english_text(f"{paper.title}\n{paper.abstract}", threshold=0.80)


def validate_full_text(full_text: str, max_chars: int) -> str:
    """校验 MinerU 全文非空且未超过模型输入上限，不做静默截断。"""
    content = (full_text or "").strip()
    if not content:
        raise IngestError("MinerU 论文全文为空，拒绝仅根据标题或摘要分析")
    if len(content) > max_chars:
        raise IngestError(
            f"MinerU 论文全文长度 {len(content)} 超过分析上限 {max_chars}，"
            "拒绝截断后分析"
        )
    return content


def _normalize_section_title(value: str) -> str:
    """清理 Markdown 标题中的编号和格式字符，供章节类型识别。"""
    # MinerU 可能把单词拆成 Referen<sub>c</sub>es，先去除内联 HTML 标签。
    title = re.sub(r"<[^>]+>", "", value)
    title = re.sub(r"[*_`~]+", "", title)
    title = re.sub(r"\s*\{#[^}]+\}\s*$", "", title)
    title = SECTION_NUMBER_PATTERN.sub("", title)
    title = re.sub(r"[^a-z]+", " ", title.casefold())
    return " ".join(title.split())


def strip_analysis_sections(full_text: str) -> str:
    """删除 Related Work 章节，并从参考文献章节开始截断全文。

    参数:
        full_text: MinerU 生成的 Markdown 全文。

    返回:
        保留标题、摘要、方法、实验和结论等章节的正文。
    """
    lines = (full_text or "").splitlines(keepends=True)
    kept: List[str] = []
    skipped_related_level: Optional[int] = None

    for line in lines:
        heading = MARKDOWN_HEADING_PATTERN.match(line)
        if heading:
            level = len(heading.group(1))
            title = _normalize_section_title(heading.group(2))
            if title in REFERENCE_SECTION_TITLES or title.startswith("references "):
                break

            # Related Work 的子标题一并删除，遇到同级或更高级标题后恢复保留。
            if skipped_related_level is not None:
                if level > skipped_related_level:
                    continue
                skipped_related_level = None
            if RELATED_WORK_SECTION_PATTERN.search(title):
                skipped_related_level = level
                continue
        elif skipped_related_level is not None:
            continue

        kept.append(line)

    cleaned = "".join(kept).strip()
    plain_reference = PLAIN_REFERENCES_PATTERN.search(cleaned)
    if plain_reference:
        cleaned = cleaned[: plain_reference.start()].strip()
    return cleaned


def _normalize_multiline_text(value: str) -> str:
    """清理多段文本中的多余空白，同时保留自然段。"""
    lines = [" ".join(line.split()) for line in value.replace("\r", "").split("\n")]
    paragraphs: List[str] = []
    current: List[str] = []
    for line in lines:
        if line:
            current.append(line)
        elif current:
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    return "\n\n".join(paragraphs).strip()


def _main_text_without_references(full_text: str) -> str:
    """返回已去除 Related Work 和参考文献的正文供证据校验。"""
    return strip_analysis_sections(full_text)


def _normalize_evidence_text(value: str) -> str:
    """统一 Markdown 转义和空白，便于核对模型引用的原文证据。"""
    return " ".join(value.replace("\\_", "_").split()).strip()


def _evidence_in_text(evidence: str, source_text: str) -> bool:
    """判断简短证据是否能在指定原文中找到。"""
    needle = _normalize_evidence_text(evidence).casefold()
    haystack = _normalize_evidence_text(source_text).casefold()
    return bool(needle) and needle in haystack


def normalize_github_url(value: str) -> str:
    """把 GitHub 地址规范化为 owner/repository 根地址。"""
    match = GITHUB_REPOSITORY_PATTERN.search((value or "").replace("\\_", "_"))
    if not match:
        raise ValueError("code_url must be a GitHub repository URL")
    owner = match.group("owner").strip(". ")
    repository = match.group("repo").rstrip(".,;:)]}>")
    if repository.lower().endswith(".git"):
        repository = repository[:-4]
    if not owner or not repository:
        raise ValueError("code_url must contain a GitHub owner and repository")
    return f"https://github.com/{owner}/{repository}"


def extract_github_repositories(full_text: str) -> List[str]:
    """只从参考文献之前的正文提取并去重 GitHub 仓库地址。"""
    repositories: List[str] = []
    for match in GITHUB_REPOSITORY_PATTERN.finditer(
        _main_text_without_references(full_text).replace("\\_", "_")
    ):
        normalized = normalize_github_url(match.group(0))
        if normalized not in repositories:
            repositories.append(normalized)
    return repositories


def _find_code_evidence(full_text: str, status: str) -> str:
    """从正文中确定性查找与开源状态匹配的完整句子。"""
    main_text = _main_text_without_references(full_text)
    candidates = re.split(r"(?<=[.!?])(?:\s+|\n+)", main_text)
    pattern = CODE_POSITIVE_PATTERN if status == "yes" else CODE_NEGATIVE_PATTERN
    for candidate in candidates:
        evidence = " ".join(candidate.split()).strip()
        if not evidence or len(evidence) > 600:
            continue
        # “未来发布”等否定语义优先，不能被 publicly available 字样误判为已开源。
        if status == "yes" and CODE_NEGATIVE_PATTERN.search(evidence):
            continue
        if pattern.search(evidence):
            return evidence
    return ""


def count_english_words(value: str) -> int:
    """统计英文方法说明中的单词数量。"""
    return len(re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*", value))


def _analysis_text(analysis: Dict[str, Any]) -> str:
    """拼接结构化分析中的非空字符串，供语言检测使用。"""
    values: List[str] = []
    for field in ARRAY_FIELDS:
        values.extend(str(item) for item in analysis[field] if str(item).strip())
    if analysis["core_method"]:
        values.append(str(analysis["core_method"]))
    for field in ("code_evidence", "venue", "venue_evidence"):
        if analysis[field]:
            values.append(str(analysis[field]))
    return "\n".join(values)


def parse_analysis_json(
    content: str, full_text: str, journal_ref: str = ""
) -> Dict[str, Any]:
    """清理 DeepSeek JSON，并校验方法、开源代码和 venue 证据。"""
    cleaned = (content or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("LLM response does not contain a JSON object")
    value = json.loads(cleaned[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("LLM response must be a JSON object")

    expected = set(ARRAY_FIELDS) | set(SCALAR_FIELDS)
    if set(value) != expected:
        raise ValueError(
            f"LLM response fields mismatch: expected={sorted(expected)}, "
            f"actual={sorted(value)}"
        )

    result: Dict[str, Any] = {}
    for field in ARRAY_FIELDS:
        items = value[field]
        if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
            raise ValueError(f"{field} must be an array of strings")
        result[field] = [normalize_text(item) for item in items if normalize_text(item)]
    if len(result["keywords"]) != 5:
        raise ValueError("keywords must contain exactly five items")
    if not 3 <= len(result["research_topics"]) <= 5:
        raise ValueError("research_topics must contain three to five items")
    for field in SCALAR_FIELDS:
        if not isinstance(value[field], str):
            raise ValueError(f"{field} must be a string")
    result.update(
        {
            field: (
                _normalize_multiline_text(value[field])
                if field == "core_method"
                else normalize_text(value[field])
            )
            for field in SCALAR_FIELDS
        }
    )

    if CJK_PATTERN.search(result["core_method"]):
        raise ValueError("analysis contains CJK characters")
    core_method_words = count_english_words(result["core_method"])
    if not 300 <= core_method_words <= 600:
        raise ValueError(
            "core_method must contain 300 to 600 English words; "
            f"actual={core_method_words}"
        )

    main_text = _main_text_without_references(full_text)
    status = result["code_status"].lower()
    if status not in CODE_STATUSES:
        raise ValueError("code_status must be yes, no, or unknown")
    result["code_status"] = status
    code_url = result["code_url"]
    code_evidence = result["code_evidence"]
    deterministic_evidence = (
        _find_code_evidence(full_text, status) if status != "unknown" else ""
    )
    if status == "unknown":
        if code_url or code_evidence:
            raise ValueError("unknown code_status requires empty URL and evidence")
        if _find_code_evidence(full_text, "yes") or _find_code_evidence(
            full_text, "no"
        ):
            raise ValueError("code_status=unknown conflicts with explicit body evidence")
    else:
        if not deterministic_evidence:
            raise ValueError("code_status is not supported by the paper body")
        if not code_evidence or not _evidence_in_text(code_evidence, main_text):
            # 模型可能轻微改写证据；使用程序定位到的正文原句保证可审计性。
            result["code_evidence"] = deterministic_evidence
        if status == "no" and code_url:
            raise ValueError("code_status=no requires an empty code_url")
    repositories = extract_github_repositories(full_text)
    if status == "yes" and not code_url and len(repositories) == 1:
        code_url = repositories[0]
        result["code_url"] = code_url
    if code_url:
        if status != "yes":
            raise ValueError("a code_url requires code_status=yes")
        try:
            normalized_url = normalize_github_url(code_url)
        except ValueError:
            if len(repositories) == 1:
                normalized_url = repositories[0]
            elif repositories:
                raise
            else:
                # 正文只说“代码在此”但 MinerU 丢失超链接时，禁止模型补造地址。
                normalized_url = ""
        if normalized_url and normalized_url not in repositories:
            if len(repositories) == 1:
                normalized_url = repositories[0]
            elif repositories:
                raise ValueError(
                    "code_url must appear in the paper body before references"
                )
            else:
                normalized_url = ""
        result["code_url"] = normalized_url

    venue = result["venue"]
    venue_evidence = result["venue_evidence"]
    if venue:
        if venue.casefold() == "arxiv":
            raise ValueError("arXiv is a source, not a publication venue")
        if len(venue) > 255 or not venue_evidence:
            raise ValueError("venue requires concise evidence")
        from_journal_ref = bool(journal_ref) and _evidence_in_text(
            venue_evidence, journal_ref
        )
        from_body = _evidence_in_text(venue_evidence, main_text)
        if not from_journal_ref and not from_body:
            raise ValueError("venue_evidence must quote journal_ref or the paper body")
        if from_body and (
            VENUE_REJECTION_PATTERN.search(venue_evidence)
            or not VENUE_ACCEPTANCE_PATTERN.search(venue_evidence)
        ):
            raise ValueError("venue evidence must state accepted or published status")
    elif venue_evidence:
        raise ValueError("empty venue requires empty venue_evidence")

    analysis_text = _analysis_text(result)
    if CJK_PATTERN.search(analysis_text):
        raise ValueError("analysis contains CJK characters")
    language = detect_english_text(analysis_text, threshold=0.70)
    if not language.is_english:
        raise ValueError(
            f"analysis must be English: detected={language.language}, "
            f"confidence={language.confidence:.3f}"
        )
    return result


def apply_analysis_metadata(paper: Paper, analysis: Dict[str, Any]) -> None:
    """把已校验的 venue 和开源字段映射到论文主记录。"""
    status = str(analysis["code_status"])
    paper.venue = str(analysis["venue"]) or None
    paper.is_code_open_source = status
    paper.is_code_open = {"yes": 1, "no": 0, "unknown": None}[status]
    paper.code_url = str(analysis["code_url"]) or None


class DeepSeekAnalyzer:
    """调用 DeepSeek 生成严格的英文结构化论文分析。"""

    def __init__(
        self,
        provider: str = "deepseek",
        sleep: Callable[[float], None] = time.sleep,
        max_full_text_chars: Optional[int] = None,
    ) -> None:
        """读取 DeepSeek 配置并初始化重试等待函数。"""
        if provider.lower() != "deepseek":
            raise IngestError("当前入库流程仅支持 provider=deepseek")
        self.api_key = os.environ.get("DEEPSEEK_API_KEY") or DEEPSEEK_INFO.get(
            "API_KEY", ""
        )
        self.base_url = (
            os.environ.get("DEEPSEEK_BASE_URL")
            or DEEPSEEK_INFO.get("BASE_URL")
            or "https://api.deepseek.com"
        ).rstrip("/")
        self.model = (
            os.environ.get("DEEPSEEK_CHAT_MODEL")
            or DEEPSEEK_INFO.get("CHAT_MODEL")
            or "deepseek-chat"
        )
        self._sleep = sleep
        configured_limit = max_full_text_chars or int(
            os.environ.get(
                "PAPER_ANALYSIS_MAX_CHARS", str(DEFAULT_MAX_FULL_TEXT_CHARS)
            )
        )
        if configured_limit < 1000:
            raise IngestError("PAPER_ANALYSIS_MAX_CHARS 不能小于 1000")
        self.max_full_text_chars = configured_limit
        if not self.api_key:
            raise IngestError("DEEPSEEK_API_KEY 不能为空")

    def analyze(self, paper: Paper) -> Dict[str, Any]:
        """基于 MinerU 全文分析论文，临时错误或非法输出最多重试三次。"""
        source_text = (paper.full_text or "").strip()
        full_text = validate_full_text(
            strip_analysis_sections(source_text), self.max_full_text_chars
        )
        paper.raw_metadata["analysis_preprocessing"] = {
            "source_chars": len(source_text),
            "analysis_chars": len(full_text),
            "removed_chars": max(0, len(source_text) - len(full_text)),
            "related_work_and_references_removed": True,
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": analyze_paper_metadata_prompt()},
                {
                    "role": "user",
                    "content": analyze_paper_metadata_user_prompt(
                        paper.title,
                        paper.authors,
                        paper.categories,
                        paper.abstract,
                        str(paper.raw_metadata.get("journal_ref") or ""),
                        full_text,
                    ),
                },
            ],
            "temperature": 0.1,
            # 校内兼容接口关闭思考模式，避免长全文分析耗时过长且保证 JSON 输出稳定。
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
            "max_tokens": 4500,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        last_error: Optional[BaseException] = None
        for attempt in range(3):
            try:
                response = httpx.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    # 全文请求在校内兼容接口上可能需要数分钟，避免过早超时后重复排队。
                    timeout=httpx.Timeout(600, connect=30),
                    follow_redirects=True,
                )
                if response.status_code in (401, 403):
                    raise AuthenticationError("DeepSeek 认证失败")
                if response.status_code == 429 or response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        "DeepSeek 暂时不可用",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                return parse_analysis_json(
                    content,
                    full_text=full_text,
                    journal_ref=str(paper.raw_metadata.get("journal_ref") or ""),
                )
            except AuthenticationError:
                raise
            except ValueError as exc:
                last_error = exc
                print(
                    f"DeepSeek 分析 {paper.arxiv_id} 第 {attempt + 1}/3 次"
                    f"内容校验失败：{exc}",
                    flush=True,
                )
                if attempt < 2:
                    # 把具体校验原因反馈给模型，避免三次重复同一格式错误。
                    payload["messages"].append(
                        {
                            "role": "user",
                            "content": (
                                "上一份 JSON 未通过程序校验，请重新阅读全文并返回完整 JSON。"
                                f"校验错误：{exc}。code_evidence 和 venue_evidence 必须"
                                "逐字复制连续原文；无法提供合格证据时使用 unknown 或空值。"
                                "core_method 必须压缩到 400 至 500 个英文词，且绝不能"
                                "超过 600 词。"
                            ),
                        }
                    )
                    self._sleep(float(2 ** attempt))
            except (
                httpx.HTTPError,
                TypeError,
                KeyError,
                IndexError,
            ) as exc:
                last_error = exc
                print(
                    f"DeepSeek 分析 {paper.arxiv_id} 第 {attempt + 1}/3 次"
                    f"请求失败：{type(exc).__name__}",
                    flush=True,
                )
                if attempt < 2:
                    self._sleep(float(2 ** attempt))
        raise IngestError(
            f"DeepSeek 分析 {paper.arxiv_id} 重试 3 次后仍失败：{last_error}"
        )
