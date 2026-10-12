import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import httpx


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.mineru_client import (  # noqa: E402
    MinerUClient,
    MinerUDocument,
    MinerUError,
    extract_title_and_abstract,
)


LONG_ABSTRACT = (
    "This paper introduces a reliable artificial intelligence method and evaluates "
    "it on several representative tasks with careful experiments and analysis."
)


def _zip_with_markdown(markdown: str) -> bytes:
    """在内存中创建仅包含 full.md 的测试 ZIP。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("result/full.md", markdown)
    return buffer.getvalue()


class MinerUClientTest(unittest.TestCase):
    """验证 MinerU 字段抽取、缓存、上传、轮询与 ZIP 读取。"""

    def test_extracts_title_and_abstract_without_llm(self):
        """验证从一级标题和 Abstract 小节确定性抽取字段。"""
        markdown = f"# A Reliable AI Paper\n\n## Abstract\n\n{LONG_ABSTRACT}\n\n## 1 Introduction\nBody"
        title, abstract, title_source, abstract_source = extract_title_and_abstract(
            markdown, "Fallback title", "Fallback abstract"
        )

        self.assertEqual("A Reliable AI Paper", title)
        self.assertEqual(LONG_ABSTRACT, abstract)
        self.assertEqual("mineru", title_source)
        self.assertEqual("mineru", abstract_source)

    def test_falls_back_to_arxiv_for_invalid_fields(self):
        """验证标题或摘要不合理时分别回退 arXiv 元数据。"""
        title, abstract, title_source, abstract_source = extract_title_and_abstract(
            "# x\n\n## Introduction\nNo abstract section.",
            "Fallback arXiv title",
            LONG_ABSTRACT,
        )

        self.assertEqual("Fallback arXiv title", title)
        self.assertEqual(LONG_ABSTRACT, abstract)
        self.assertEqual("arxiv_fallback", title_source)
        self.assertEqual("arxiv_fallback", abstract_source)

    def test_reuses_valid_full_markdown_cache(self):
        """验证存在有效 full.md 时不再进行任何网络请求。"""
        def handler(request: httpx.Request) -> httpx.Response:
            """若缓存失效而发起网络请求则让测试失败。"""
            raise AssertionError(f"不应发起网络请求：{request.url}")

        with tempfile.TemporaryDirectory() as root:
            cache_root = Path(root)
            document_dir = cache_root / "7"
            document_dir.mkdir()
            (document_dir / "full.md").write_text(
                f"# Cached Paper Title\n\n## Abstract\n{LONG_ABSTRACT}",
                encoding="utf-8",
            )
            client = httpx.Client(transport=httpx.MockTransport(handler))
            mineru = MinerUClient(
                token="test", cache_root=cache_root, client=client
            )
            outcome = mineru.extract_batch(
                [MinerUDocument(7, "https://example.test/p.pdf", "fallback", LONG_ABSTRACT)]
            )

            self.assertEqual(1, outcome.cache_hits)
            self.assertEqual("Cached Paper Title", outcome.extractions[7].title)
            client.close()

    def test_upload_omits_content_type(self):
        """验证预签名上传请求不主动设置 Content-Type。"""
        observed_content_type: list[str | None] = []

        def handler(request: httpx.Request) -> httpx.Response:
            """返回上传地址并记录 PUT 请求头。"""
            if request.method == "POST":
                return httpx.Response(
                    200,
                    request=request,
                    json={
                        "code": 0,
                        "data": {
                            "batch_id": "batch-1",
                            "file_urls": ["https://upload.test/file"],
                        },
                    },
                )
            observed_content_type.append(request.headers.get("content-type"))
            return httpx.Response(200, request=request)

        with tempfile.TemporaryDirectory() as root:
            pdf_path = Path(root) / "7.pdf"
            pdf_path.write_bytes(b"%PDF-test")
            client = httpx.Client(transport=httpx.MockTransport(handler))
            mineru = MinerUClient(token="test", cache_root=Path(root), client=client)
            batch_id, errors = mineru._apply_upload_urls(
                client,
                [MinerUDocument(7, "unused", "title", LONG_ABSTRACT)],
                {7: pdf_path},
            )

            self.assertEqual("batch-1", batch_id)
            self.assertEqual({}, errors)
            self.assertEqual([None], observed_content_type)
            client.close()

    def test_poll_waits_until_done(self):
        """验证 pending 状态继续轮询，done 状态结束。"""
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            """第一次返回 pending，第二次返回 done。"""
            nonlocal calls
            calls += 1
            state = "pending" if calls == 1 else "done"
            return httpx.Response(
                200,
                request=request,
                json={
                    "code": 0,
                    "data": {
                        "extract_result": [{"data_id": "7", "state": state}]
                    },
                },
            )

        clock_values = iter([0.0, 0.0, 1.0])
        client = httpx.Client(transport=httpx.MockTransport(handler))
        mineru = MinerUClient(
            token="test",
            client=client,
            poll_interval=0.0,
            poll_timeout=10.0,
            sleep=lambda _: None,
            monotonic=lambda: next(clock_values),
        )
        result = mineru._poll_batch(client, "batch-1", [7])

        self.assertEqual("done", result[7]["state"])
        self.assertEqual(2, calls)
        client.close()

    def test_downloads_only_full_markdown_and_redacts_manifest(self):
        """验证结果 ZIP 只提取 full.md，manifest 不保存签名 URL 或 Token。"""
        archive = _zip_with_markdown(
            f"# Result Paper Title\n\n## Abstract\n{LONG_ABSTRACT}"
        )

        def handler(request: httpx.Request) -> httpx.Response:
            """返回内存中的 MinerU 结果 ZIP。"""
            return httpx.Response(200, request=request, content=archive)

        with tempfile.TemporaryDirectory() as root:
            document_dir = Path(root) / "7"
            document_dir.mkdir()
            client = httpx.Client(transport=httpx.MockTransport(handler))
            mineru = MinerUClient(token="secret-test", cache_root=Path(root), client=client)
            markdown_path = mineru._download_result(
                client,
                7,
                {
                    "state": "done",
                    "full_zip_url": "https://download.test/signed?secret=value",
                },
                document_dir,
                "batch-1",
            )
            manifest_text = (document_dir / "manifest.json").read_text(encoding="utf-8")

            self.assertTrue(markdown_path.is_file())
            self.assertNotIn("signed", manifest_text)
            self.assertNotIn("secret-test", manifest_text)
            self.assertEqual(7, json.loads(manifest_text)["paper_id"])
            client.close()

    def test_rejects_failed_result(self):
        """验证 MinerU failed 状态被转换为清晰异常。"""
        with tempfile.TemporaryDirectory() as root:
            mineru = MinerUClient(token="test", cache_root=Path(root))
            with self.assertRaisesRegex(MinerUError, "解析失败"):
                mineru._download_result(
                    httpx.Client(),
                    7,
                    {"state": "failed", "err_msg": "page limit"},
                    Path(root),
                    "batch-1",
                )


if __name__ == "__main__":
    unittest.main()
