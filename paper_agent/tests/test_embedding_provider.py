import math
import sys
import unittest
from pathlib import Path

import httpx


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.embedding_provider import (  # noqa: E402
    DashScopeEmbedder,
    EmbeddingAuthenticationError,
    EmbeddingError,
)


def _vector(value: float) -> list[float]:
    """构造测试用的 1024 维向量。"""
    return [value] * 1024


class DashScopeEmbedderTest(unittest.TestCase):
    """验证 DashScope 批量顺序、限制、重试与向量校验。"""

    def test_restores_response_order_and_normalizes(self):
        """验证乱序响应能按 index 复原并完成 L2 归一化。"""
        def handler(request: httpx.Request) -> httpx.Response:
            """返回顺序与输入相反的模拟响应。"""
            return httpx.Response(
                200,
                request=request,
                json={
                    "data": [
                        {"index": 1, "embedding": _vector(2.0)},
                        {"index": 0, "embedding": [1.0] + [0.0] * 1023},
                    ]
                },
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        embedder = DashScopeEmbedder(api_key="test", client=client)
        vectors = embedder.encode(["first", "second"])

        self.assertEqual(1.0, vectors[0][0])
        self.assertAlmostEqual(1.0, math.sqrt(sum(v * v for v in vectors[1])))
        client.close()

    def test_splits_more_than_ten_inputs(self):
        """验证超过十条输入时自动拆分且单批不超过服务限制。"""
        batch_sizes: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            """记录请求批量并返回同序测试向量。"""
            payload = __import__("json").loads(request.content)
            batch_sizes.append(len(payload["input"]))
            return httpx.Response(
                200,
                request=request,
                json={
                    "data": [
                        {"index": index, "embedding": [1.0] + [0.0] * 1023}
                        for index in range(len(payload["input"]))
                    ]
                },
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        vectors = DashScopeEmbedder(api_key="test", client=client).encode(
            [f"text-{index}" for index in range(11)]
        )

        self.assertEqual([10, 1], batch_sizes)
        self.assertEqual(11, len(vectors))
        client.close()

    def test_retries_rate_limit(self):
        """验证 429 会指数退避并最多重试三次。"""
        calls = 0
        waits: list[float] = []

        def handler(request: httpx.Request) -> httpx.Response:
            """前两次返回 429，第三次返回成功。"""
            nonlocal calls
            calls += 1
            if calls < 3:
                return httpx.Response(429, request=request)
            return httpx.Response(
                200,
                request=request,
                json={"data": [{"index": 0, "embedding": _vector(1.0)}]},
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        embedder = DashScopeEmbedder(
            api_key="test", client=client, sleep=waits.append
        )
        self.assertEqual(1, len(embedder.encode(["hello"])))
        self.assertEqual([1.0, 2.0], waits)
        client.close()

    def test_rejects_invalid_dimension(self):
        """验证服务返回非 1024 维向量时立即拒绝。"""
        def handler(request: httpx.Request) -> httpx.Response:
            """返回错误维度的模拟向量。"""
            return httpx.Response(
                200,
                request=request,
                json={"data": [{"index": 0, "embedding": [1.0]}]},
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        with self.assertRaisesRegex(EmbeddingError, "1024"):
            DashScopeEmbedder(api_key="test", client=client).encode(["hello"])
        client.close()

    def test_authentication_failure_does_not_retry(self):
        """验证 401 立即失败且不会重试。"""
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            """始终返回认证失败。"""
            nonlocal calls
            calls += 1
            return httpx.Response(401, request=request)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        with self.assertRaises(EmbeddingAuthenticationError):
            DashScopeEmbedder(api_key="test", client=client).encode(["hello"])
        self.assertEqual(1, calls)
        client.close()


if __name__ == "__main__":
    unittest.main()
