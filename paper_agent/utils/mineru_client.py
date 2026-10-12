"""封装 MinerU PDF 批量解析、缓存和标题摘要抽取。"""

from __future__ import annotations

import json
import os
import re
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE_ROOT = PROJECT_ROOT / "papers" / "mineru_cache"
MAX_PDF_BYTES = 200 * 1024 * 1024
MAX_MARKDOWN_BYTES = 50 * 1024 * 1024
MAX_BATCH_SIZE = 50


class MinerUError(RuntimeError):
    """MinerU 请求、文件校验或解析结果不符合要求时抛出。"""


class MinerUAuthenticationError(MinerUError):
    """MinerU 拒绝当前 Token 时抛出。"""


@dataclass(frozen=True)
class MinerUDocument:
    """描述一篇需要交给 MinerU 解析的 arXiv PDF。"""

    paper_id: int
    pdf_url: str
    fallback_title: str
    fallback_abstract: str


@dataclass(frozen=True)
class MinerUExtraction:
    """保存 MinerU 全文、确定的标题摘要和字段来源。"""

    paper_id: int
    title: str
    abstract: str
    title_source: str
    abstract_source: str
    markdown_path: Path
    full_text: str = ""


@dataclass
class MinerUBatchOutcome:
    """汇总一批 MinerU 文档的成功结果、失败信息和缓存统计。"""

    extractions: Dict[int, MinerUExtraction] = field(default_factory=dict)
    errors: Dict[int, str] = field(default_factory=dict)
    pdf_downloaded: int = 0
    cache_hits: int = 0


def _clean_markdown_text(value: str) -> str:
    """移除常见 Markdown 标记并合并空白。

    参数:
        value: Markdown 片段。

    返回:
        适合写入数据库的单行纯文本。
    """
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", value)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[`*_~]", "", text)
    return " ".join(text.split()).strip()


def _safe_error_text(value: Any, limit: int = 300) -> str:
    """清理服务错误文本中的 URL 和疑似密钥，避免写入日志。

    参数:
        value: 外部服务返回的错误内容。
        limit: 最多保留的字符数。

    返回:
        已脱敏并截断的单行错误文本。
    """
    text = " ".join(str(value or "未知错误").split())
    text = re.sub(r"https?://\S+", "[URL]", text, flags=re.IGNORECASE)
    text = re.sub(r"\bsk-[A-Za-z0-9_-]+", "[TOKEN]", text)
    return text[:limit]


def extract_title_and_abstract(
    markdown: str, fallback_title: str, fallback_abstract: str
) -> Tuple[str, str, str, str]:
    """从 MinerU Markdown 确定论文标题和摘要。

    参数:
        markdown: MinerU 返回的 ``full.md`` 内容。
        fallback_title: arXiv 元数据中的标题。
        fallback_abstract: arXiv 元数据中的摘要。

    返回:
        ``(title, abstract, title_source, abstract_source)``；来源为
        ``mineru`` 或 ``arxiv_fallback``。
    """
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    title = ""
    for line in lines:
        match = re.match(r"^\s{0,3}#\s+(.+?)\s*$", line)
        if match:
            candidate = _clean_markdown_text(match.group(1))
            if 5 <= len(candidate) <= 500:
                title = candidate
                break

    abstract_lines: List[str] = []
    collecting = False
    for line in lines:
        heading = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
        plain = _clean_markdown_text(line)
        if not collecting:
            heading_text = _clean_markdown_text(heading.group(1)) if heading else plain
            inline = re.match(r"^(?:abstract|摘要)\s*[:：—-]\s*(.+)$", heading_text, re.I)
            if re.fullmatch(r"(?:abstract|摘要)\s*[:：]?", heading_text, re.I):
                collecting = True
                continue
            if inline:
                collecting = True
                abstract_lines.append(inline.group(1))
                continue
        else:
            if heading:
                break
            if plain:
                abstract_lines.append(plain)

    parsed_abstract = _clean_markdown_text(" ".join(abstract_lines))
    if not 50 <= len(parsed_abstract) <= 30000:
        parsed_abstract = ""

    final_title = title or _clean_markdown_text(fallback_title)
    final_abstract = parsed_abstract or _clean_markdown_text(fallback_abstract)
    return (
        final_title,
        final_abstract,
        "mineru" if title else "arxiv_fallback",
        "mineru" if parsed_abstract else "arxiv_fallback",
    )


