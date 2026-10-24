import json
import importlib.util
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "paper_agent"))
MODULE_PATH = PROJECT_ROOT / "paper_agent" / "paper_agent" / "arxiv_ingest.py"
SPEC = importlib.util.spec_from_file_location("arxiv_ingest_under_test", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
analyze_paper_metadata_prompt = MODULE.analyze_paper_metadata_prompt
arxiv_candidate_pool_size = MODULE.arxiv_candidate_pool_size
build_embedding_text = MODULE.build_embedding_text
build_lancedb_records = MODULE.build_lancedb_records
canonical_arxiv_id = MODULE.canonical_arxiv_id
parse_analysis_json = MODULE.parse_analysis_json
parse_arxiv_feed = MODULE.parse_arxiv_feed
stable_paper_id = MODULE.stable_paper_id
ingest = MODULE.ingest
prepare_papers_with_mineru = MODULE.prepare_papers_with_mineru


ATOM_FIXTURE = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2609.10522v1</id>
    <updated>2026-09-09T12:30:00Z</updated>
    <published>2026-09-09T12:30:00Z</published>
    <title>  A Test\n Paper </title>
    <summary> We introduce a reliable AI method. </summary>
    <author><name>Alice Example</name></author>
    <author><name>Bob Example</name></author>
    <category term="cs.AI" />
    <category term="cs.LG" />
    <link href="http://arxiv.org/abs/2609.10522v1" rel="alternate" />
    <link title="pdf" href="http://arxiv.org/pdf/2609.10522v1" />
    <arxiv:doi>10.1000/example</arxiv:doi>
  </entry>
</feed>
"""


def _valid_analysis_payload() -> dict:
    """构造满足全文分析字段和方法长度要求的结果。"""
    sentence = (
        "The method encodes each input into a structured representation, applies a "
        "controlled transformation, and evaluates the state with a task objective."
    )
    return {
        "keywords": ["one", "two", "three", "four", "five"],
        "research_topics": ["AI evaluation", "Benchmarking", "Reliability"],
        "core_method": " ".join([sentence] * 16),
        "datasets": [],
        "main_contributions": ["Introduces the benchmark"],
        "main_results": [],
        "limitations": [],
        "code_status": "unknown",
        "code_url": "",
        "code_evidence": "",
        "venue": "",
        "venue_evidence": "",
    }


class ArxivIngestTest(unittest.TestCase):
    """验证 arXiv 抓取、LLM 结果解析和向量文本构造。"""

    def test_canonical_id_and_stable_modern_id(self):
        """验证新版 arXiv ID 的版本号清理和稳定主键生成。"""
        self.assertEqual("2609.10522", canonical_arxiv_id("2609.10522v3"))
        self.assertEqual(260910522, stable_paper_id("2609.10522v3"))

    def test_candidate_pool_expands_for_one_hundred_papers(self):
        """验证百篇入库会读取足够候选，同时遵守 200 篇上限。"""
        self.assertEqual(30, arxiv_candidate_pool_size(10))
        self.assertEqual(200, arxiv_candidate_pool_size(100))

    def test_paper_count_is_command_line_alias_for_limit(self):
        """验证命令行可直接指定本次需要成功入库的论文数量。"""
        args = MODULE.build_parser().parse_args(["--paper-count", "100"])
        self.assertEqual(100, args.limit)

    def test_legacy_id_is_stable_positive_int(self):
        """验证旧版 arXiv ID 能生成稳定的正整数主键。"""
        first = stable_paper_id("cs/9901001v2")
        self.assertEqual(first, stable_paper_id("cs/9901001"))
        self.assertGreater(first, 0)
        self.assertLessEqual(first, 0x7FFFFFFF)

    def test_parse_atom_feed(self):
        """验证 Atom XML 能完整解析为标准论文对象。"""
        papers = parse_arxiv_feed(ATOM_FIXTURE)
        self.assertEqual(1, len(papers))
        paper = papers[0]
        self.assertEqual(260910522, paper.paper_id)
        self.assertEqual("A Test Paper", paper.title)
        self.assertEqual(["Alice Example", "Bob Example"], paper.authors)
        self.assertEqual(["cs.AI", "cs.LG"], paper.categories)
        self.assertEqual("10.1000/example", paper.doi)
        self.assertIsNone(paper.venue)
        self.assertTrue(paper.paper_url.startswith("https://"))
        self.assertTrue(paper.pdf_url.startswith("https://"))

    def test_parse_llm_json_with_fences(self):
        """验证能够清理 Markdown 代码块并解析合法分析 JSON。"""
        payload = _valid_analysis_payload()
        parsed = parse_analysis_json(
            "```json\n" + json.dumps(payload) + "\n```", "Full paper body"
        )
        self.assertEqual(payload, parsed)

    def test_rejects_wrong_keyword_count(self):
        """验证关键词数量不符合约定时会拒绝分析结果。"""
        payload = _valid_analysis_payload()
        payload["keywords"] = ["one"]
        with self.assertRaisesRegex(ValueError, "exactly five"):
            parse_analysis_json(json.dumps(payload), "Full paper body")

    def test_embedding_text_only_uses_title_and_abstract(self):
        """验证向量化文本只包含最终标题和摘要，不包含 LLM 分析。"""
        paper = parse_arxiv_feed(ATOM_FIXTURE)[0]
        paper.analysis = _valid_analysis_payload()
        text = build_embedding_text(paper)
        self.assertEqual(
            "Title: A Test Paper\nAbstract: We introduce a reliable AI method.",
            text,
        )
        self.assertNotIn("AI evaluation", text)

    def test_lancedb_record_contains_only_six_fields(self):
        """验证入口映射出的 LanceDB 记录符合精简六字段设计。"""
        paper = parse_arxiv_feed(ATOM_FIXTURE)[0]
        paper.embedding_text = build_embedding_text(paper)
        paper.vector = [1.0] + [0.0] * 1023

        record = build_lancedb_records([paper], "text-embedding-v4")[0]

        self.assertEqual(
            {
                "paper_id",
                "title",
                "abstract",
                "embedding_text",
                "embedding_model",
                "vector",
            },
            set(record),
        )

    def test_analysis_prompt_requires_english_and_keeps_json_keys(self):
        """验证分析 Prompt 集中要求英文输出且字段名保持不变。"""
        prompt = analyze_paper_metadata_prompt()
        self.assertIn("所有非空字符串值必须使用英文", prompt)
        self.assertIn("必须以用户提供的 MinerU 论文正文", prompt)
        self.assertIn("删除 Related Work、References 和 Bibliography", prompt)
        self.assertIn("300 到 600 个英文单词", prompt)
        for field in (
            "keywords",
            "research_topics",
            "core_method",
            "datasets",
            "main_contributions",
            "main_results",
            "limitations",
            "code_status",
            "code_url",
            "venue",
        ):
            self.assertIn(f'"{field}"', prompt)

    def test_insufficient_candidates_do_not_write_mysql_or_lancedb(self):
        """验证不足目标数量时在任何数据库写入前失败。"""
        paper = parse_arxiv_feed(ATOM_FIXTURE)[0]
        analysis = _valid_analysis_payload()
        repository = Mock()
        analyzer = Mock(model="deepseek-chat")
        analyzer.analyze.return_value = analysis
        mineru = Mock(model_version="vlm")
        mineru.extract_batch.return_value = MODULE.MinerUBatchOutcome(
            extractions={
                paper.paper_id: MODULE.MinerUExtraction(
                    paper_id=paper.paper_id,
                    title=paper.title,
                    abstract=paper.abstract,
                    title_source="arxiv_fallback",
                    abstract_source="arxiv_fallback",
                    markdown_path=Path("full.md"),
                    full_text="# A Test Paper\n\n## Method\nFull paper content.",
                )
            }
        )
        args = SimpleNamespace(
            limit=2,
            sync_lancedb_only=False,
            category="cs.AI",
            provider="deepseek",
            mineru_model="vlm",
            embedding_provider="dashscope",
            embedding_model="text-embedding-v4",
            dry_run=False,
            reanalyze_existing=False,
        )

        with patch.object(MODULE, "MySQLPaperRepository", return_value=repository), patch.object(
            MODULE, "fetch_arxiv_papers", return_value=[paper]
        ), patch.object(MODULE, "DeepSeekAnalyzer", return_value=analyzer), patch.object(
            MODULE, "MinerUClient", return_value=mineru
        ), patch.object(MODULE, "LanceDBPaperStore") as store_class:
            with self.assertRaises(MODULE.IngestError):
                ingest(args)

        repository.upsert_batch.assert_not_called()
        store_class.assert_not_called()

    def test_non_english_candidate_is_skipped_and_replaced(self):
        """验证非英文论文会被跳过并使用后续英文候选补位。"""
        base = parse_arxiv_feed(ATOM_FIXTURE)[0]
        chinese = replace(
            base,
            paper_id=1,
            arxiv_id="2609.00001",
            title="一种人工智能评测方法",
            abstract="本文提出一种可靠的人工智能评测方法，并通过多个实验分析该方法的性能和局限。",
            raw_metadata={},
        )
        english = replace(base, paper_id=2, arxiv_id="2609.00002", raw_metadata={})
        analysis = _valid_analysis_payload()
        analyzer = Mock()
        analyzer.analyze.return_value = analysis
        mineru = Mock(model_version="vlm")

        def extract(documents):
            """使用候选自带字段构造 MinerU 测试结果。"""
            document = documents[0]
            return MODULE.MinerUBatchOutcome(
                extractions={
                    document.paper_id: MODULE.MinerUExtraction(
                        paper_id=document.paper_id,
                        title=document.fallback_title,
                        abstract=document.fallback_abstract,
                        title_source="mineru",
                        abstract_source="mineru",
                        markdown_path=Path("full.md"),
                        full_text=(
                            f"# {document.fallback_title}\n\n"
                            "## Method\nFull paper content."
                        ),
                    )
                }
            )

        mineru.extract_batch.side_effect = extract
        summary = {
            "pdf_downloaded": 0,
            "mineru_parsed": 0,
            "mineru_field_fallbacks": 0,
            "full_text_loaded": 0,
            "non_english_skipped": 0,
            "analyzed": 0,
            "skipped": 0,
            "failures": [],
        }

        prepared = prepare_papers_with_mineru(
            [chinese, english], 1, mineru, analyzer, summary
        )

        self.assertEqual([2], [paper.paper_id for paper in prepared])
        self.assertEqual(1, summary["non_english_skipped"])
        analyzer.analyze.assert_called_once_with(english)
        self.assertEqual("unknown", english.is_code_open_source)
        self.assertIsNone(english.venue)

    def test_authentication_failure_stops_candidate_processing(self):
        """验证鉴权失败会终止处理，而不是跳过当前论文并继续请求。"""
        paper = parse_arxiv_feed(ATOM_FIXTURE)[0]
        analyzer = Mock()
        analyzer.analyze.side_effect = MODULE.AuthenticationError("认证失败")
        mineru = Mock(model_version="vlm")
        mineru.extract_batch.return_value = MODULE.MinerUBatchOutcome(
            extractions={paper.paper_id: Mock()}
        )
        summary = {
            "pdf_downloaded": 0,
            "mineru_parsed": 0,
            "mineru_field_fallbacks": 0,
            "full_text_loaded": 0,
            "non_english_skipped": 0,
            "analyzed": 0,
            "skipped": 0,
            "failures": [],
        }

        with patch.object(
            MODULE, "apply_mineru_extraction", return_value=0
        ), patch.object(MODULE, "_record_language", return_value=True):
            with self.assertRaises(MODULE.AuthenticationError):
                prepare_papers_with_mineru(
                    [paper, replace(paper, paper_id=paper.paper_id + 1)],
                    1,
                    mineru,
                    analyzer,
                    summary,
                )

        analyzer.analyze.assert_called_once()
        mineru.extract_batch.assert_called_once()
        self.assertEqual(0, summary["skipped"])

    def test_mineru_batches_are_limited_to_fifty_documents(self):
        """验证百篇入库时 MinerU 请求会拆成不超过 50 篇的批次。"""
        base = parse_arxiv_feed(ATOM_FIXTURE)[0]
        papers = [
            replace(
                base,
                paper_id=index,
                arxiv_id=f"2610.{index:05d}",
                raw_metadata={},
            )
            for index in range(1, 52)
        ]
        analyzer = Mock()
        analyzer.analyze.return_value = _valid_analysis_payload()
        mineru = Mock(model_version="vlm")

        def extract(documents):
            """为每个 MinerU 测试批次构造成功解析结果。"""
            return MODULE.MinerUBatchOutcome(
                extractions={
                    document.paper_id: MODULE.MinerUExtraction(
                        paper_id=document.paper_id,
                        title=document.fallback_title,
                        abstract=document.fallback_abstract,
                        title_source="mineru",
                        abstract_source="mineru",
                        markdown_path=Path("full.md"),
                        full_text="# Paper\n\n## Method\nFull method details.",
                    )
                    for document in documents
                }
            )

        mineru.extract_batch.side_effect = extract
        summary = {
            "pdf_downloaded": 0,
            "mineru_parsed": 0,
            "mineru_field_fallbacks": 0,
            "full_text_loaded": 0,
            "non_english_skipped": 0,
            "analyzed": 0,
            "skipped": 0,
            "failures": [],
        }

        prepared = prepare_papers_with_mineru(
            papers, 51, mineru, analyzer, summary
        )

        self.assertEqual(51, len(prepared))
        self.assertEqual(
            [50, 1],
            [len(call.args[0]) for call in mineru.extract_batch.call_args_list],
        )

    def test_reanalyze_dry_run_does_not_write_any_store(self):
        """验证已有论文英文重分析 dry-run 不写 MySQL 或 LanceDB。"""
        paper = parse_arxiv_feed(ATOM_FIXTURE)[0]
        repository = Mock()
        repository.load_recent.return_value = [paper]
        analyzer = Mock(model="deepseek-chat")
        analyzer.analyze.return_value = _valid_analysis_payload()
        args = SimpleNamespace(
            limit=1,
            reanalyze_existing=True,
            sync_lancedb_only=False,
            provider="deepseek",
            dry_run=True,
        )

        with patch.object(MODULE, "MySQLPaperRepository", return_value=repository), patch.object(
            MODULE, "DeepSeekAnalyzer", return_value=analyzer
        ), patch.object(
            MODULE, "_load_cached_full_text", return_value="# Full paper\nContent"
        ), patch.object(MODULE, "LanceDBPaperStore") as store_class:
            result = ingest(args)

        self.assertTrue(result["dry_run"])
        self.assertEqual(1, result["reanalyzed"])
        self.assertEqual(1, result["full_text_loaded"])
        self.assertEqual("# Full paper\nContent", paper.full_text)
        self.assertEqual(1, len(result["planned_updates"]))
        repository.upsert_analysis_batch.assert_not_called()
        store_class.assert_not_called()

    def test_lancedb_validation_allows_existing_extra_papers(self):
        """验证持续追加时 LanceDB 中已有旧论文不会导致本批校验失败。"""
        paper = parse_arxiv_feed(ATOM_FIXTURE)[0]
        repository = Mock()
        repository.load_recent.return_value = [paper]
        repository.complete_ids.return_value = [paper.paper_id]
        store = Mock()
        store.upsert_embeddings.return_value = 1
        store.paper_ids.return_value = [999, paper.paper_id]
        embedder = SimpleNamespace(model_name="text-embedding-v4")
        args = SimpleNamespace(
            limit=1,
            reanalyze_existing=False,
            sync_lancedb_only=True,
            embedding_provider="dashscope",
            embedding_model="text-embedding-v4",
            dry_run=False,
        )

        def prepare(papers, provider, model):
            """为跨库校验测试补充合法向量。"""
            papers[0].embedding_text = build_embedding_text(papers[0])
            papers[0].vector = [1.0] + [0.0] * 1023
            return embedder

        with patch.object(
            MODULE, "MySQLPaperRepository", return_value=repository
        ), patch.object(
            MODULE, "prepare_embeddings", side_effect=prepare
        ), patch.object(
            MODULE, "LanceDBPaperStore", return_value=store
        ):
            result = ingest(args)

        self.assertTrue(result["verified"])
        self.assertEqual(1, result["lancedb_written"])

    def test_analysis_only_writes_mysql_without_embedding(self):
        """验证分析模式只写 MySQL，不调用向量模型或 LanceDB。"""
        paper = parse_arxiv_feed(ATOM_FIXTURE)[0]
        paper.analysis = _valid_analysis_payload()
        repository = Mock()
        repository.complete_ids.return_value = [paper.paper_id]
        analyzer = Mock(model="deepseek-flash")
        args = SimpleNamespace(
            limit=1,
            reanalyze_existing=False,
            sync_lancedb_only=False,
            skip_embedding=True,
            category="cs.AI",
            provider="deepseek",
            mineru_model="vlm",
            analysis_workers=4,
            dry_run=False,
        )

        with patch.object(
            MODULE, "MySQLPaperRepository", return_value=repository
        ), patch.object(
            MODULE, "fetch_arxiv_papers", return_value=[paper]
        ), patch.object(
            MODULE, "DeepSeekAnalyzer", return_value=analyzer
        ), patch.object(
            MODULE, "MinerUClient"
        ), patch.object(
            MODULE, "prepare_papers_with_mineru", return_value=[paper]
        ), patch.object(
            MODULE, "prepare_embeddings"
        ) as prepare_embeddings_mock, patch.object(
            MODULE, "LanceDBPaperStore"
        ) as store_class:
            result = ingest(args)

        self.assertTrue(result["verified"])
        self.assertTrue(result["embedding_skipped"])
        self.assertEqual(1, result["mysql_written"])
        repository.upsert_batch.assert_called_once_with([paper], "deepseek-flash")
        prepare_embeddings_mock.assert_not_called()
        store_class.assert_not_called()


if __name__ == "__main__":
    unittest.main()
