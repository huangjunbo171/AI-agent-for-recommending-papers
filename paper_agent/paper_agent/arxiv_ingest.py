"""Ingest recent arXiv papers into MySQL and the local LanceDB store."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence
from urllib.parse import urlencode


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = PROJECT_ROOT / "paper_agent"
sys.path.insert(0, str(PACKAGE_ROOT))

from config import DATABASE_INFO, DEEPSEEK_INFO  # noqa: E402
from utils.lancedb_store import LanceDBPaperStore  # noqa: E402
from utils.prompt import analyze_paper_metadata_prompt  # noqa: E402


ATOM_NS = "http://www.w3.org/2005/Atom"
ARXIV_NS = "http://arxiv.org/schemas/atom"
ARRAY_FIELDS = (
    "keywords",
    "research_topics",
    "datasets",
    "main_contributions",
    "main_results",
    "limitations",
)


class IngestError(RuntimeError):
    """Raised when the ingest cannot meet its all-or-nothing contract."""


class AuthenticationError(IngestError):
    """Raised when an external service rejects configured credentials."""


@dataclass
class Paper:
    paper_id: int
    arxiv_id: str
    title: str
    authors: List[str]
    abstract: str
    categories: List[str]
    published_at: datetime
    updated_at: datetime
    paper_url: str
    pdf_url: str
    doi: Optional[str]
    venue: str
    raw_metadata: Dict[str, Any]
    analysis: Optional[Dict[str, Any]] = None
    embedding_text: str = ""
    vector: Optional[List[float]] = None


def load_dotenv(path: Path) -> None:
    """Load a small KEY=VALUE file without overriding the current process."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def normalize_text(value: Optional[str]) -> str:
    return " ".join((value or "").split())


def canonical_arxiv_id(value: str) -> str:
    identifier = value.rstrip("/").rsplit("/", 1)[-1]
    return re.sub(r"v\d+$", "", identifier, flags=re.IGNORECASE)


def stable_paper_id(arxiv_id: str) -> int:
    """Create a stable signed-INT-safe id for both modern and legacy ids."""
    canonical = canonical_arxiv_id(arxiv_id)
    if re.fullmatch(r"\d{4}\.\d{4,5}", canonical):
        return int(canonical.replace(".", ""))
    value = int.from_bytes(
        hashlib.sha256(f"arxiv:{canonical}".encode("utf-8")).digest()[:4], "big"
    ) & 0x7FFFFFFF
    return value or 1


def parse_arxiv_feed(xml_content: bytes) -> List[Paper]:
    root = ET.fromstring(xml_content)
    papers: List[Paper] = []
    ns = {"atom": ATOM_NS, "arxiv": ARXIV_NS}
    for entry in root.findall("atom:entry", ns):
        entry_id = normalize_text(entry.findtext("atom:id", namespaces=ns))
        arxiv_id = canonical_arxiv_id(entry_id)
        title = normalize_text(entry.findtext("atom:title", namespaces=ns))
        abstract = normalize_text(entry.findtext("atom:summary", namespaces=ns))
        if not arxiv_id or not title or not abstract:
            continue

        authors = [
            normalize_text(author.findtext("atom:name", namespaces=ns))
            for author in entry.findall("atom:author", ns)
        ]
        authors = [author for author in authors if author]
        categories = [
            category.attrib.get("term", "").strip()
            for category in entry.findall("atom:category", ns)
        ]
        categories = [category for category in categories if category]
        published_at = parse_arxiv_datetime(
            entry.findtext("atom:published", namespaces=ns)
        )
        updated_at = parse_arxiv_datetime(entry.findtext("atom:updated", namespaces=ns))

        paper_url = f"https://arxiv.org/abs/{arxiv_id}"
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
        for link in entry.findall("atom:link", ns):
            href = link.attrib.get("href", "")
            if link.attrib.get("rel") == "alternate" and href:
                paper_url = href.replace("http://", "https://")
            if link.attrib.get("title") == "pdf" and href:
                pdf_url = href.replace("http://", "https://")

        doi = normalize_text(entry.findtext("arxiv:doi", namespaces=ns)) or None
        journal_ref = normalize_text(
            entry.findtext("arxiv:journal_ref", namespaces=ns)
        )
        raw_metadata = {
            "arxiv_id": arxiv_id,
            "title": title,
            "authors": authors,
            "abstract": abstract,
            "categories": categories,
            "published": published_at.isoformat(),
            "updated": updated_at.isoformat(),
            "doi": doi,
            "journal_ref": journal_ref or None,
            "paper_url": paper_url,
            "pdf_url": pdf_url,
        }
        papers.append(
            Paper(
                paper_id=stable_paper_id(arxiv_id),
                arxiv_id=arxiv_id,
                title=title,
                authors=authors,
                abstract=abstract,
                categories=categories,
                published_at=published_at,
                updated_at=updated_at,
                paper_url=paper_url,
                pdf_url=pdf_url,
                doi=doi,
                venue=journal_ref or "arXiv",
                raw_metadata=raw_metadata,
            )
        )
    return papers


