import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.embedding_provider import EmbeddingError
from utils.lancedb_store import LanceDBPaperStore, LanceDBSchemaError


class LanceDBSearchTest(unittest.TestCase):
    def setUp(self):
        self.store = LanceDBPaperStore()
        self.table = Mock()
        self.store.open_table = Mock(return_value=self.table)
        self.store.validate_schema = Mock(return_value={"valid": True})
        self.query = Mock()
        self.table.search.return_value = self.query
        for name in ("distance_type", "where", "select", "limit"):
            getattr(self.query, name).return_value = self.query
        self.query.to_list.return_value = [{"paper_id": 7, "_distance": 0.2}]

    def test_cosine_model_prefilter_topk_and_result(self):
        result = self.store.search([1.0] + [0.0] * 1023)
        self.assertEqual([{"paper_id": 7, "distance": 0.2}], result)
        self.query.distance_type.assert_called_once_with("cosine")
        self.query.where.assert_called_once_with("embedding_model = 'text-embedding-v4'", prefilter=True)
        self.query.limit.assert_called_once_with(5)
        self.query.select.assert_called_once_with(["paper_id", "_distance"])
        self.table.add.assert_not_called()

    def test_rejects_invalid_dimensions_values_schema_and_topk(self):
        for vector in ([1.0], [0.0] * 1024, [float("nan")] * 1024):
            with self.assertRaises(EmbeddingError):
                self.store.search(vector)
        for top_k in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                self.store.search([1.0] * 1024, top_k)
        self.store.validate_schema.return_value = {"valid": False}
        with self.assertRaises(LanceDBSchemaError):
            self.store.search([1.0] * 1024)


if __name__ == "__main__":
    unittest.main()