class MinerUClient:
    """下载论文 PDF，通过 MinerU 批量解析并复用本地缓存。"""

    def __init__(
        self,
        model_version: str = "vlm",
        token: Optional[str] = None,
        base_url: Optional[str] = None,
        cache_root: Optional[Path] = None,
        client: Optional[httpx.Client] = None,
        poll_interval: float = 5.0,
        poll_timeout: float = 900.0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """初始化 MinerU 客户端和缓存策略。

        参数:
            model_version: MinerU 模型版本，首版默认 ``vlm``。
            token: MinerU Token；为空时读取 ``MINERU_TOKEN``。
            base_url: MinerU API 根地址；为空时读取环境变量。
            cache_root: PDF、ZIP 和 Markdown 缓存根目录。
            client: 可选 httpx 客户端，用于连接复用和测试注入。
            poll_interval: 任务轮询间隔秒数。
            poll_timeout: 单个批次最长等待秒数。
            sleep: 等待函数，测试时可替换。
            monotonic: 单调时钟函数，测试时可替换。

        异常:
            MinerUError: Token 为空或模型版本不受支持。
        """
        if model_version not in {"vlm", "pipeline"}:
            raise MinerUError(f"不支持的 MinerU 模型版本：{model_version}")
        self.model_version = model_version
        self.token = token or os.environ.get("MINERU_TOKEN", "")
        if not self.token:
            raise MinerUError("MINERU_TOKEN 不能为空")
        self.base_url = (
            base_url or os.environ.get("MINERU_BASE_URL") or "https://mineru.net/api/v4"
        ).rstrip("/")
        self.cache_root = Path(cache_root or DEFAULT_CACHE_ROOT).resolve()
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self._client = client
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout
        self._sleep = sleep
        self._monotonic = monotonic

    def _headers(self) -> Dict[str, str]:
        """构造 MinerU API 鉴权请求头。

        返回:
            包含 Bearer Token 和 JSON 类型的请求头。
        """
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def _request_api(
        self,
        client: httpx.Client,
        method: str,
        path: str,
        operation: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """调用 MinerU API，并对 429 和服务端错误执行重试。

        参数:
            client: 已初始化的 httpx 客户端。
            method: HTTP 方法。
            path: 相对 ``MINERU_BASE_URL`` 的路径。
            operation: 用于脱敏错误日志的操作名称。
            kwargs: 传递给 httpx 的其他参数。

        返回:
            成功的 HTTP 响应。

        异常:
            MinerUAuthenticationError: Token 无效。
            MinerUError: 请求重试后仍失败。
        """
        last_error: Optional[BaseException] = None
        url = f"{self.base_url}/{path.lstrip('/')}"
        for attempt in range(3):
            try:
                response = client.request(
                    method, url, headers=self._headers(), **kwargs
                )
                if response.status_code in (401, 403):
                    raise MinerUAuthenticationError("MinerU 认证失败")
                if response.status_code == 429 or response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"{operation} 暂时不可用",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                return response
            except MinerUAuthenticationError:
                raise
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < 2:
                    self._sleep(float(2 ** attempt))
        raise MinerUError(f"{operation} 重试 3 次后仍失败：{last_error}")

    @staticmethod
    def _check_api_body(
        response: httpx.Response, operation: str
    ) -> Dict[str, Any]:
        """校验 MinerU JSON 响应中的业务状态码。

        参数:
            response: MinerU HTTP 响应。
            operation: 当前操作名称。

        返回:
            响应中的 ``data`` 对象。

        异常:
            MinerUError: JSON 结构错误或业务状态码非零。
        """
        try:
            body = response.json()
        except ValueError as exc:
            raise MinerUError(f"{operation} 返回的不是合法 JSON") from exc
        if not isinstance(body, dict) or body.get("code") != 0:
            code = body.get("code") if isinstance(body, dict) else "unknown"
            raise MinerUError(f"{operation} 失败，业务状态码：{code}")
        data = body.get("data")
        if not isinstance(data, dict):
            raise MinerUError(f"{operation} 响应缺少 data 对象")
        return data

    def _document_dir(self, paper_id: int) -> Path:
        """返回单篇论文的 MinerU 缓存目录。

        参数:
            paper_id: 稳定论文主键。

        返回:
            位于缓存根目录下的论文专属目录。
        """
        path = self.cache_root / str(int(paper_id))
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _valid_pdf(path: Path) -> bool:
        """检查缓存文件是否是大小合规的 PDF。

        参数:
            path: 待检查 PDF 路径。

        返回:
            文件存在、大小合规且以 ``%PDF`` 开头时返回 True。
        """
        if not path.is_file() or not 5 <= path.stat().st_size <= MAX_PDF_BYTES:
            return False
        with path.open("rb") as file:
            return file.read(4) == b"%PDF"

    def _download_pdf(
        self, client: httpx.Client, document: MinerUDocument, target: Path
    ) -> bool:
        """流式下载并校验一篇 arXiv PDF。

        参数:
            client: 已初始化的 httpx 客户端。
            document: 待下载论文描述。
            target: 最终缓存路径。

        返回:
            实际发生下载时返回 True，命中有效缓存时返回 False。

        异常:
            MinerUError: 下载失败、文件过大或内容不是 PDF。
        """
        if self._valid_pdf(target):
            return False
        temporary = target.with_suffix(".pdf.part")
        last_error: Optional[BaseException] = None
        for attempt in range(3):
            try:
                size = 0
                with client.stream(
                    "GET",
                    document.pdf_url,
                    headers={"User-Agent": "paper-recommender/0.2"},
                ) as response:
                    if response.status_code == 429 or response.status_code >= 500:
                        raise httpx.HTTPStatusError(
                            "PDF 下载服务暂时不可用",
                            request=response.request,
                            response=response,
                        )
                    response.raise_for_status()
                    with temporary.open("wb") as file:
                        for chunk in response.iter_bytes():
                            size += len(chunk)
                            if size > MAX_PDF_BYTES:
                                raise MinerUError("PDF 文件超过 200MB 限制")
                            file.write(chunk)
                if not self._valid_pdf(temporary):
                    raise MinerUError("下载内容不是有效 PDF")
                os.replace(temporary, target)
                return True
            except MinerUError:
                temporary.unlink(missing_ok=True)
                raise
            except httpx.HTTPError as exc:
                temporary.unlink(missing_ok=True)
                last_error = exc
                if attempt < 2:
                    self._sleep(float(2 ** attempt))
        raise MinerUError(f"PDF 下载重试 3 次后仍失败：{last_error}")

    def _apply_upload_urls(
        self,
        client: httpx.Client,
        documents: Sequence[MinerUDocument],
        pdf_paths: Dict[int, Path],
    ) -> Tuple[str, Dict[int, str]]:
        """申请上传地址并把本地 PDF 上传给 MinerU。

        参数:
            client: 已初始化的 httpx 客户端。
            documents: 本批论文描述，最多 50 篇。
            pdf_paths: paper_id 到本地 PDF 的映射。

        返回:
            ``(batch_id, upload_errors)``。

        异常:
            MinerUError: 批量大小错误或申请上传地址失败。
        """
        if not documents or len(documents) > MAX_BATCH_SIZE:
            raise MinerUError("MinerU 单批文档数量必须为 1 到 50")
        payload = {
            "files": [
                {
                    "name": f"{document.paper_id}.pdf",
                    "data_id": str(document.paper_id),
                    "is_ocr": False,
                }
                for document in documents
            ],
            "model_version": self.model_version,
            "language": "en",
            "enable_formula": True,
            "enable_table": True,
        }
        response = self._request_api(
            client,
            "POST",
            "file-urls/batch",
            "申请 MinerU 上传地址",
            json=payload,
        )
        data = self._check_api_body(response, "申请 MinerU 上传地址")
        batch_id = data.get("batch_id")
        upload_urls = data.get("file_urls")
        if not isinstance(batch_id, str) or not batch_id:
            raise MinerUError("MinerU 响应缺少 batch_id")
        if not isinstance(upload_urls, list) or len(upload_urls) != len(documents):
            raise MinerUError("MinerU 上传地址数量与文件数量不一致")

        errors: Dict[int, str] = {}
        for document, upload_url in zip(documents, upload_urls):
            if not isinstance(upload_url, str) or not upload_url:
                errors[document.paper_id] = "MinerU 返回了无效上传地址"
                continue
            uploaded = False
            for attempt in range(3):
                try:
                    with pdf_paths[document.paper_id].open("rb") as file:
                        # 官方要求上传预签名地址时不要设置 Content-Type。
                        upload = client.put(upload_url, content=file)
                    if upload.status_code == 429 or upload.status_code >= 500:
                        raise httpx.HTTPStatusError(
                            "MinerU 上传服务暂时不可用",
                            request=upload.request,
                            response=upload,
                        )
                    upload.raise_for_status()
                    uploaded = True
                    break
                except (OSError, httpx.HTTPError):
                    if attempt < 2:
                        self._sleep(float(2 ** attempt))
            if not uploaded:
                errors[document.paper_id] = "PDF 上传 MinerU 重试 3 次后仍失败"
        return batch_id, errors

    def _poll_batch(
        self,
        client: httpx.Client,
        batch_id: str,
        expected_ids: Sequence[int],
    ) -> Dict[int, Dict[str, Any]]:
        """轮询 MinerU 批量任务直到目标文件全部结束。

        参数:
            client: 已初始化的 httpx 客户端。
            batch_id: MinerU 批次 ID。
            expected_ids: 已成功上传并需要等待的 paper_id。

        返回:
            paper_id 到最终任务结果的映射。

        异常:
            MinerUError: 超时、响应缺少任务结果或 API 请求失败。
        """
        expected = {int(value) for value in expected_ids}
        completed: Dict[int, Dict[str, Any]] = {}
        deadline = self._monotonic() + self.poll_timeout
        while self._monotonic() < deadline:
            response = self._request_api(
                client,
                "GET",
                f"extract-results/batch/{batch_id}",
                "查询 MinerU 解析结果",
            )
            data = self._check_api_body(response, "查询 MinerU 解析结果")
            items = data.get("extract_result")
            if not isinstance(items, list):
                raise MinerUError("MinerU 批量结果缺少 extract_result 列表")
            for item in items:
                if not isinstance(item, dict):
                    continue
                data_id = item.get("data_id")
                if data_id is None:
                    file_name = str(item.get("file_name", ""))
                    data_id = Path(file_name).stem
                try:
                    paper_id = int(data_id)
                except (TypeError, ValueError):
                    continue
                if paper_id in expected and item.get("state") in {"done", "failed"}:
                    completed[paper_id] = item
            if set(completed) == expected:
                return completed
            self._sleep(self.poll_interval)
        missing = sorted(expected - set(completed))
        raise MinerUError(f"MinerU 批量任务等待超时，未完成数量：{len(missing)}")

    def _download_result(
        self,
        client: httpx.Client,
        paper_id: int,
        result: Dict[str, Any],
        document_dir: Path,
        batch_id: str,
    ) -> Path:
        """下载 MinerU 结果 ZIP，并安全保存其中的 full.md。

        参数:
            client: 已初始化的 httpx 客户端。
            paper_id: 论文主键。
            result: 单个 MinerU 最终任务结果。
            document_dir: 当前论文缓存目录。
            batch_id: MinerU 批次 ID，仅用于本地 manifest。

        返回:
            本地 ``full.md`` 路径。

        异常:
            MinerUError: 任务失败、下载失败或 ZIP 不包含合法 full.md。
        """
        if result.get("state") != "done":
            reason = _safe_error_text(result.get("err_msg"))
            raise MinerUError(f"MinerU 解析失败：{reason}")
        zip_url = result.get("full_zip_url")
        if not isinstance(zip_url, str) or not zip_url:
            raise MinerUError("MinerU 完成结果缺少 full_zip_url")

        zip_path = document_dir / "result.zip"
        temporary = document_dir / "result.zip.part"
        last_error: Optional[BaseException] = None
        for attempt in range(3):
            try:
                with client.stream("GET", zip_url) as response:
                    if response.status_code == 429 or response.status_code >= 500:
                        raise httpx.HTTPStatusError(
                            "MinerU 结果下载服务暂时不可用",
                            request=response.request,
                            response=response,
                        )
                    response.raise_for_status()
                    size = 0
                    with temporary.open("wb") as file:
                        for chunk in response.iter_bytes():
                            size += len(chunk)
                            if size > MAX_PDF_BYTES:
                                raise MinerUError("MinerU 结果 ZIP 超过 200MB")
                            file.write(chunk)
                os.replace(temporary, zip_path)
                break
            except MinerUError:
                temporary.unlink(missing_ok=True)
                raise
            except (OSError, httpx.HTTPError) as exc:
                temporary.unlink(missing_ok=True)
                last_error = exc
                if attempt < 2:
                    self._sleep(float(2 ** attempt))
        else:
            raise MinerUError("下载 MinerU 结果 ZIP 重试 3 次后仍失败") from last_error

        try:
            with zipfile.ZipFile(zip_path) as archive:
                candidates = [
                    info
                    for info in archive.infolist()
                    if not info.is_dir() and Path(info.filename).name == "full.md"
                ]
                if not candidates:
                    raise MinerUError("MinerU 结果 ZIP 中不存在 full.md")
                info = min(candidates, key=lambda item: len(item.filename))
                if not 1 <= info.file_size <= MAX_MARKDOWN_BYTES:
                    raise MinerUError("MinerU full.md 大小不符合要求")
                markdown = archive.read(info).decode("utf-8-sig")
        except (zipfile.BadZipFile, UnicodeDecodeError, OSError) as exc:
            raise MinerUError("MinerU 结果 ZIP 无法读取") from exc

        markdown_path = document_dir / "full.md"
        markdown_path.write_text(markdown, encoding="utf-8")
        manifest = {
            "paper_id": int(paper_id),
            "batch_id": batch_id,
            "model_version": self.model_version,
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }
        (document_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return markdown_path

    @staticmethod
    def _extraction_from_markdown(
        document: MinerUDocument, markdown_path: Path
    ) -> MinerUExtraction:
        """从缓存 Markdown 构造字段抽取结果。

        参数:
            document: 原始 arXiv 论文描述。
            markdown_path: MinerU ``full.md`` 路径。

        返回:
            包含最终标题、摘要和来源的抽取结果。

        异常:
            MinerUError: Markdown 为空或无法读取。
        """
        try:
            markdown = markdown_path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as exc:
            raise MinerUError("MinerU full.md 无法读取") from exc
        if not markdown.strip():
            raise MinerUError("MinerU full.md 为空")
        title, abstract, title_source, abstract_source = extract_title_and_abstract(
            markdown, document.fallback_title, document.fallback_abstract
        )
        if not title or not abstract:
            raise MinerUError("标题或摘要在 MinerU 和 arXiv 中均为空")
        return MinerUExtraction(
            paper_id=document.paper_id,
            title=title,
            abstract=abstract,
            title_source=title_source,
            abstract_source=abstract_source,
            markdown_path=markdown_path,
            full_text=markdown,
        )

    def extract_batch(self, documents: Sequence[MinerUDocument]) -> MinerUBatchOutcome:
        """解析一批 PDF，优先复用缓存并隔离单篇失败。

        参数:
            documents: 待解析论文，单次最多 50 篇。

        返回:
            成功结果、失败原因、下载数和缓存命中数。

        异常:
            MinerUAuthenticationError: Token 无效，继续处理没有意义。
            MinerUError: 批次级 API 错误或输入数量错误。
        """
        if not documents or len(documents) > MAX_BATCH_SIZE:
            raise MinerUError("MinerU 单批文档数量必须为 1 到 50")
        ids = [int(document.paper_id) for document in documents]
        if len(set(ids)) != len(ids):
            raise MinerUError("同一 MinerU 批次不能包含重复 paper_id")

        outcome = MinerUBatchOutcome()
        pending: List[MinerUDocument] = []
        for document in documents:
            markdown_path = self._document_dir(document.paper_id) / "full.md"
            if markdown_path.is_file() and markdown_path.stat().st_size > 0:
                try:
                    outcome.extractions[document.paper_id] = self._extraction_from_markdown(
                        document, markdown_path
                    )
                    outcome.cache_hits += 1
                    continue
                except MinerUError:
                    markdown_path.unlink(missing_ok=True)
            pending.append(document)

        if not pending:
            return outcome

        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=60.0, follow_redirects=True)
        try:
            pdf_paths: Dict[int, Path] = {}
            ready: List[MinerUDocument] = []
            for document in pending:
                pdf_path = self._document_dir(document.paper_id) / "source.pdf"
                try:
                    if self._download_pdf(client, document, pdf_path):
                        outcome.pdf_downloaded += 1
                    pdf_paths[document.paper_id] = pdf_path
                    ready.append(document)
                except MinerUError as exc:
                    outcome.errors[document.paper_id] = str(exc)

            if not ready:
                return outcome

            batch_id, upload_errors = self._apply_upload_urls(client, ready, pdf_paths)
            outcome.errors.update(upload_errors)
            uploaded = [
                document
                for document in ready
                if document.paper_id not in upload_errors
            ]
            if not uploaded:
                return outcome
            final_results = self._poll_batch(
                client, batch_id, [document.paper_id for document in uploaded]
            )
            for document in uploaded:
                try:
                    markdown_path = self._download_result(
                        client,
                        document.paper_id,
                        final_results[document.paper_id],
                        self._document_dir(document.paper_id),
                        batch_id,
                    )
                    outcome.extractions[document.paper_id] = self._extraction_from_markdown(
                        document, markdown_path
                    )
                except (KeyError, MinerUError) as exc:
                    outcome.errors[document.paper_id] = str(exc)
            return outcome
        finally:
            if owns_client:
                client.close()
