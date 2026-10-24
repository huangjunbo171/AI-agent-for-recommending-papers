import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.lancedb_store import (
    LanceDBPaperStore,
    LanceDBPathError,
    LanceDBSchemaError,
)


class _FakeTable:
    """提供测试所需的最小 LanceDB 表替身。"""

    def __init__(self, schema):
        """保存测试传入的表结构。"""
        self.schema = schema


class _FakeDatabase:
    """提供仅在内存中保存表对象的数据库替身。"""

    def __init__(self):
        """初始化空的测试表集合。"""
        self.tables = {}

    def table_names(self):
        """返回当前测试数据库中的全部表名。"""
        return list(self.tables)

    def create_table(self, name, schema):
        """创建并保存一个测试表对象。"""
        table = _FakeTable(schema)
        self.tables[name] = table
        return table

    def open_table(self, name):
        """按名称打开已创建的测试表。"""
        return self.tables[name]


class LanceDBPaperStoreTest(unittest.TestCase):
    """验证 LanceDB 路径、Schema 和幂等写入行为。"""

    @staticmethod
    def _temporary_papers_root():
        """在项目 papers 目录中创建测试用临时根目录。"""
        return tempfile.TemporaryDirectory(
            dir=Path(__file__).resolve().parents[2] / "papers"
        )

    def test_rejects_database_path_escape(self):
        """验证子库名称不能通过相对路径逃逸根目录。"""
        with self._temporary_papers_root() as root:
            for invalid_name in ("..", "../outside", "folder/child"):
                with self.subTest(invalid_name=invalid_name):
                    with self.assertRaises(LanceDBPathError):
                        LanceDBPaperStore(root_path=root, database_name=invalid_name)

    def test_creates_empty_table_without_overwriting_existing_table(self):
        """验证重复建表会打开原表而不会覆盖已有表。"""
        with self._temporary_papers_root() as root:
            store = LanceDBPaperStore(root_path=root)
            database = _FakeDatabase()
            store._database = database
            fake_schema = object()

            with patch.object(store, "schema", return_value=fake_schema):
                first_table = store.create_table()
                second_table = store.create_table()

            self.assertIs(first_table, second_table)
            self.assertEqual([store.DEFAULT_TABLE_NAME], store.list_tables())

    def test_health_check_reports_child_database(self):
        """验证健康检查会返回正确的子库路径和表列表。"""
        with self._temporary_papers_root() as root:
            store = LanceDBPaperStore(root_path=root, database_name="child_db")
            store._database = _FakeDatabase()

            result = store.health_check()

            self.assertTrue(result["ok"])
            self.assertEqual(Path(root).resolve() / "child_db", Path(result["database_path"]))
            self.assertEqual([], result["tables"])

    def test_rejects_root_outside_project_papers(self):
        """验证 LanceDB 根目录不能位于项目 papers 目录之外。"""
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(LanceDBPathError):
                LanceDBPaperStore(root_path=root)

    def test_vector_schema_has_exact_six_non_null_fields(self):
        """验证新表只包含六个非空字段和固定 1024 维向量。"""
        schema = LanceDBPaperStore.schema()
        self.assertEqual(
            [
                "paper_id",
                "title",
                "abstract",
                "embedding_text",
                "embedding_model",
                "vector",
            ],
            schema.names,
        )
        self.assertTrue(all(not field.nullable for field in schema))
        fields = {field.name: str(field.type) for field in LanceDBPaperStore.schema()}
        self.assertEqual("string", fields["embedding_model"])
        self.assertEqual("fixed_size_list<item: float>[1024]", fields["vector"])

    def test_rejects_wrong_vector_dimension_before_write(self):
        """验证写入前会拒绝维度错误的向量。"""
        store = LanceDBPaperStore.__new__(LanceDBPaperStore)
        store.VECTOR_DIMENSION = 1024
        store.ensure_schema = lambda: object()
        with self.assertRaisesRegex(LanceDBSchemaError, "1024"):
            store.upsert_embeddings(
                [
                    {
                        "paper_id": 1,
                        "title": "Title",
                        "abstract": "Abstract",
                        "embedding_text": "Title: Title\nAbstract: Abstract",
                        "embedding_model": "text-embedding-v4",
                        "vector": [0.0],
                    }
                ]
            )

    def test_real_search_prefilters_models_and_preserves_table(self):
        """使用临时真实LanceDB验证查询接口及同维不同模型隔离。"""
        with self._temporary_papers_root() as root:
            store = LanceDBPaperStore(root_path=root)
            store.initialize()
            records = []
            for paper_id, model, vector in (
                (1, "text-embedding-v4", [1.0, 0.0]),
                (2, "BAAI/bge-m3", [1.0, 0.0]),
                (3, "text-embedding-v4", [0.0, 1.0]),
            ):
                records.append(dict(paper_id=paper_id, title="Title", abstract="Abstract",
                                    embedding_text="Title: Title\nAbstract: Abstract",
                                    embedding_model=model, vector=vector + [0.0] * 1022))
            store.upsert_embeddings(records)
            results = store.search([1.0] + [0.0] * 1023, top_k=2)
            self.assertEqual([1, 3], [row["paper_id"] for row in results])
            self.assertLess(results[0]["distance"], results[1]["distance"])
            self.assertEqual([], store.search([1.0] * 1024, embedding_model="another-model"))
            self.assertEqual(3, store.open_table().count_rows())

    def test_recreates_only_an_empty_incompatible_table(self):
        """验证只有空的旧结构表可以被安全重建。"""
        with self._temporary_papers_root() as root:
            store = LanceDBPaperStore(root_path=root)
            lancedb, pa = store._load_dependencies()
            database = lancedb.connect(str(store.database_path))
            database.create_table(
                store.DEFAULT_TABLE_NAME,
                schema=pa.schema([pa.field("paper_id", pa.int64())]),
            )
            store._database = database

            table = store.ensure_schema()

            self.assertEqual(0, table.count_rows())
            self.assertTrue(store.validate_schema()["valid"])

    def test_upsert_is_idempotent_by_paper_id(self):
        """验证相同 paper_id 重复写入只保留最新记录。"""
        with self._temporary_papers_root() as root:
            store = LanceDBPaperStore(root_path=root)
            store.initialize()
            record = {
                "paper_id": 7,
                "title": "First title",
                "abstract": "Abstract",
                "embedding_text": "Title: First title\nAbstract: Abstract",
                "embedding_model": "text-embedding-v4",
                "vector": [1.0] + [0.0] * 1023,
            }

            store.upsert_embeddings([record])
            record["title"] = "Updated title"
            store.upsert_embeddings([record])

            table = store.open_table()
            self.assertEqual(1, table.count_rows())
            self.assertEqual("Updated title", table.to_arrow()["title"][0].as_py())

    def test_keeps_legacy_paper_sections_unchanged(self):
        """验证初始化新表不会覆盖或删除旧 paper_sections 数据。"""
        with self._temporary_papers_root() as root:
            store = LanceDBPaperStore(root_path=root)
            lancedb, pa = store._load_dependencies()
            database = lancedb.connect(str(store.database_path))
            legacy_schema = pa.schema([pa.field("paper_id", pa.int64())])
            database.create_table(
                store.LEGACY_TABLE_NAME,
                data=[{"paper_id": 99}],
                schema=legacy_schema,
            )
            store._database = database

            store.initialize()

            self.assertIn(store.LEGACY_TABLE_NAME, store.list_tables())
            legacy = store.open_table(store.LEGACY_TABLE_NAME)
            self.assertEqual(1, legacy.count_rows())


if __name__ == "__main__":
    unittest.main()
