"""提供 DashScope 与本地 BGE-M3 两种论文向量生成实现。"""

from __future__ import annotations

import math
import os
import time
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VECTOR_DIMENSION = 1024
DASHSCOPE_BATCH_SIZE = 10
DEFAULT_DASHSCOPE_MODEL = "text-embedding-v4"
DEFAULT_BGE_MODEL = "BAAI/bge-m3"


class EmbeddingError(RuntimeError):
    """向量服务返回无效结果或请求最终失败时抛出。"""


class EmbeddingAuthenticationError(EmbeddingError):
    """向量服务拒绝当前认证信息时抛出。"""


def normalize_vector(values: Sequence[float]) -> List[float]:
    """校验向量并执行 L2 归一化。

    参数:
        values: 待校验的原始向量。

    返回:
        归一化后的 1024 维浮点向量。

    异常:
        EmbeddingError: 向量维度错误、包含非有限值或范数为零。
    """
    if len(values) != VECTOR_DIMENSION:
        raise EmbeddingError(
            f"向量维度必须为 {VECTOR_DIMENSION}，实际为 {len(values)}"
        )
    try:
        vector = [float(value) for value in values]
    except (TypeError, ValueError) as exc:
        raise EmbeddingError("向量包含不能转换为浮点数的值") from exc
    if any(not math.isfinite(value) for value in vector):
        raise EmbeddingError("向量包含 NaN 或无穷值")
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0.0:
        raise EmbeddingError("向量范数必须大于零")
    return [value / norm for value in vector]


class DashScopeEmbedder:
    """通过 OpenAI 兼容接口批量调用 DashScope 文本向量模型。"""

    def __init__(
        self,
        model_name: str = DEFAULT_DASHSCOPE_MODEL,
        endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
        client: Optional[httpx.Client] = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """初始化 DashScope 向量客户端。

        参数:
            model_name: DashScope 模型名称。
            endpoint: OpenAI 兼容 embeddings 接口；为空时读取环境变量。
            api_key: API 密钥；为空时读取 ``DASHSCOPE_API_KEY``。
            client: 可选的 httpx 客户端，主要用于连接复用和测试注入。
            sleep: 重试等待函数，测试时可替换。

        异常:
            EmbeddingError: 未配置 API 密钥。
        """
        self.model_name = model_name
        self.endpoint = (
            endpoint
            or os.environ.get("DASHSCOPE_EMBEDDING_URL")
            or "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
        )
        self.api_key = api_key or os.environ.get("DASHSCOPE_API_KEY", "")
        if not self.api_key:
            raise EmbeddingError("DASHSCOPE_API_KEY 不能为空")
        self._client = client
        self._sleep = sleep

    def _request_batch(
        self, client: httpx.Client, texts: Sequence[str]
    ) -> List[List[float]]:
        """请求一批最多 10 条文本并按响应 index 恢复顺序。

        参数:
            client: 已初始化的 httpx 客户端。
            texts: 本批待向量化文本。

        返回:
            与输入顺序一致的归一化向量列表。

        异常:
            EmbeddingAuthenticationError: API 密钥无效。
            EmbeddingError: 请求失败或响应结构不符合约定。
        """
        payload = {
            "model": self.model_name,
            "input": list(texts),
            "dimensions": VECTOR_DIMENSION,
            "encoding_format": "float",
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        last_error: Optional[BaseException] = None
        for attempt in range(3):
            try:
                response = client.post(self.endpoint, headers=headers, json=payload)
                if response.status_code in (401, 403):
                    raise EmbeddingAuthenticationError("DashScope 认证失败")
                if response.status_code == 429 or response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        "DashScope 暂时不可用",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, dict):
                    raise EmbeddingError("DashScope 响应必须是 JSON 对象")
                items = body.get("data")
                if not isinstance(items, list) or len(items) != len(texts):
                    raise EmbeddingError("DashScope 返回的向量数量与输入不一致")
                ordered: List[Optional[List[float]]] = [None] * len(texts)
                for item in items:
                    if not isinstance(item, dict):
                        raise EmbeddingError("DashScope data 元素必须是对象")
                    index = item.get("index")
                    embedding = item.get("embedding")
                    if not isinstance(index, int) or not 0 <= index < len(texts):
                        raise EmbeddingError("DashScope 返回了非法 index")
                    if not isinstance(embedding, list) or ordered[index] is not None:
                        raise EmbeddingError("DashScope 返回了非法或重复向量")
                    ordered[index] = normalize_vector(embedding)
                if any(vector is None for vector in ordered):
                    raise EmbeddingError("DashScope 响应缺少部分向量")
                return [vector for vector in ordered if vector is not None]
            except EmbeddingAuthenticationError:
                raise
            except EmbeddingError:
                raise
            except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
                last_error = exc
                if attempt < 2:
                    self._sleep(float(2 ** attempt))
        raise EmbeddingError(f"DashScope 请求重试 3 次后仍失败：{last_error}")

    def encode(self, texts: Sequence[str]) -> List[List[float]]:
        """按每批最多 10 条文本生成 1024 维向量。

        参数:
            texts: 待向量化的非空文本序列。

        返回:
            与输入顺序一致的归一化向量列表。

        异常:
            EmbeddingError: 输入为空、包含空文本或请求失败。
        """
        normalized_texts = [str(text).strip() for text in texts]
        if not normalized_texts or any(not text for text in normalized_texts):
            raise EmbeddingError("向量化文本不能为空")

        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=30.0, follow_redirects=True)
        try:
            vectors: List[List[float]] = []
            for start in range(0, len(normalized_texts), DASHSCOPE_BATCH_SIZE):
                batch = normalized_texts[start : start + DASHSCOPE_BATCH_SIZE]
                vectors.extend(self._request_batch(client, batch))
            return vectors
        finally:
            if owns_client:
                client.close()


