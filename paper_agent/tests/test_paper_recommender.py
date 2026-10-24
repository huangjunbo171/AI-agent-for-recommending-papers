import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.paper_recommender import PostRecommendationService


def paper(identifier=1, **overrides):
    fields = dict(paper_id=identifier, title=f"Paper {identifier}", authors=["Alice"],
                  abstract="A retrieval study", paper_url=f"https://arxiv.org/abs/2610.0000{identifier}",
                  analysis={"core_method": "Retrieve candidate evidence.", "main_results": ["Improves recall."]})
    fields.update(overrides)
    return SimpleNamespace(**fields)


class PostRecommendationServiceTest(unittest.IsolatedAsyncioTestCase):
    def service(self, responses, papers=None):
        self.generate = AsyncMock(side_effect=responses)
        self.embedder = Mock(model_name="text-embedding-v4")
        self.embedder.encode.return_value = [[1.0] + [0.0] * 1023]
        self.store = Mock()
        self.store.search.return_value = [{"paper_id": p.paper_id, "distance": 0.1} for p in (papers or [])]
        self.repository = Mock()
        self.repository.load_by_ids.return_value = papers or []
        return PostRecommendationService(self.embedder, self.store, self.repository, self.generate, log=Mock())

    async def test_three_recommendation_strategies_retrieve_then_generate(self):
        for strategy in ("直接推荐", "互动+推荐", "推荐相关领域论文"):
            with self.subTest(strategy=strategy):
                service = self.service([strategy, '{"papers":[{"paper_id":1,"evidence_indices":[0]}]}',
                                        "Useful retrieval evidence [1].", "Useful retrieval evidence [1]."], [paper()])
                result = await service.recommend({"content": "How can retrieval improve?"}, "Researcher", "AI")
                self.assertEqual(strategy, result.strategy)
                self.assertEqual([1], [p["paper_id"] for p in result.papers])
                self.assertIn("https://arxiv.org/abs/2610.00001", result.content)
                self.assertLessEqual(len(result.content), 270)
                self.embedder.encode.assert_called_once_with(["How can retrieval improve?"])
                self.store.search.assert_called_once_with(self.embedder.encode.return_value[0], 5, "text-embedding-v4")
                self.repository.load_by_ids.assert_called_once_with([1])
                self.assertTrue(all(call.kwargs["provider"] == "deepseek" for call in self.generate.call_args_list))

    async def test_only_interaction_and_invalid_strategy_never_retrieve(self):
        for strategy in ("只互动", "malformed strategy"):
            service = self.service([strategy, "How does evaluation account for drift?", "How does evaluation account for drift?"])
            result = await service.recommend({"content": "Evaluation matters"}, "Researcher")
            self.assertEqual("只互动", result.strategy)
            self.assertEqual([], result.papers)
            self.embedder.encode.assert_not_called()
            self.store.search.assert_not_called()
            self.repository.load_by_ids.assert_not_called()

    async def test_irrelevant_post_skips(self):
        service = self.service(["跳过"])
        self.assertIsNone(await service.recommend({"content": "Unrelated"}, "Researcher"))
        self.embedder.encode.assert_not_called()

    async def test_selection_rejects_hallucinated_ids_and_evidence(self):
        for selection in ('{"papers":[{"paper_id":99,"evidence_indices":[0]}]}',
                          '{"papers":[{"paper_id":1,"evidence_indices":[999]}]}', "bad JSON"):
            service = self.service(["直接推荐", selection, "How was this evaluated?", "How was this evaluated?"], [paper()])
            result = await service.recommend({"content": "Retrieval"}, "Researcher")
            self.assertEqual("只互动", result.strategy)
            self.assertNotIn("https://", result.content)

    async def test_missing_sql_records_and_invalid_details_are_dropped(self):
        for papers in ([], [paper(paper_url="")], [paper(analysis={})]):
            service = self.service(["直接推荐", "How was this evaluated?", "How was this evaluated?"], papers)
            self.store.search.return_value = [{"paper_id": 1, "distance": 0.1}]
            result = await service.recommend({"content": "Retrieval"}, "Researcher")
            self.assertEqual("只互动", result.strategy)

    async def test_duplicate_retrieval_ids_are_loaded_once(self):
        service = self.service(["直接推荐", '{"papers":[]}', "Specific question?", "Specific question?"], [paper()])
        self.store.search.return_value *= 2
        await service.recommend({"content": "Retrieval"}, "Researcher")
        self.repository.load_by_ids.assert_called_once_with([1])

    async def test_empty_selection_and_embedding_error_fall_back(self):
        service = self.service(["直接推荐", "A specific question?", "A specific question?"])
        self.embedder.encode.side_effect = RuntimeError("embedding unavailable")
        result = await service.recommend({"content": "Retrieval"}, "Researcher")
        self.assertEqual("只互动", result.strategy)
        self.repository.load_by_ids.assert_not_called()

    async def test_maximum_three_papers_and_link_budget(self):
        papers = [paper(index) for index in range(1, 5)]
        selection = json.dumps({"papers": [{"paper_id": index, "evidence_indices": [0]} for index in range(1, 5)]})
        service = self.service(["互动+推荐", selection, "Compare [1], [2] and [3].", "Compare [1], [2] and [3]."], papers)
        result = await service.recommend({"content": "Retrieval"}, "Researcher")
        self.assertEqual(3, len(result.papers))
        self.assertEqual(3, result.content.count("https://"))
        self.assertLessEqual(len(result.content), 270)

    async def test_overlong_reply_drops_last_paper_and_regenerates(self):
        papers = [paper(index) for index in range(1, 4)]
        selection = json.dumps({"papers": [{"paper_id": p.paper_id, "evidence_indices": [0]} for p in papers]})
        service = self.service(["直接推荐", selection, "x" * 300, "x" * 300,
                                "Complementary evidence [1] and [2].", "Complementary evidence [1] and [2]."], papers)
        result = await service.recommend({"content": "Retrieval"}, "Researcher")
        self.assertEqual([1, 2], [p["paper_id"] for p in result.papers])
        self.assertNotIn("2610.00003", result.content)

    async def test_generated_links_bad_citations_and_generation_failures_skip(self):
        for body in ("Unknown source https://invented.example", "Unsupported [99]", "x" * 300, ""):
            service = self.service(["只互动", "Draft", body])
            self.assertIsNone(await service.recommend({"content": "Retrieval"}, "Researcher"))
        service = self.service([RuntimeError("LLM unavailable")])
        self.assertIsNone(await service.recommend({"content": "Retrieval"}, "Researcher"))


if __name__ == "__main__":
    unittest.main()
