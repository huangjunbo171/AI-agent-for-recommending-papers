import json
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paper_agent.prompts_test import (  # noqa: E402
    analyze_paper_metadata_prompt,
    analyze_paper_metadata_user_prompt,
)
from utils.arxiv_source import Paper  # noqa: E402
from utils.paper_analyzer import (  # noqa: E402
    DeepSeekAnalyzer,
    apply_analysis_metadata,
    count_english_words,
    detect_english_text,
    parse_analysis_json,
    strip_analysis_sections,
)


def _detailed_core_method() -> str:
    """构造约 330 个英文词且保留两段的方法说明。"""
    sentence = (
        "The method encodes each input into a structured representation, applies a "
        "controlled transformation, and evaluates the resulting state with a "
        "task-specific objective."
    )
    return " ".join([sentence] * 8) + "\n\n" + " ".join([sentence] * 7)


def _analysis_payload(
    core_method: str = "",
    code_status: str = "unknown",
    code_url: str = "",
    code_evidence: str = "",
    venue: str = "",
    venue_evidence: str = "",
) -> dict:
    """构造满足字段数量约束的英文分析结果。"""
    return {
        "keywords": ["evaluation", "benchmark", "reliability", "model", "testing"],
        "research_topics": ["AI evaluation", "Benchmarking", "Model reliability"],
        "core_method": core_method or _detailed_core_method(),
        "datasets": [],
        "main_contributions": ["Introduces a controlled evaluation framework"],
        "main_results": ["Reports consistent improvements across tested settings"],
        "limitations": [],
        "code_status": code_status,
        "code_url": code_url,
        "code_evidence": code_evidence,
        "venue": venue,
        "venue_evidence": venue_evidence,
    }


def _paper() -> Paper:
    """构造 DeepSeek 分析测试使用的英文论文。"""
    now = datetime.now(timezone.utc)
    return Paper(
        paper_id=1,
        arxiv_id="2609.00001",
        title="A Reliable Evaluation Method for AI Systems",
        authors=["Alice Example"],
        abstract=(
            "This paper introduces a controlled evaluation method for artificial "
            "intelligence systems and reports results across representative tasks."
        ),
        categories=["cs.AI"],
        published_at=now,
        updated_at=now,
        paper_url="https://arxiv.org/abs/2609.00001",
        pdf_url="https://arxiv.org/pdf/2609.00001",
        doi=None,
        venue=None,
        raw_metadata={},
        full_text=(
            "# A Reliable Evaluation Method for AI Systems\n\n"
            "## Method\nThe full paper describes a controlled benchmark.\n\n"
            "## Experiments\nThe evaluation covers representative tasks."
        ),
    )


