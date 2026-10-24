import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.arxiv_source import Paper  # noqa: E402
from utils.mysql_paper_repository import MySQLPaperRepository  # noqa: E402


class _FakeCursor:
    """记录测试期间执行的 SQL。"""

    def __init__(self) -> None:
        """初始化 SQL 记录列表。"""
        self.statements = []

    def __enter__(self):
        """返回当前游标。"""
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """退出上下文时不吞掉异常。"""
        return None

    def execute(self, sql, parameters) -> None:
        """保存 SQL 和参数供断言使用。"""
        self.statements.append((" ".join(sql.split()), parameters))


class _FakeConnection:
    """模拟支持事务提交和回滚的 MySQL 连接。"""

    def __init__(self) -> None:
        """初始化游标和事务状态。"""
        self.fake_cursor = _FakeCursor()
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        """返回测试游标。"""
        return self.fake_cursor

    def commit(self) -> None:
        """记录事务提交。"""
        self.committed = True

    def rollback(self) -> None:
        """记录事务回滚。"""
        self.rolled_back = True

    def close(self) -> None:
        """记录连接关闭。"""
        self.closed = True


def _paper() -> Paper:
    """构造包含英文分析的测试论文。"""
    now = datetime.now(timezone.utc)
    return Paper(
        paper_id=7,
        arxiv_id="2609.00007",
        title="English Paper",
        authors=["Alice"],
        abstract="This paper evaluates an artificial intelligence system.",
        categories=["cs.AI"],
        published_at=now,
        updated_at=now,
        paper_url="https://arxiv.org/abs/2609.00007",
        pdf_url="https://arxiv.org/pdf/2609.00007",
        doi=None,
        venue="Example Conference 2026",
        raw_metadata={},
        is_code_open_source="yes",
        is_code_open=1,
        code_url="https://github.com/example/paper-code",
        analysis={
            "keywords": ["one", "two", "three", "four", "five"],
            "research_topics": ["AI evaluation", "Benchmarking", "Reliability"],
            "core_method": "A controlled benchmark",
            "datasets": [],
            "main_contributions": ["Introduces the benchmark"],
            "main_results": [],
            "limitations": [],
        },
    )


class MySQLPaperRepositoryTest(unittest.TestCase):
    """验证论文派生字段只写入 papers 库中的目标表。"""

    def test_load_by_ids_uses_parameters_and_preserves_retrieval_order(self):
        repository = MySQLPaperRepository()
        connection = _FakeConnection()
        repository.connect = lambda: connection
        template = dict(paper_id=1, source_id="2610.00001", title="Title", authors='["Alice"]',
                        abstract="Abstract", categories='["cs.AI"]', published_at=datetime(2026, 10, 24),
                        raw_metadata="{}", paper_url="https://arxiv.org/abs/2610.00001", pdf_url="https://arxiv.org/pdf/2610.00001",
                        doi=None, venue=None, is_code_open_source="unknown", is_code_open=None, code_url=None,
                        keywords='["retrieval"]', research_topics='["AI"]', core_method="Retrieve evidence",
                        datasets="[]", main_contributions='["A method"]', main_results="[]", limitations="[]")
        connection.fake_cursor.fetchall = lambda: [template, dict(template, paper_id=3)]
        papers = repository.load_by_ids([3, 2, 1, 3])
        self.assertEqual([3, 1], [paper.paper_id for paper in papers])
        self.assertEqual(["A method"], papers[0].analysis["main_contributions"])
        sql, parameters = connection.fake_cursor.statements[0]
        self.assertIn("IN (%s,%s,%s)", sql)
        self.assertEqual([3, 2, 1], parameters)
        self.assertTrue(connection.closed)
        self.assertFalse(connection.committed)

    def test_empty_load_by_ids_does_not_connect(self):
        repository = MySQLPaperRepository()
        repository.connect = lambda: self.fail("空ID列表不应连接数据库")
        self.assertEqual([], repository.load_by_ids([]))

    def test_analysis_only_update_does_not_touch_source(self):
        """验证重分析更新主表派生字段且不修改来源表。"""
        repository = MySQLPaperRepository()
        connection = _FakeConnection()
        repository.connect = lambda: connection

        repository.upsert_analysis_batch([_paper()], "deepseek-chat")

        sql_text = " ".join(sql for sql, _ in connection.fake_cursor.statements)
        self.assertIn("UPDATE papers_info", sql_text)
        self.assertIn("venue=%s", sql_text)
        self.assertIn("is_code_open_source=%s", sql_text)
        self.assertIn("is_code_open=%s", sql_text)
        self.assertIn("code_url=%s", sql_text)
        self.assertIn("INSERT INTO papers_analysis", sql_text)
        self.assertNotIn("papers_source", sql_text)
        update_parameters = connection.fake_cursor.statements[0][1]
        self.assertEqual("Example Conference 2026", update_parameters[1])
        self.assertEqual("yes", update_parameters[2])
        self.assertEqual(1, update_parameters[3])
        self.assertEqual(
            "https://github.com/example/paper-code", update_parameters[4]
        )
        self.assertTrue(connection.committed)
        self.assertFalse(connection.rolled_back)
        self.assertTrue(connection.closed)

    def test_new_ingest_writes_code_fields_but_leaves_citations_null(self):
        """验证新入库写入开源字段且引用量继续保持空值。"""
        repository = MySQLPaperRepository()
        connection = _FakeConnection()
        repository.connect = lambda: connection

        repository.upsert_batch([_paper()], "deepseek-chat")

        info_sql, parameters = connection.fake_cursor.statements[0]
        self.assertIn("initial_citation_count", info_sql)
        self.assertIn("current_citation_count", info_sql)
        self.assertIn("NULL, NULL", info_sql)
        self.assertIn("is_code_open_source=VALUES(is_code_open_source)", info_sql)
        self.assertIn("yes", parameters)
        self.assertIn("https://github.com/example/paper-code", parameters)

    def test_analysis_update_rolls_back_on_error(self):
        """验证任意 SQL 失败时整批派生字段更新会回滚。"""
        repository = MySQLPaperRepository()
        connection = _FakeConnection()

        def fail_execute(sql, parameters) -> None:
            """模拟数据库执行失败。"""
            raise RuntimeError("database failure")

        connection.fake_cursor.execute = fail_execute
        repository.connect = lambda: connection

        with self.assertRaisesRegex(RuntimeError, "database failure"):
            repository.upsert_analysis_batch([_paper()], "deepseek-chat")

        self.assertTrue(connection.rolled_back)
        self.assertFalse(connection.committed)
        self.assertTrue(connection.closed)


if __name__ == "__main__":
    unittest.main()
