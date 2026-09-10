import json
import importlib.util
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "paper_agent"))
MODULE_PATH = PROJECT_ROOT / "paper_agent" / "paper_agent" / "arxiv_ingest.py"
SPEC = importlib.util.spec_from_file_location("arxiv_ingest_under_test", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
build_embedding_text = MODULE.build_embedding_text
canonical_arxiv_id = MODULE.canonical_arxiv_id
parse_analysis_json = MODULE.parse_analysis_json
parse_arxiv_feed = MODULE.parse_arxiv_feed
stable_paper_id = MODULE.stable_paper_id


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


class ArxivIngestTest(unittest.TestCase):
    def test_canonical_id_and_stable_modern_id(self):
        self.assertEqual("2609.10522", canonical_arxiv_id("2609.10522v3"))
        self.assertEqual(260910522, stable_paper_id("2609.10522v3"))

    def test_legacy_id_is_stable_positive_int(self):
        first = stable_paper_id("cs/9901001v2")
        self.assertEqual(first, stable_paper_id("cs/9901001"))
        self.assertGreater(first, 0)
        self.assertLessEqual(first, 0x7FFFFFFF)

    def test_parse_atom_feed(self):
        papers = parse_arxiv_feed(ATOM_FIXTURE)
        self.assertEqual(1, len(papers))
        paper = papers[0]
        self.assertEqual(260910522, paper.paper_id)
        self.assertEqual("A Test Paper", paper.title)
        self.assertEqual(["Alice Example", "Bob Example"], paper.authors)
        self.assertEqual(["cs.AI", "cs.LG"], paper.categories)
        self.assertEqual("10.1000/example", paper.doi)
        self.assertTrue(paper.paper_url.startswith("https://"))
        self.assertTrue(paper.pdf_url.startswith("https://"))

    def test_parse_llm_json_with_fences(self):
        payload = {
            "keywords": ["one", "two", "three", "four", "five"],
            "research_topics": ["AI evaluation", "Benchmarking", "Reliability"],
            "core_method": "A controlled benchmark",
            "datasets": [],
            "main_contributions": ["Introduces the benchmark"],
            "main_results": [],
            "limitations": [],
        }
        parsed = parse_analysis_json("```json\n" + json.dumps(payload) + "\n```")
        self.assertEqual(payload, parsed)

    def test_rejects_wrong_keyword_count(self):
        payload = {
            "keywords": ["one"],
            "research_topics": [],
            "core_method": "",
            "datasets": [],
            "main_contributions": [],
            "main_results": [],
            "limitations": [],
        }
        with self.assertRaisesRegex(ValueError, "exactly five"):
            parse_analysis_json(json.dumps(payload))

    def test_embedding_text_uses_analysis(self):
        paper = parse_arxiv_feed(ATOM_FIXTURE)[0]
        paper.analysis = {
            "keywords": ["one", "two", "three", "four", "five"],
            "research_topics": ["AI evaluation", "Benchmarking", "Reliability"],
            "core_method": "A controlled benchmark",
            "datasets": [],
            "main_contributions": ["Introduces the benchmark"],
            "main_results": [],
            "limitations": [],
        }
        text = build_embedding_text(paper)
        self.assertIn("Title: A Test Paper", text)
        self.assertIn("Abstract: We introduce a reliable AI method.", text)
        self.assertIn("AI evaluation", text)


if __name__ == "__main__":
    unittest.main()