class PaperAnalyzerTest(unittest.TestCase):
    """验证英文过滤、集中 Prompt 和 DeepSeek 输出重试。"""

    def test_detects_english_and_rejects_chinese(self):
        """验证语言检测接受英文并拒绝中文文本。"""
        english = detect_english_text(_paper().abstract)
        chinese = detect_english_text("本文提出一种人工智能评测方法，并分析其性能。")

        self.assertTrue(english.is_english)
        self.assertEqual("en", english.language)
        self.assertFalse(chinese.is_english)

    def test_rejects_non_english_analysis(self):
        """验证结构合法但包含中文的分析结果会被拒绝。"""
        payload = _analysis_payload(core_method="一种受控评测方法")
        with self.assertRaisesRegex(ValueError, "CJK"):
            parse_analysis_json(
                json.dumps(payload, ensure_ascii=False), _paper().full_text
            )

    def test_prompt_builders_live_in_prompts_test(self):
        """验证 system 和 user Prompt 都由 prompts_test 构造。"""
        system_prompt = analyze_paper_metadata_prompt()
        user_prompt = analyze_paper_metadata_user_prompt(
            "Paper title",
            ["Alice"],
            ["cs.AI"],
            "Paper abstract",
            "",
            "# Full paper\n\n## Method\nComplete method details.",
        )

        self.assertIn("所有非空字符串值必须使用英文", system_prompt)
        self.assertIn("300 到 600 个英文单词", system_prompt)
        prompt_data = json.loads(user_prompt)
        self.assertEqual("Paper title", prompt_data["metadata"]["title"])
        self.assertIn("Complete method details", prompt_data["full_text_markdown"])

    def test_strips_related_work_and_references_from_markdown(self):
        """验证预处理删除相关工作和参考文献，但保留后续方法与实验。"""
        full_text = (
            "# Paper\n\n## 1 Introduction\nIntroduction text.\n\n"
            "## 2 Related Work\nRelated comparison.\n\n"
            "### 2.1 Prior Systems\nPrior system details.\n\n"
            "## 3 Method\nMethod details.\n\n"
            "## 4 Experiments\nExperiment details.\n\n"
            "## References\nReference entry."
        )

        cleaned = strip_analysis_sections(full_text)

        self.assertIn("Introduction text", cleaned)
        self.assertIn("Method details", cleaned)
        self.assertIn("Experiment details", cleaned)
        self.assertNotIn("Related comparison", cleaned)
        self.assertNotIn("Prior system details", cleaned)
        self.assertNotIn("Reference entry", cleaned)

    def test_strips_mineru_html_split_section_titles(self):
        """验证 MinerU 插入 HTML 标签后仍能识别相关工作与参考文献。"""
        full_text = (
            "# Paper\n\n## 1<sub>.</sub> Introduction\nIntroduction.\n\n"
            "## 2<sub>.</sub> R<sub>e</sub>lated W<sub>or</sub>k\nPrior work.\n\n"
            "## 3<sub>.</sub> Method\nMethod details.\n\n"
            "## Referen<sub>c</sub>e<sub>s</sub>\nReference entry."
        )

        cleaned = strip_analysis_sections(full_text)

        self.assertIn("Introduction", cleaned)
        self.assertIn("Method details", cleaned)
        self.assertNotIn("Prior work", cleaned)
        self.assertNotIn("Reference entry", cleaned)

    def test_strips_unnumbered_literature_review(self):
        """验证未编号的综述标题不会被误当罗马数字编号而漏删。"""
        full_text = (
            "# Paper\n\n## Literature Review\nPrior system details.\n\n"
            "## II Method\nMethod details.\n\n"
            "## III References\nReference entry."
        )

        cleaned = strip_analysis_sections(full_text)

        self.assertIn("Method details", cleaned)
        self.assertNotIn("Prior system details", cleaned)
        self.assertNotIn("Reference entry", cleaned)

    def test_core_method_preserves_paragraphs_and_word_count(self):
        """验证详细方法达到词数要求并保留自然段。"""
        result = parse_analysis_json(
            json.dumps(_analysis_payload()), _paper().full_text
        )
        self.assertIn("\n\n", result["core_method"])
        self.assertGreaterEqual(count_english_words(result["core_method"]), 300)

    def test_rejects_short_core_method(self):
        """验证过短的核心方法说明会被拒绝并触发重试。"""
        payload = _analysis_payload(core_method="A short method description.")
        with self.assertRaisesRegex(ValueError, "300 to 600"):
            parse_analysis_json(json.dumps(payload), _paper().full_text)

    def test_accepts_official_github_code_from_body(self):
        """验证正文明确声明的官方 GitHub 仓库能够通过校验。"""
        evidence = (
            "The implementation used in this paper is publicly available under the "
            "MIT License at https://github.com/example/paper-code."
        )
        full_text = f"# Paper\n\n## Code Availability\n{evidence}\n\n## References\n"
        payload = _analysis_payload(
            code_status="yes",
            code_url="https://github.com/example/paper-code/tree/main",
            code_evidence=evidence,
        )
        result = parse_analysis_json(json.dumps(payload), full_text)
        self.assertEqual("https://github.com/example/paper-code", result["code_url"])

        paper = _paper()
        apply_analysis_metadata(paper, result)
        self.assertEqual("yes", paper.is_code_open_source)
        self.assertEqual(1, paper.is_code_open)

    def test_rejects_github_link_found_only_in_references(self):
        """验证参考文献中的第三方 GitHub 链接不能标记为本文开源。"""
        evidence = "A related toolkit is available at https://github.com/example/tool."
        full_text = f"# Paper\n\n## Method\nDetails.\n\n## References\n{evidence}"
        payload = _analysis_payload(
            code_status="yes",
            code_url="https://github.com/example/tool",
            code_evidence=evidence,
        )
        with self.assertRaisesRegex(ValueError, "paper body"):
            parse_analysis_json(json.dumps(payload), full_text)

    def test_maps_future_code_release_to_closed_state(self):
        """验证未来才发布代码会映射为 no/0，而不是当前已开源。"""
        evidence = "We plan to release the implementation after peer review."
        payload = _analysis_payload(
            code_status="no", code_evidence=evidence
        )
        result = parse_analysis_json(json.dumps(payload), evidence)
        paper = _paper()
        apply_analysis_metadata(paper, result)
        self.assertEqual("no", paper.is_code_open_source)
        self.assertEqual(0, paper.is_code_open)
        self.assertIsNone(paper.code_url)

    def test_rejects_unknown_when_body_explicitly_opens_code(self):
        """验证正文已有开源声明时不能错误返回 unknown。"""
        full_text = "The source code is publicly available in our repository."
        with self.assertRaisesRegex(ValueError, "conflicts with explicit body evidence"):
            parse_analysis_json(json.dumps(_analysis_payload()), full_text)

    def test_accepts_published_venue_and_rejects_under_review(self):
        """验证只接受明确发表或接收的 venue 证据。"""
        accepted = "This paper was accepted at Example Conference 2026."
        full_text = f"# Paper\n\n{accepted}\n\n## Method\nDetails."
        payload = _analysis_payload(
            venue="Example Conference 2026", venue_evidence=accepted
        )
        result = parse_analysis_json(json.dumps(payload), full_text)
        self.assertEqual("Example Conference 2026", result["venue"])

        review = "This paper is under review at Example Conference 2026."
        payload = _analysis_payload(
            venue="Example Conference 2026", venue_evidence=review
        )
        with self.assertRaisesRegex(ValueError, "accepted or published"):
            parse_analysis_json(json.dumps(payload), review)

    def test_accepts_venue_from_arxiv_journal_reference(self):
        """验证 arXiv journal_ref 可作为可靠的发表 venue 证据。"""
        journal_ref = "Journal of Reliable AI, Volume 8, 2026"
        payload = _analysis_payload(
            venue="Journal of Reliable AI", venue_evidence=journal_ref
        )
        result = parse_analysis_json(
            json.dumps(payload), _paper().full_text, journal_ref=journal_ref
        )
        self.assertEqual("Journal of Reliable AI", result["venue"])

    def test_rejects_missing_full_text_before_request(self):
        """验证没有 MinerU 全文时不会退回标题摘要分析。"""
        paper = _paper()
        paper.full_text = ""
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test"}), patch(
            "utils.paper_analyzer.httpx.post"
        ) as request:
            with self.assertRaisesRegex(RuntimeError, "拒绝仅根据标题或摘要"):
                DeepSeekAnalyzer().analyze(paper)
        request.assert_not_called()

    def test_rejects_oversized_full_text_without_truncation(self):
        """验证全文超限时明确失败，不截断后继续分析。"""
        paper = _paper()
        paper.full_text = "A" * 1001
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test"}), patch(
            "utils.paper_analyzer.httpx.post"
        ) as request:
            with self.assertRaisesRegex(RuntimeError, "拒绝截断后分析"):
                DeepSeekAnalyzer(max_full_text_chars=1000).analyze(paper)
        request.assert_not_called()

    def test_deepseek_retries_chinese_then_accepts_english(self):
        """验证 DeepSeek 首次返回中文时重试并接受下一次英文结果。"""
        chinese = _analysis_payload(core_method="一种受控评测方法")
        english = _analysis_payload()
        first = Mock(status_code=200)
        first.json.return_value = {
            "choices": [{"message": {"content": json.dumps(chinese, ensure_ascii=False)}}]
        }
        second = Mock(status_code=200)
        second.json.return_value = {
            "choices": [{"message": {"content": json.dumps(english)}}]
        }
        waits = []

        paper = _paper()
        paper.full_text = (
            "# Paper\n\n## Related Work\nComparison that must be removed.\n\n"
            "## Method\nThe full paper describes a controlled benchmark.\n\n"
            "## References\nReference that must be removed."
        )
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test"}), patch(
            "utils.paper_analyzer.httpx.post", side_effect=[first, second]
        ) as request:
            result = DeepSeekAnalyzer(sleep=waits.append).analyze(paper)

        self.assertEqual(english, result)
        self.assertEqual(2, request.call_count)
        self.assertEqual([1.0], waits)
        request_payload = request.call_args_list[0].kwargs["json"]
        user_content = request_payload["messages"][1]["content"]
        self.assertIn("The full paper describes", user_content)
        self.assertNotIn("Comparison that must be removed", user_content)
        self.assertNotIn("Reference that must be removed", user_content)
        self.assertGreater(
            paper.raw_metadata["analysis_preprocessing"]["removed_chars"], 0
        )


if __name__ == "__main__":
    unittest.main()
