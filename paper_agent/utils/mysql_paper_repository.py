"""封装 papers 数据库三张论文表的事务读写。"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Sequence

from config import DATABASE_INFO
from utils.arxiv_source import IngestError, Paper, parse_arxiv_datetime


def _json_value(value: Any) -> Any:
    """把数据库 JSON 字符串或字节还原为 Python 值。"""
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
    """把带时区时间转换为 MySQL 使用的无时区 UTC 时间。"""
    return value.astimezone(timezone.utc).replace(tzinfo=None)


class MySQLPaperRepository:
    """只连接 papers 数据库并管理三张既有论文表。"""

    DATABASE_NAME = "papers"

    def __init__(self) -> None:
        """从环境变量或项目配置读取 MySQL 连接参数。"""
        self.host = os.environ.get("DB_HOST") or DATABASE_INFO["HOST"]
        self.port = int(os.environ.get("DB_PORT") or DATABASE_INFO["PORT"])
        self.user = os.environ.get("DB_USER") or DATABASE_INFO["USER"]
        self.password = os.environ.get("DB_PASSWORD") or DATABASE_INFO["PASSWORD"]

    def connect(self) -> Any:
        """建立固定指向 papers 数据库的事务连接。"""
        import pymysql

        return pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.DATABASE_NAME,
            charset="utf8mb4",
            connect_timeout=10,
            read_timeout=30,
            write_timeout=30,
            autocommit=False,
            cursorclass=pymysql.cursors.DictCursor,
        )

    @staticmethod
    def _upsert_analysis(
        cursor: Any,
        paper: Paper,
        model_name: str,
        now: datetime,
        update_info: bool,
    ) -> None:
        """写入单篇分析，并按需同步主表中的全文派生字段。"""
        if paper.analysis is None:
            raise IngestError(f"论文 {paper.arxiv_id} 缺少分析结果")
        if update_info:
            cursor.execute(
                """
                UPDATE papers_info
                SET keywords=%s, venue=%s, is_code_open_source=%s,
                    is_code_open=%s, code_url=%s, updated_at=%s
                WHERE paper_id=%s
                """,
                (
                    json.dumps(paper.analysis["keywords"], ensure_ascii=False),
                    paper.venue,
                    paper.is_code_open_source,
                    paper.is_code_open,
                    paper.code_url,
                    now,
                    paper.paper_id,
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
                json.dumps(paper.analysis["main_contributions"], ensure_ascii=False),
                json.dumps(paper.analysis["main_results"], ensure_ascii=False),
                json.dumps(paper.analysis["limitations"], ensure_ascii=False),
                model_name,
                now,
            ),
        )

    def upsert_batch(self, papers: Sequence[Paper], model_name: str) -> None:
        """在同一事务中写入论文元数据、来源和英文分析。"""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                for paper in papers:
                    if paper.analysis is None:
                        raise IngestError(f"论文 {paper.arxiv_id} 缺少分析结果")
                    cursor.execute(
                        """
                        INSERT INTO papers_info
                          (paper_id, title, doi, venue, authors, abstract, keywords,
                           published_at, categories, initial_citation_count,
                           current_citation_count, is_code_open_source, is_code_open,
                           code_url, created_at, updated_at)
                        VALUES
                          (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                           NULL, NULL, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                          title=VALUES(title), doi=VALUES(doi), venue=VALUES(venue),
                          authors=VALUES(authors), abstract=VALUES(abstract),
                          keywords=VALUES(keywords), published_at=VALUES(published_at),
                          categories=VALUES(categories),
                          is_code_open_source=VALUES(is_code_open_source),
                          is_code_open=VALUES(is_code_open),
                          code_url=VALUES(code_url), updated_at=VALUES(updated_at)
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
                            paper.is_code_open_source,
                            paper.is_code_open,
                            paper.code_url,
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
                    self._upsert_analysis(
                        cursor, paper, model_name, now, update_info=False
                    )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def upsert_analysis_batch(
        self, papers: Sequence[Paper], model_name: str
    ) -> None:
        """在单事务中更新分析及主表派生字段，不改来源或向量。"""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                for paper in papers:
                    self._upsert_analysis(
                        cursor, paper, model_name, now, update_info=True
                    )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def load_recent(self, limit: int) -> List[Paper]:
        """读取最近且三张关联表均完整的论文。"""
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT pi.*, ps.source_id, ps.paper_url, ps.pdf_url, ps.raw_metadata,
                           pa.research_topics, pa.core_method, pa.datasets,
                           pa.main_contributions, pa.main_results, pa.limitations
                    FROM papers_info pi
                    JOIN papers_source ps
                      ON ps.paper_id = pi.paper_id AND ps.source='arxiv'
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
            updated_text = (
                raw_metadata.get("updated") if isinstance(raw_metadata, dict) else None
            )
            updated = parse_arxiv_datetime(updated_text) if updated_text else published
            papers.append(
                Paper(
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
                    venue=row["venue"] or None,
                    raw_metadata=(
                        raw_metadata if isinstance(raw_metadata, dict) else {}
                    ),
                    is_code_open_source=row["is_code_open_source"] or "unknown",
                    is_code_open=(
                        int(row["is_code_open"])
                        if row["is_code_open"] is not None
                        else None
                    ),
                    code_url=row["code_url"] or None,
                    analysis={
                        "keywords": list(_json_value(row["keywords"]) or []),
                        "research_topics": list(
                            _json_value(row["research_topics"]) or []
                        ),
                        "core_method": row["core_method"] or "",
                        "datasets": list(_json_value(row["datasets"]) or []),
                        "main_contributions": list(
                            _json_value(row["main_contributions"]) or []
                        ),
                        "main_results": list(
                            _json_value(row["main_results"]) or []
                        ),
                        "limitations": list(_json_value(row["limitations"]) or []),
                    },
                )
            )
        return papers

    def complete_ids(self, paper_ids: Iterable[int]) -> List[int]:
        """返回在 papers 三张目标表中都存在的指定论文 ID。"""
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