class BGEEmbedder:
    """加载 D 盘本地 BGE-M3，并生成 1024 维归一化向量。"""

    def __init__(self, model_name: str = DEFAULT_BGE_MODEL) -> None:
        """优先读取项目本地模型，不存在时使用模型名称下载。

        参数:
            model_name: Hugging Face 模型名称或兼容标识。

        异常:
            EmbeddingError: 缺少 sentence-transformers 依赖。
        """
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise EmbeddingError(
                "使用本地 BGE-M3 前请安装 sentence-transformers"
            ) from exc

        configured_path = os.environ.get("EMBEDDING_MODEL_PATH", "").strip()
        cache_dir = PROJECT_ROOT / "papers" / "lancedb" / "models"
        cache_dir.mkdir(parents=True, exist_ok=True)
        default_local_path = cache_dir / "bge-m3"
        if configured_path:
            model_ref = configured_path
            kwargs: dict[str, Any] = {}
            self.model_name = Path(configured_path).name
        elif (default_local_path / "config.json").exists() and (
            default_local_path / "pytorch_model.bin"
        ).exists():
            model_ref = str(default_local_path)
            kwargs = {}
            self.model_name = model_name
        else:
            model_ref = model_name
            kwargs = {"cache_folder": str(cache_dir)}
            self.model_name = model_name
        self.model = SentenceTransformer(model_ref, **kwargs)

    def encode(self, texts: Sequence[str]) -> List[List[float]]:
        """批量生成并校验 BGE-M3 向量。

        参数:
            texts: 待向量化文本序列。

        返回:
            与输入顺序一致的 1024 维归一化向量。

        异常:
            EmbeddingError: 输入为空或模型返回的向量结构不正确。
        """
        normalized_texts = [str(text).strip() for text in texts]
        if not normalized_texts or any(not text for text in normalized_texts):
            raise EmbeddingError("向量化文本不能为空")
        embeddings = self.model.encode(
            normalized_texts, normalize_embeddings=True, convert_to_numpy=True
        )
        if len(embeddings.shape) != 2 or embeddings.shape[1] != VECTOR_DIMENSION:
            raise EmbeddingError(
                f"向量维度必须为 {VECTOR_DIMENSION}，实际为 {tuple(embeddings.shape)}"
            )
        return [normalize_vector(row.tolist()) for row in embeddings]


def create_embedder(provider: str, model_name: Optional[str] = None) -> Any:
    """根据命令行配置创建向量生成器。

    参数:
        provider: ``dashscope`` 或 ``bge``。
        model_name: 可选模型名；为空时使用对应 Provider 默认值。

    返回:
        实现 ``encode`` 方法并包含 ``model_name`` 属性的向量生成器。

    异常:
        EmbeddingError: Provider 名称不受支持。
    """
    normalized = provider.strip().lower()
    if normalized == "dashscope":
        return DashScopeEmbedder(model_name or DEFAULT_DASHSCOPE_MODEL)
    if normalized == "bge":
        return BGEEmbedder(model_name or DEFAULT_BGE_MODEL)
    raise EmbeddingError(f"不支持的 embedding provider：{provider}")