def parse_arxiv_datetime(value: Optional[str]) -> datetime:
    if not value:
        raise IngestError("arXiv entry is missing a timestamp")
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fetch_arxiv_papers(
    category: str, max_results: int, timeout: int = 30
) -> List[Paper]:
    import requests

    params = {
        "search_query": f"cat:{category}",
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    url = "https://export.arxiv.org/api/query?" + urlencode(params)
    headers = {
        "User-Agent": os.environ.get(
            "ARXIV_USER_AGENT", "paper-recommender/0.1 (arXiv metadata ingest)"
        )
    }
    last_error: Optional[Exception] = None
    for attempt in range(3):
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            return parse_arxiv_feed(response.content)
        except Exception as exc:  # requests and XML errors share retry handling
            last_error = exc
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
    raise IngestError(f"arXiv request failed after 3 attempts: {last_error}")


def parse_analysis_json(content: str) -> Dict[str, Any]:
    cleaned = (content or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("LLM response does not contain a JSON object")
    value = json.loads(cleaned[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("LLM response must be a JSON object")

    allowed = set(ARRAY_FIELDS) | {"core_method"}
    if not allowed.issubset(value):
        missing = sorted(allowed - set(value))
        raise ValueError(f"LLM response is missing fields: {missing}")

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
    core_method = value["core_method"]
    if not isinstance(core_method, str):
        raise ValueError("core_method must be a string")
    result["core_method"] = normalize_text(core_method)
    return result


class DeepSeekAnalyzer:
    def __init__(self, provider: str = "deepseek") -> None:
        if provider.lower() != "deepseek":
            raise IngestError("The first ingest version supports provider=deepseek only")
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
        if not self.api_key:
            raise IngestError("DEEPSEEK_API_KEY is empty")

    def analyze(self, paper: Paper) -> Dict[str, Any]:
        import requests

        user_content = json.dumps(
            {
                "title": paper.title,
                "authors": paper.authors,
                "categories": paper.categories,
                "abstract": paper.abstract,
            },
            ensure_ascii=False,
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": analyze_paper_metadata_prompt()},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.1,
            "max_tokens": 1800,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        last_error: Optional[Exception] = None
        for attempt in range(3):
            try:
                response = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=90,
                )
                if response.status_code in (401, 403):
                    raise AuthenticationError(
                        "DeepSeek authentication failed; set a valid DEEPSEEK_API_KEY"
                    )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                return parse_analysis_json(content)
            except Exception as exc:
                last_error = exc
                if isinstance(exc, AuthenticationError):
                    raise
                if attempt < 2:
                    time.sleep(3 * (attempt + 1))
        raise IngestError(
            f"DeepSeek analysis failed for {paper.arxiv_id} after 3 attempts: {last_error}"
        )


def build_embedding_text(paper: Paper) -> str:
    if paper.analysis is None:
        raise IngestError(f"paper {paper.arxiv_id} has no LLM analysis")
    analysis = paper.analysis
    parts = [
        f"Title: {paper.title}",
        f"Abstract: {paper.abstract}",
        "Keywords: " + ", ".join(analysis["keywords"]),
        "Research topics: " + ", ".join(analysis["research_topics"]),
        f"Core method: {analysis['core_method']}",
        "Main contributions: " + "; ".join(analysis["main_contributions"]),
    ]
    return "\n".join(part for part in parts if part.split(":", 1)[-1].strip())


class BGEEmbedder:
    def __init__(self, model_name: str) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise IngestError(
                "sentence-transformers is required for BGE-M3 embeddings"
            ) from exc

        configured_path = os.environ.get("EMBEDDING_MODEL_PATH", "").strip()
        cache_dir = PROJECT_ROOT / "papers" / "lancedb" / "models"
        cache_dir.mkdir(parents=True, exist_ok=True)
        default_local_path = cache_dir / "bge-m3"
        if configured_path:
            model_ref = configured_path
            kwargs = {}
        elif (default_local_path / "config.json").exists() and (
            default_local_path / "pytorch_model.bin"
        ).exists():
            model_ref = str(default_local_path)
            kwargs = {}
        else:
            model_ref = model_name
            kwargs = {"cache_folder": str(cache_dir)}
        self.model = SentenceTransformer(model_ref, **kwargs)
        self.model_name = model_name if not configured_path else Path(configured_path).name

    def encode(self, texts: Sequence[str]) -> List[List[float]]:
        embeddings = self.model.encode(
            list(texts), normalize_embeddings=True, convert_to_numpy=True
        )
        if len(embeddings.shape) != 2 or embeddings.shape[1] != 1024:
            raise IngestError(
                f"embedding dimension must be 1024, got {tuple(embeddings.shape)}"
            )
        return [row.astype("float32").tolist() for row in embeddings]


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (list, dict)):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _mysql_datetime(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None)


class MySQLPaperRepository:
    def __init__(self) -> None:
        self.host = os.environ.get("DB_HOST") or DATABASE_INFO["HOST"]
        self.port = int(os.environ.get("DB_PORT") or DATABASE_INFO["PORT"])
        self.user = os.environ.get("DB_USER") or DATABASE_INFO["USER"]
        self.password = os.environ.get("DB_PASSWORD") or DATABASE_INFO["PASSWORD"]

    def connect(self):
        import pymysql

        return pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database="papers",
            charset="utf8mb4",
            connect_timeout=10,
            read_timeout=30,
            write_timeout=30,
            autocommit=False,
            cursorclass=pymysql.cursors.DictCursor,
        )

    def upsert_batch(self, papers: Sequence[Paper], model_name: str) -> None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                for paper in papers:
                    if paper.analysis is None:
                        raise IngestError(f"paper {paper.arxiv_id} has no analysis")
                    cursor.execute(
                        """
                        INSERT INTO papers_info
                          (paper_id, title, doi, venue, authors, abstract, keywords,
                           published_at, categories, initial_citation_count,
                           current_citation_count, is_code_open_source, is_code_open,
                           code_url, created_at, updated_at)
                        VALUES
                          (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                           NULL, NULL, NULL, NULL, NULL, %s, %s)
                        ON DUPLICATE KEY UPDATE
                          title=VALUES(title), doi=VALUES(doi), venue=VALUES(venue),
                          authors=VALUES(authors), abstract=VALUES(abstract),
                          keywords=VALUES(keywords), published_at=VALUES(published_at),
                          categories=VALUES(categories), updated_at=VALUES(updated_at)
                        """,
                        (
                            paper.paper_id,
                            paper.title,
                            paper.doi,
                            paper.venue,
                            json.dumps(paper.authors, ensure_ascii=False),
                            paper.abstract,
                            json.dumps(paper.analysis["keywords"], ensure_ascii=False),
                            _mysql_datetime(paper.published_at),
                            json.dumps(paper.categories, ensure_ascii=False),
                            now,
                            now,
                        ),
                    )
                    cursor.execute(
                        """
                        INSERT INTO papers_source
                          (paper_source_id, paper_id, source, source_id, paper_url,
                           pdf_url, fetched_at, updated_at, raw_metadata)
                        VALUES (%s, %s, 'arxiv', %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                          paper_id=VALUES(paper_id), source=VALUES(source),
                          source_id=VALUES(source_id), paper_url=VALUES(paper_url),
                          pdf_url=VALUES(pdf_url), fetched_at=VALUES(fetched_at),
                          updated_at=VALUES(updated_at), raw_metadata=VALUES(raw_metadata)
                        """,
                        (
                            paper.paper_id,
                            paper.paper_id,
                            paper.arxiv_id,
                            paper.paper_url,
                            paper.pdf_url,
                            datetime.now(timezone.utc).isoformat(),
                            now,
                            json.dumps(paper.raw_metadata, ensure_ascii=False),
                        ),
                    )
                    cursor.execute(
                        """
                        INSERT INTO papers_analysis
                          (analysis_id, paper_id, research_topics, core_method,
                           datasets, main_contributions, main_results, limitations,
                           model_name, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                          paper_id=VALUES(paper_id), research_topics=VALUES(research_topics),
                          core_method=VALUES(core_method), datasets=VALUES(datasets),
                          main_contributions=VALUES(main_contributions),
                          main_results=VALUES(main_results), limitations=VALUES(limitations),
                          model_name=VALUES(model_name), created_at=VALUES(created_at)
                        """,
                        (
                            paper.paper_id,
                            paper.paper_id,
                            json.dumps(paper.analysis["research_topics"], ensure_ascii=False),
                            paper.analysis["core_method"],
                            json.dumps(paper.analysis["datasets"], ensure_ascii=False),
                            json.dumps(
                                paper.analysis["main_contributions"], ensure_ascii=False
                            ),
                            json.dumps(paper.analysis["main_results"], ensure_ascii=False),
                            json.dumps(paper.analysis["limitations"], ensure_ascii=False),
                            model_name,
                            now,
                        ),
                    )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def load_recent(self, limit: int) -> List[Paper]:
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT pi.*, ps.source_id, ps.paper_url, ps.pdf_url, ps.raw_metadata,
                           pa.research_topics, pa.core_method, pa.datasets,
                           pa.main_contributions, pa.main_results, pa.limitations
                    FROM papers_info pi
                    JOIN papers_source ps ON ps.paper_id = pi.paper_id AND ps.source='arxiv'
                    JOIN papers_analysis pa ON pa.paper_id = pi.paper_id
                    ORDER BY pi.published_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cursor.fetchall()
        finally:
            connection.close()

        papers: List[Paper] = []
        for row in rows:
            published = row["published_at"].replace(tzinfo=timezone.utc)
            raw_metadata = _json_value(row["raw_metadata"]) or {}
            updated_text = raw_metadata.get("updated") if isinstance(raw_metadata, dict) else None
            updated = parse_arxiv_datetime(updated_text) if updated_text else published
            paper = Paper(
                paper_id=int(row["paper_id"]),
                arxiv_id=str(row["source_id"]),
                title=row["title"],
                authors=list(_json_value(row["authors"]) or []),
                abstract=row["abstract"] or "",
                categories=list(_json_value(row["categories"]) or []),
                published_at=published,
                updated_at=updated,
                paper_url=row["paper_url"],
                pdf_url=row["pdf_url"],
                doi=row["doi"],
                venue=row["venue"] or "arXiv",
                raw_metadata=raw_metadata if isinstance(raw_metadata, dict) else {},
                analysis={
                    "keywords": list(_json_value(row["keywords"]) or []),
                    "research_topics": list(_json_value(row["research_topics"]) or []),
                    "core_method": row["core_method"] or "",
                    "datasets": list(_json_value(row["datasets"]) or []),
                    "main_contributions": list(
                        _json_value(row["main_contributions"]) or []
                    ),
                    "main_results": list(_json_value(row["main_results"]) or []),
                    "limitations": list(_json_value(row["limitations"]) or []),
                },
            )
            papers.append(paper)
        return papers

    def complete_ids(self, paper_ids: Iterable[int]) -> List[int]:
        ids = sorted({int(value) for value in paper_ids})
        if not ids:
            return []
        placeholders = ",".join(["%s"] * len(ids))
        sql = f"""
            SELECT DISTINCT pi.paper_id
            FROM papers_info pi
            JOIN papers_source ps ON ps.paper_id=pi.paper_id AND ps.source='arxiv'
            JOIN papers_analysis pa ON pa.paper_id=pi.paper_id
            WHERE pi.paper_id IN ({placeholders})
        """
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, ids)
                return sorted(int(row["paper_id"]) for row in cursor.fetchall())
        finally:
            connection.close()


def build_lancedb_records(
    papers: Sequence[Paper], embedding_model: str
) -> List[Dict[str, Any]]:
    records = []
    for paper in papers:
        if paper.analysis is None or paper.vector is None:
            raise IngestError(f"paper {paper.arxiv_id} is not ready for LanceDB")
        records.append(
            {
                "paper_id": paper.paper_id,
                "title": paper.title,
                "authors": json.dumps(paper.authors, ensure_ascii=False),
                "url": paper.paper_url,
                "abstract": paper.abstract,
                "field": json.dumps(paper.categories, ensure_ascii=False),
                "gene_keywords": json.dumps(
                    paper.analysis["keywords"], ensure_ascii=False
                ),
                "image_path": "",
                "section_text": paper.abstract,
                "embedding_text": paper.embedding_text,
                "embedding_model": embedding_model,
                "vector": paper.vector,
            }
        )
    return records


def prepare_embeddings(
    papers: Sequence[Paper], embedding_model: str
) -> BGEEmbedder:
    for paper in papers:
        paper.embedding_text = build_embedding_text(paper)
    embedder = BGEEmbedder(embedding_model)
    vectors = embedder.encode([paper.embedding_text for paper in papers])
    for paper, vector in zip(papers, vectors):
        paper.vector = vector
    return embedder


def ingest(args: argparse.Namespace) -> Dict[str, Any]:
    repository = MySQLPaperRepository()
    summary: Dict[str, Any] = {
        "requested": args.limit,
        "fetched": 0,
        "analyzed": 0,
        "mysql_written": 0,
        "lancedb_written": 0,
        "skipped": 0,
        "failures": [],
    }

    if args.sync_lancedb_only:
        prepared = repository.load_recent(args.limit)
        summary["fetched"] = len(prepared)
        summary["analyzed"] = len(prepared)
        if len(prepared) < args.limit:
            raise IngestError(
                f"MySQL contains only {len(prepared)} complete papers; expected {args.limit}"
            )
    else:
        candidates = fetch_arxiv_papers(
            args.category, max_results=max(30, args.limit * 3)
        )
        summary["fetched"] = len(candidates)
        analyzer = DeepSeekAnalyzer(args.provider)
        llm_model_name = analyzer.model
        prepared = []
        used_ids = set()
        for paper in candidates:
            if paper.paper_id in used_ids:
                summary["skipped"] += 1
                continue
            try:
                paper.analysis = analyzer.analyze(paper)
                prepared.append(paper)
                used_ids.add(paper.paper_id)
                summary["analyzed"] = len(prepared)
                print(
                    f"Analyzed {len(prepared)}/{args.limit}: "
                    f"{paper.arxiv_id} {paper.title}",
                    flush=True,
                )
            except Exception as exc:
                summary["skipped"] += 1
                summary["failures"].append(f"{paper.arxiv_id}: {exc}")
            if len(prepared) == args.limit:
                break
        if len(prepared) < args.limit:
            details = "; ".join(summary["failures"][:3])
            raise IngestError(
                f"Only {len(prepared)} papers passed analysis; expected {args.limit}. "
                f"First failures: {details}"
            )

    embedder = prepare_embeddings(prepared, args.embedding_model)
    if args.dry_run:
        summary["dry_run"] = True
        summary["paper_ids"] = [paper.paper_id for paper in prepared]
        summary["embedding_model"] = embedder.model_name
        return summary

    if not args.sync_lancedb_only:
        repository.upsert_batch(prepared, llm_model_name)
        summary["mysql_written"] = len(prepared)

    store = LanceDBPaperStore()
    store.ensure_schema()
    records = build_lancedb_records(prepared, embedder.model_name)
    summary["lancedb_written"] = store.upsert_sections(records)

    expected_ids = sorted(paper.paper_id for paper in prepared)
    mysql_ids = repository.complete_ids(expected_ids)
    lancedb_ids = sorted(set(store.paper_ids()) & set(expected_ids))
    if mysql_ids != expected_ids or lancedb_ids != expected_ids:
        raise IngestError(
            "cross-store verification failed: "
            f"expected={expected_ids}, mysql={mysql_ids}, lancedb={lancedb_ids}"
        )
    summary["paper_ids"] = expected_ids
    summary["embedding_model"] = embedder.model_name
    summary["verified"] = True
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--category", default="cs.AI")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--provider", default="deepseek", choices=["deepseek"])
    parser.add_argument("--embedding-model", default="BAAI/bge-m3")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sync-lancedb-only", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    args = build_parser().parse_args(argv)
    if args.limit < 1:
        print(json.dumps({"ok": False, "error": "--limit must be positive"}))
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
