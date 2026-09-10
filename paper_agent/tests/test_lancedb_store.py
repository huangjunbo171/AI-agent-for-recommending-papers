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
    def __init__(self, schema):
        self.schema = schema


class _FakeDatabase:
    def __init__(self):
        self.tables = {}

    def table_names(self):
        return list(self.tables)

    def create_table(self, name, schema):
        table = _FakeTable(schema)
        self.tables[name] = table
        return table

    def open_table(self, name):
        return self.tables[name]


class LanceDBPaperStoreTest(unittest.TestCase):
    @staticmethod
    def _temporary_papers_root():
        return tempfile.TemporaryDirectory(
            dir=Path(__file__).resolve().parents[2] / "papers"
        )

    def test_rejects_database_path_escape(self):
        with self._temporary_papers_root() as root:
            for invalid_name in ("..", "../outside", "folder/child"):
                with self.subTest(invalid_name=invalid_name):
                    with self.assertRaises(LanceDBPathError):
                        LanceDBPaperStore(root_path=root, database_name=invalid_name)

    def test_creates_empty_table_without_overwriting_existing_table(self):
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
        with self._temporary_papers_root() as root:
            store = LanceDBPaperStore(root_path=root, database_name="child_db")
            store._database = _FakeDatabase()

            result = store.health_check()

            self.assertTrue(result["ok"])
            self.assertEqual(Path(root).resolve() / "child_db", Path(result["database_path"]))
            self.assertEqual([], result["tables"])

    def test_rejects_root_outside_project_papers(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(LanceDBPathError):
                LanceDBPaperStore(root_path=root)

    def test_vector_schema_uses_bge_m3_dimension(self):
        fields = {field.name: str(field.type) for field in LanceDBPaperStore.schema()}
        self.assertEqual("string", fields["embedding_model"])
        self.assertEqual("fixed_size_list<item: float>[1024]", fields["vector"])

    def test_rejects_wrong_vector_dimension_before_write(self):
        store = LanceDBPaperStore.__new__(LanceDBPaperStore)
        store.VECTOR_DIMENSION = 1024
        store.ensure_schema = lambda: object()
        with self.assertRaisesRegex(LanceDBSchemaError, "1024"):
            store.upsert_sections([{"paper_id": 1, "vector": [0.0]}])

    def test_recreates_only_an_empty_incompatible_table(self):
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
        with self._temporary_papers_root() as root:
            store = LanceDBPaperStore(root_path=root)
            store.initialize()
            record = {
                "paper_id": 7,
                "title": "First title",
                "authors": "[]",
                "url": "https://arxiv.org/abs/2609.00007",
                "abstract": "Abstract",
                "field": "[\"cs.AI\"]",
                "gene_keywords": "[]",
                "image_path": "",
                "section_text": "Abstract",
                "embedding_text": "Title: First title\nAbstract: Abstract",
                "embedding_model": "BAAI/bge-m3",
                "vector": [0.0] * 1024,
            }

            store.upsert_sections([record])
            record["title"] = "Updated title"
            store.upsert_sections([record])

            table = store.open_table()
            self.assertEqual(1, table.count_rows())
            self.assertEqual("Updated title", table.to_arrow()["title"][0].as_py())


if __name__ == "__main__":
    unittest.main()
