"""提供 arXiv 论文模型、Atom 解析和最新论文抓取。"""

from __future__ import annotations

import hashlib
import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx


ATOM_NS = "http://www.w3.org/2005/Atom"
ARXIV_NS = "http://arxiv.org/schemas/atom"


class IngestError(RuntimeError):
    """论文入库链路无法满足完整性要求时抛出。"""


@dataclass
class Paper:
    """保存论文元数据、分析结果和向量。"""

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
    venue: Optional[str]
    raw_metadata: Dict[str, Any]
    full_text: str = ""
    is_code_open_source: str = "unknown"
    is_code_open: Optional[int] = None
    code_url: Optional[str] = None
    analysis: Optional[Dict[str, Any]] = None
    embedding_text: str = ""
    vector: Optional[List[float]] = None


def normalize_text(value: Optional[str]) -> str:
    """合并文本中的多余空白并返回单行内容。"""
    return " ".join((value or "").split())


def canonical_arxiv_id(value: str) -> str:
    """从 URL 或带版本号编号中提取无版本号 arXiv ID。"""
    identifier = value.rstrip("/").rsplit("/", 1)[-1]
    return re.sub(r"v\d+$", "", identifier, flags=re.IGNORECASE)


def stable_paper_id(arxiv_id: str) -> int:
    """为新旧格式 arXiv ID 生成稳定的正整数主键。"""
    canonical = canonical_arxiv_id(arxiv_id)
    if re.fullmatch(r"\d{4}\.\d{4,5}", canonical):
        return int(canonical.replace(".", ""))
    value = int.from_bytes(
        hashlib.sha256(f"arxiv:{canonical}".encode("utf-8")).digest()[:4], "big"
    ) & 0x7FFFFFFF
    return value or 1


def parse_arxiv_datetime(value: Optional[str]) -> datetime:
    """把 arXiv 时间字符串转换为 UTC datetime。"""
    if not value:
        raise IngestError("arXiv 条目缺少时间")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_arxiv_feed(xml_content: bytes) -> List[Paper]:
    """把 arXiv Atom XML 解析为论文对象列表。"""
    root = ET.fromstring(xml_content)
    namespace = {"atom": ATOM_NS, "arxiv": ARXIV_NS}
    papers: List[Paper] = []
    for entry in root.findall("atom:entry", namespace):
        entry_id = normalize_text(entry.findtext("atom:id", namespaces=namespace))
        arxiv_id = canonical_arxiv_id(entry_id)
        title = normalize_text(entry.findtext("atom:title", namespaces=namespace))
        abstract = normalize_text(entry.findtext("atom:summary", namespaces=namespace))
        if not arxiv_id or not title or not abstract:
            continue

        authors = [
            normalize_text(author.findtext("atom:name", namespaces=namespace))
            for author in entry.findall("atom:author", namespace)
        ]
        categories = [
            category.attrib.get("term", "").strip()
            for category in entry.findall("atom:category", namespace)
        ]
        authors = [value for value in authors if value]
        categories = [value for value in categories if value]
        published_at = parse_arxiv_datetime(
            entry.findtext("atom:published", namespaces=namespace)
        )
        updated_at = parse_arxiv_datetime(
            entry.findtext("atom:updated", namespaces=namespace)
        )

        paper_url = f"https://arxiv.org/abs/{arxiv_id}"
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
        for link in entry.findall("atom:link", namespace):
            href = link.attrib.get("href", "")
            if link.attrib.get("rel") == "alternate" and href:
                paper_url = href.replace("http://", "https://")
            if link.attrib.get("title") == "pdf" and href:
                pdf_url = href.replace("http://", "https://")

        doi = normalize_text(entry.findtext("arxiv:doi", namespaces=namespace)) or None
        journal_ref = normalize_text(
            entry.findtext("arxiv:journal_ref", namespaces=namespace)
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
                venue=journal_ref or None,
                raw_metadata=raw_metadata,
            )
        )
    return papers


def fetch_arxiv_papers(
    category: str, max_results: int, timeout: int = 30
) -> List[Paper]:
    """按提交时间抓取指定分类的最新论文，临时失败最多重试三次。"""
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
    last_error: Optional[BaseException] = None
    for attempt in range(3):
        try:
            response = httpx.get(
                url, headers=headers, timeout=timeout, follow_redirects=True
            )
            response.raise_for_status()
            return parse_arxiv_feed(response.content)
        except (httpx.HTTPError, ET.ParseError, ValueError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(float(2 ** attempt))
    raise IngestError(f"arXiv 请求重试 3 次后仍失败：{last_error}")
