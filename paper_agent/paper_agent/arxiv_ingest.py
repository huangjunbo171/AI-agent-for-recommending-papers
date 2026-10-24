"""编排 arXiv、MinerU、DeepSeek、MySQL 和 LanceDB 论文入库。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = PROJECT_ROOT / "paper_agent"
MINERU_CACHE_ROOT = (PROJECT_ROOT / "papers" / "mineru_cache").resolve()
MAX_MINERU_BATCH_SIZE = 50
MAX_NORMAL_INGEST_LIMIT = 100
MAX_ARXIV_CANDIDATES = 200
sys.path.insert(0, str(PACKAGE_ROOT))

from paper_agent.prompts_test import (  # noqa: E402
    analyze_paper_metadata_prompt,
    analyze_paper_metadata_user_prompt,
)
from utils.arxiv_source import (  # noqa: E402
    IngestError,
    Paper,
    canonical_arxiv_id,
    fetch_arxiv_papers,
    normalize_text,
    parse_arxiv_datetime,
    parse_arxiv_feed,
    stable_paper_id,
)
from utils.embedding_provider import create_embedder  # noqa: E402
from utils.lancedb_store import LanceDBPaperStore  # noqa: E402
from utils.mineru_client import (  # noqa: E402
    MinerUBatchOutcome,
    MinerUAuthenticationError,
    MinerUClient,
    MinerUDocument,
    MinerUError,
    MinerUExtraction,
)
from utils.mysql_paper_repository import MySQLPaperRepository  # noqa: E402
from utils.paper_analyzer import (  # noqa: E402
    AuthenticationError,
    DeepSeekAnalyzer,
    apply_analysis_metadata,
    count_english_words,
    detect_english_text,
    parse_analysis_json,
    validate_english_paper,
)


def load_dotenv(path: Path) -> None:
    """加载简单 KEY=VALUE 配置且不覆盖已有环境变量。"""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def build_embedding_text(paper: Paper) -> str:
    """使用最终英文标题和摘要构造向量文本。"""
    title = normalize_text(paper.title)
    abstract = normalize_text(paper.abstract)
    if not title or not abstract:
        raise IngestError(f"论文 {paper.arxiv_id} 的标题或摘要为空")
    return f"Title: {title}\nAbstract: {abstract}"


def arxiv_candidate_pool_size(limit: int) -> int:
    """按目标数量扩大 arXiv 候选池，并限制单次最多读取 200 篇。"""
    return max(30, min(limit * 2, MAX_ARXIV_CANDIDATES))


def build_lancedb_records(
    papers: Sequence[Paper], embedding_model: str
) -> List[Dict[str, Any]]:
    """把已向量化论文映射为 paper_embeddings 六字段记录。"""
    records: List[Dict[str, Any]] = []
    for paper in papers:
        if not paper.embedding_text or paper.vector is None:
            raise IngestError(f"论文 {paper.arxiv_id} 尚未完成向量生成")
        records.append(
            {
                "paper_id": paper.paper_id,
                "title": paper.title,
                "abstract": paper.abstract,
                "embedding_text": paper.embedding_text,
                "embedding_model": embedding_model,
                "vector": paper.vector,
            }
        )
    return records


def prepare_embeddings(
    papers: Sequence[Paper], provider: str, embedding_model: Optional[str]
) -> Any:
    """构造向量文本并用指定 Provider 批量生成向量。"""
    for paper in papers:
        paper.embedding_text = build_embedding_text(paper)
    embedder = create_embedder(provider, embedding_model)
    vectors = embedder.encode([paper.embedding_text for paper in papers])
    if len(vectors) != len(papers):
        raise IngestError("向量数量与论文数量不一致")
    for paper, vector in zip(papers, vectors):
        paper.vector = vector
    return embedder


def _read_full_text(markdown_path: Path) -> str:
    """读取 MinerU Markdown 全文，拒绝空文件或无法解码的缓存。"""
    try:
        full_text = markdown_path.read_text(encoding="utf-8-sig").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise IngestError(f"MinerU 全文缓存无法读取：{markdown_path.name}") from exc
    if not full_text:
        raise IngestError("MinerU 全文缓存为空")
    return full_text


def _load_cached_full_text(paper: Paper) -> str:
    """从 raw_metadata 指向的安全缓存路径加载已有论文全文。"""
    mineru_metadata = paper.raw_metadata.get("mineru")
    cache_value = (
        mineru_metadata.get("markdown_cache")
        if isinstance(mineru_metadata, dict)
        else None
    )
    if not isinstance(cache_value, str) or not cache_value.strip():
        raise IngestError(f"论文 {paper.arxiv_id} 缺少 MinerU 全文缓存路径")

    candidate = Path(cache_value)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(MINERU_CACHE_ROOT)
    except ValueError as exc:
        raise IngestError(f"论文 {paper.arxiv_id} 的全文缓存路径不安全") from exc
    return _read_full_text(resolved)


def apply_mineru_extraction(
    paper: Paper, extraction: MinerUExtraction, model_version: str
) -> int:
    """应用 MinerU 字段并记录缓存位置和字段来源。"""
    paper.title = extraction.title
    paper.abstract = extraction.abstract
    paper.full_text = extraction.full_text.strip() or _read_full_text(
        extraction.markdown_path
    )
    try:
        markdown_cache = str(extraction.markdown_path.relative_to(PROJECT_ROOT))
    except ValueError:
        markdown_cache = extraction.markdown_path.name
    paper.raw_metadata["mineru"] = {
        "model_version": model_version,
        "title_source": extraction.title_source,
        "abstract_source": extraction.abstract_source,
        "markdown_cache": markdown_cache.replace("\\", "/"),
        "full_text_chars": len(paper.full_text),
    }
    return sum(
        source == "arxiv_fallback"
        for source in (extraction.title_source, extraction.abstract_source)
    )


def _record_language(paper: Paper) -> bool:
    """检测最终标题和摘要，记录语言结果并返回英文判定。"""
    result = validate_english_paper(paper)
    paper.raw_metadata["language"] = {
        "detected": result.language,
        "confidence": round(result.confidence, 6),
        "is_english": result.is_english,
    }
    return result.is_english


def _planned_updates(papers: Sequence[Paper]) -> List[Dict[str, Any]]:
    """生成 dry-run 和验收日志使用的安全字段预览。"""
    return [
        {
            "paper_id": paper.paper_id,
            "venue": paper.venue,
            "code_status": paper.is_code_open_source,
            "code_url": paper.code_url,
            "core_method_words": count_english_words(
                str((paper.analysis or {}).get("core_method", ""))
            ),
        }
        for paper in papers
    ]


def prepare_papers_with_mineru(
    candidates: Sequence[Paper],
    limit: int,
    mineru: MinerUClient,
    analyzer: DeepSeekAnalyzer,
    summary: Dict[str, Any],
    analysis_workers: int = 1,
) -> List[Paper]:
    """批量解析 PDF，并发分析英文论文，直到补足目标数量。"""
    prepared: List[Paper] = []
    used_ids: set[int] = set()
    candidate_index = 0

    while candidate_index < len(candidates) and len(prepared) < limit:
        remaining = limit - len(prepared)
        batch: List[Paper] = []
        batch_size = min(remaining, MAX_MINERU_BATCH_SIZE)
        while candidate_index < len(candidates) and len(batch) < batch_size:
            paper = candidates[candidate_index]
            candidate_index += 1
            if paper.paper_id in used_ids:
                summary["skipped"] += 1
                continue
            used_ids.add(paper.paper_id)
            batch.append(paper)
        if not batch:
            continue

        documents = [
            MinerUDocument(
                paper_id=paper.paper_id,
                pdf_url=paper.pdf_url,
                fallback_title=paper.title,
                fallback_abstract=paper.abstract,
            )
            for paper in batch
        ]
        try:
            outcome: MinerUBatchOutcome = mineru.extract_batch(documents)
        except MinerUAuthenticationError:
            raise
        except MinerUError as exc:
            for paper in batch:
                summary["skipped"] += 1
                summary["failures"].append(
                    f"{paper.arxiv_id}: MinerU 批次失败：{exc}"
                )
            continue

        summary["pdf_downloaded"] += outcome.pdf_downloaded
        summary["mineru_parsed"] += len(outcome.extractions)
        papers_to_analyze: List[Paper] = []
        for paper in batch:
            extraction = outcome.extractions.get(paper.paper_id)
            if extraction is None:
                summary["skipped"] += 1
                reason = outcome.errors.get(paper.paper_id, "MinerU 未返回解析结果")
                summary["failures"].append(f"{paper.arxiv_id}: {reason}")
                continue
            summary["mineru_field_fallbacks"] += apply_mineru_extraction(
                paper, extraction, mineru.model_version
            )
            summary["full_text_loaded"] += 1

            # 只让英文论文进入 DeepSeek，避免翻译或污染来源字段。
            if not _record_language(paper):
                summary["skipped"] += 1
                summary["non_english_skipped"] += 1
                language = paper.raw_metadata["language"]
                summary["failures"].append(
                    f"{paper.arxiv_id}: 非英文论文 "
                    f"({language['detected']}, {language['confidence']})"
                )
                continue

            papers_to_analyze.append(paper)

        # 全文分析是链路中最耗时的阶段，使用有限并发复用已验证的校内接口。
        worker_count = min(analysis_workers, len(papers_to_analyze))
        if worker_count == 0:
            continue
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_papers: Dict[Future[Dict[str, Any]], Paper] = {
                executor.submit(analyzer.analyze, paper): paper
                for paper in papers_to_analyze
            }
            for future in as_completed(future_papers):
                paper = future_papers[future]
                try:
                    paper.analysis = future.result()
                    apply_analysis_metadata(paper, paper.analysis)
                except AuthenticationError:
                    # 密钥失效时取消尚未开始的分析，停止继续消耗候选与接口配额。
                    for pending in future_papers:
                        pending.cancel()
                    raise
                except (IngestError, ValueError, httpx.HTTPError) as exc:
                    summary["skipped"] += 1
                    summary["failures"].append(f"{paper.arxiv_id}: {exc}")
                    continue
                prepared.append(paper)
                summary["analyzed"] = len(prepared)
                print(
                    f"已分析 {len(prepared)}/{limit}：{paper.arxiv_id} {paper.title}",
                    flush=True,
                )

    if len(prepared) < limit:
        details = "; ".join(summary["failures"][:3])
        raise IngestError(
            f"只有 {len(prepared)} 篇英文论文完成解析与分析，目标为 {limit}。"
            f"前几项失败原因：{details}"
        )
    return prepared


def _reanalyze_existing(
    args: argparse.Namespace,
    repository: MySQLPaperRepository,
    summary: Dict[str, Any],
) -> Dict[str, Any]:
    """重新生成已有论文的英文分析，不触碰来源和向量数据。"""
    papers = repository.load_recent(args.limit)
    summary["fetched"] = len(papers)
    if len(papers) < args.limit:
        raise IngestError(
            f"MySQL 只有 {len(papers)} 篇完整论文，目标为 {args.limit}"
        )

    non_english: List[str] = []
    for paper in papers:
        paper.full_text = _load_cached_full_text(paper)
        summary["full_text_loaded"] += 1
        if not _record_language(paper):
            summary["non_english_skipped"] += 1
            non_english.append(paper.arxiv_id)
    if non_english:
        raise IngestError(f"已有论文包含非英文内容，未写库：{non_english}")

    analyzer = DeepSeekAnalyzer(args.provider)
    for paper in papers:
        paper.analysis = analyzer.analyze(paper)
        apply_analysis_metadata(paper, paper.analysis)
        summary["analyzed"] += 1
        summary["reanalyzed"] += 1
        print(
            f"已重新分析 {summary['reanalyzed']}/{args.limit}：{paper.arxiv_id}",
            flush=True,
        )

    expected_ids = sorted(paper.paper_id for paper in papers)
    if args.dry_run:
        summary.update(
            dry_run=True,
            paper_ids=expected_ids,
            analysis_model=analyzer.model,
            planned_updates=_planned_updates(papers),
        )
        return summary

    # 单事务更新分析及论文主表派生字段，来源表和 LanceDB 保持不变。
    repository.upsert_analysis_batch(papers, analyzer.model)
    summary["mysql_written"] = len(papers)
    if repository.complete_ids(expected_ids) != expected_ids:
        raise IngestError("英文重分析后的 MySQL 完整性校验失败")
    summary.update(
        paper_ids=expected_ids,
        analysis_model=analyzer.model,
        planned_updates=_planned_updates(papers),
        verified=True,
    )
    return summary


def ingest(args: argparse.Namespace) -> Dict[str, Any]:
    """编排普通入库、向量修复或已有论文英文重分析。"""
    repository = MySQLPaperRepository()
    summary: Dict[str, Any] = {
        "requested": args.limit,
        "fetched": 0,
        "pdf_downloaded": 0,
        "mineru_parsed": 0,
        "mineru_field_fallbacks": 0,
        "full_text_loaded": 0,
        "non_english_skipped": 0,
        "analyzed": 0,
        "reanalyzed": 0,
        "embedded": 0,
        "mysql_written": 0,
        "lancedb_written": 0,
        "skipped": 0,
        "failures": [],
    }

    if args.reanalyze_existing:
        return _reanalyze_existing(args, repository, summary)

    if args.sync_lancedb_only:
        prepared = repository.load_recent(args.limit)
        summary["fetched"] = len(prepared)
        summary["analyzed"] = len(prepared)
        if len(prepared) < args.limit:
            raise IngestError(
                f"MySQL 只有 {len(prepared)} 篇完整论文，目标为 {args.limit}"
            )
    else:
        candidates = fetch_arxiv_papers(
            args.category, max_results=arxiv_candidate_pool_size(args.limit)
        )
        summary["fetched"] = len(candidates)
        analyzer = DeepSeekAnalyzer(args.provider)
        llm_model_name = analyzer.model
        mineru = MinerUClient(model_version=args.mineru_model)
        prepared = prepare_papers_with_mineru(
            candidates,
            args.limit,
            mineru,
            analyzer,
            summary,
            analysis_workers=getattr(args, "analysis_workers", 1),
        )

    # 分析模式只把完整论文与 LLM 结果写入 MySQL，明确跳过向量接口和 LanceDB。
    if getattr(args, "skip_embedding", False):
        expected_ids = sorted(paper.paper_id for paper in prepared)
        if args.dry_run:
            summary.update(
                dry_run=True,
                embedding_skipped=True,
                paper_ids=expected_ids,
                planned_updates=_planned_updates(prepared),
            )
            return summary
        repository.upsert_batch(prepared, llm_model_name)
        summary["mysql_written"] = len(prepared)
        mysql_ids = repository.complete_ids(expected_ids)
        if mysql_ids != expected_ids:
            raise IngestError(
                "MySQL 校验失败："
                f"expected={expected_ids}, mysql={mysql_ids}"
            )
        summary.update(
            embedding_skipped=True,
            paper_ids=expected_ids,
            analysis_model=llm_model_name,
            verified=True,
        )
        return summary

    embedder = prepare_embeddings(
        prepared, args.embedding_provider, args.embedding_model
    )
    summary["embedded"] = len(prepared)
    if args.dry_run:
        summary.update(
            dry_run=True,
            paper_ids=[paper.paper_id for paper in prepared],
            embedding_model=embedder.model_name,
            planned_updates=_planned_updates(prepared),
        )
        return summary

    if not args.sync_lancedb_only:
        repository.upsert_batch(prepared, llm_model_name)
        summary["mysql_written"] = len(prepared)

    store = LanceDBPaperStore()
    store.ensure_schema()
    records = build_lancedb_records(prepared, embedder.model_name)
    summary["lancedb_written"] = store.upsert_embeddings(records)

    expected_ids = sorted(paper.paper_id for paper in prepared)
    mysql_ids = repository.complete_ids(expected_ids)
    lancedb_ids = set(store.paper_ids())
    missing_lancedb_ids = sorted(set(expected_ids) - lancedb_ids)
    if mysql_ids != expected_ids or missing_lancedb_ids:
        raise IngestError(
            "跨库校验失败："
            f"expected={expected_ids}, mysql={mysql_ids}, "
            f"lancedb_missing={missing_lancedb_ids}"
        )
    summary.update(
        paper_ids=expected_ids,
        embedding_model=embedder.model_name,
        verified=True,
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    """创建论文入库命令行参数解析器。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--category", default="cs.AI")
    parser.add_argument(
        "--limit",
        "--paper-count",
        dest="limit",
        type=int,
        default=10,
        help="本次需要成功入库的论文数量，普通模式支持 1 到 100",
    )
    parser.add_argument("--provider", default="deepseek", choices=["deepseek"])
    parser.add_argument(
        "--analysis-workers",
        type=int,
        default=4,
        help="DeepSeek 全文分析并发数，默认 4",
    )
    parser.add_argument(
        "--embedding-provider", default="dashscope", choices=["dashscope", "bge"]
    )
    parser.add_argument("--embedding-model", default=None)
    parser.add_argument("--mineru-model", default="vlm", choices=["vlm", "pipeline"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--skip-embedding",
        "--analysis-only",
        dest="skip_embedding",
        action="store_true",
        help="完成全文解析和分析并写 MySQL，但不生成向量、不写 LanceDB",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--sync-lancedb-only", action="store_true")
    mode.add_argument("--reanalyze-existing", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """加载本地配置、执行命令并输出 JSON 状态。"""
    load_dotenv(PROJECT_ROOT / ".env")
    args = build_parser().parse_args(argv)
    if args.limit < 1:
        print(json.dumps({"ok": False, "error": "--limit 必须为正整数"}))
        return 2
    if args.analysis_workers < 1 or args.analysis_workers > 8:
        print(
            json.dumps(
                {"ok": False, "error": "--analysis-workers 必须在 1 到 8 之间"},
                ensure_ascii=False,
            )
        )
        return 2
    if args.skip_embedding and args.sync_lancedb_only:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "--skip-embedding 不能与 --sync-lancedb-only 同时使用",
                },
                ensure_ascii=False,
            )
        )
        return 2
    if args.limit > MAX_NORMAL_INGEST_LIMIT and not (
        args.sync_lancedb_only or args.reanalyze_existing
    ):
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": (
                        "普通入库模式的 --limit 不能超过 "
                        f"{MAX_NORMAL_INGEST_LIMIT}"
                    ),
                },
                ensure_ascii=False,
            )
        )
        return 2
    try:
        summary = ingest(args)
        print(json.dumps({"ok": True, **summary}, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
