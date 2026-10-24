"""串行 Twitter 论文模式使用的、可独立测试的帖子驱动 RAG 服务。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from paper_agent.prompts_test import (
    rag_reply_system_prompt, rag_rewrite_system_prompt,
    rag_selection_system_prompt, rag_strategy_system_prompt,
)
from utils.embedding_provider import create_embedder
from utils.generation import general_generation
from utils.lancedb_store import LanceDBPaperStore
from utils.mysql_paper_repository import MySQLPaperRepository


RECOMMENDATION_STRATEGIES = {"直接推荐", "互动+推荐", "推荐相关领域论文"}


@dataclass
class Recommendation:
    """保存最终通过校验的策略、论文证据和完整待发布内容。"""

    strategy: str
    papers: List[Dict[str, Any]] = field(default_factory=list)
    content: str = ""


def _positive_setting(name: str, default: int, maximum: Optional[int] = None) -> int:
    value = int(os.environ.get(name, str(default)))
    if value < 1 or (maximum is not None and value > maximum):
        raise ValueError(f"{name} 必须在1到{maximum or '正整数上限'}之间")
    return value


def _valid_url(value: str) -> bool:
    parsed = urlparse(value or "")
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and not re.search(r"\s", value)


class PostRecommendationService:
    def __init__(self, embedder=None, store=None, repository=None, generate=None,
                 top_k=None, max_papers=None, log=None):
        self.embedder = embedder
        self.store = store
        self.repository = repository
        self.generate = generate or general_generation
        self.top_k = top_k if top_k is not None else _positive_setting("TWITTER_RAG_TOP_K", 5)
        self.max_papers = max_papers if max_papers is not None else _positive_setting("TWITTER_RAG_MAX_PAPERS", 3, 3)
        if not isinstance(self.top_k, int) or isinstance(self.top_k, bool) or self.top_k < 1:
            raise ValueError("top_k 必须为正整数")
        if not isinstance(self.max_papers, int) or isinstance(self.max_papers, bool) or not 1 <= self.max_papers <= 3:
            raise ValueError("max_papers 必须在1到3之间")
        self.log = log or logging.getLogger(__name__)

    async def _ask(self, prompt, payload):
        # 显式指定 provider，避免全局 LLM_PROVIDER 把新链路切到其他模型。
        return await self.generate([
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ], provider="deepseek")

    @staticmethod
    def _candidate(paper):
        if not paper.title or not paper.analysis or not _valid_url(paper.paper_url):
            return None
        facts = []
        for name in ("core_method", "main_contributions", "main_results", "limitations", "research_topics", "datasets"):
            value = paper.analysis.get(name)
            values = value if isinstance(value, list) else [value]
            for text in values:
                if isinstance(text, str) and text.strip():
                    facts.append({"index": len(facts), "field": name, "text": text.strip()})
        if not facts:
            return None
        return {"paper_id": paper.paper_id, "title": paper.title, "authors": paper.authors,
                "abstract": paper.abstract, "paper_url": paper.paper_url, "facts": facts}

    def _retrieve(self, text):
        # 直到推荐分支才初始化外部依赖；只互动不需要向量服务或论文数据库。
        if self.embedder is None:
            self.embedder = create_embedder(
                os.environ.get("TWITTER_RAG_EMBEDDING_PROVIDER", "dashscope"),
                os.environ.get("TWITTER_RAG_EMBEDDING_MODEL") or None,
            )
        if self.store is None:
            self.store = LanceDBPaperStore()
        if self.repository is None:
            self.repository = MySQLPaperRepository()
        vector = self.embedder.encode([text])[0]
        hits = self.store.search(vector, self.top_k, self.embedder.model_name)
        ids = list(dict.fromkeys(hit["paper_id"] for hit in hits))
        self.log.info(f"RAG召回论文ID：{ids}")
        papers = {paper.paper_id: paper for paper in self.repository.load_by_ids(ids)}
        candidates = []
        for paper_id in ids:
            candidate = self._candidate(papers[paper_id]) if paper_id in papers else None
            if candidate:
                candidates.append(candidate)
        return candidates

    def _validate_selection(self, response, candidates):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(response or "").strip(), flags=re.IGNORECASE)
        selection = json.loads(text)["papers"]
        if not isinstance(selection, list):
            raise ValueError("筛选结果papers必须为列表")
        by_id = {paper["paper_id"]: paper for paper in candidates}
        selected, seen = [], set()
        for item in selection:
            paper_id = item.get("paper_id")
            if type(paper_id) is not int or paper_id not in by_id:
                raise ValueError("筛选结果包含非候选论文ID")
            if paper_id in seen:
                continue
            candidate = by_id[paper_id]
            indices = item.get("evidence_indices")
            if not isinstance(indices, list) or not indices or any(
                type(index) is not int or not 0 <= index < len(candidate["facts"]) for index in indices
            ):
                raise ValueError("筛选结果包含无效信息点编号")
            seen.add(paper_id)
            selected.append({
                "paper_id": paper_id, "title": candidate["title"],
                "authors": candidate["authors"], "paper_url": candidate["paper_url"],
                "facts": [candidate["facts"][index] for index in dict.fromkeys(indices)],
            })
        return selected[:self.max_papers]

    @staticmethod
    def _valid_body(body, papers, budget):
        if not body or len(body) > budget or re.search(r"https?://|www\.", body, re.IGNORECASE):
            return False
        citations = set(re.findall(r"\[(\d+)\]", body))
        return citations == {str(index) for index in range(1, len(papers) + 1)}

    async def _compose(self, post, character, strategy, papers, max_length):
        papers = list(papers)
        while True:
            suffix = " ".join(f"[{index}] {paper['paper_url']}" for index, paper in enumerate(papers, 1))
            budget = max_length - len(suffix) - (1 if suffix else 0)
            if budget >= 60 or not papers:
                payload = {"post": post, "papers": papers}
                draft = await self._ask(rag_reply_system_prompt(character, strategy, budget, len(papers)), payload)
                if not draft:
                    return None
                payload["draft"] = draft
                body = await self._ask(rag_rewrite_system_prompt(character, strategy, budget, len(papers)), payload)
                body = str(body or "").strip()
                if self._valid_body(body, papers, budget):
                    return Recommendation(strategy, papers, f"{body} {suffix}".strip())
            # 不能靠截断正文保留三个无对应说明的链接，减少末位论文后重新写。
            if len(papers) <= 1:
                self.log.info("回复为空、引用不匹配或超长，跳过该帖子")
                return None
            papers.pop()

    async def recommend(self, post, character, domain=None, max_length=270):
        text = post.get("content") or ""
        if not text.strip():
            return None
        try:
            raw = await self._ask(rag_strategy_system_prompt(), {"post": post, "persona": character, "domain": domain})
            strategy = str(raw or "").strip().strip('"“”')
            if strategy == "跳过":
                return None
            if strategy not in RECOMMENDATION_STRATEGIES | {"只互动"}:
                self.log.info("策略输出不规范，降级为只互动")
                strategy = "只互动"
            papers = []
            if strategy in RECOMMENDATION_STRATEGIES:
                try:
                    candidates = await asyncio.to_thread(self._retrieve, text)
                    if candidates:
                        response = await self._ask(rag_selection_system_prompt(self.max_papers), {
                            "post": post, "persona": character, "strategy": strategy, "candidates": candidates,
                        })
                        papers = self._validate_selection(response, candidates)
                    if not papers:
                        self.log.info("没有合适论文，降级为只互动")
                        strategy = "只互动"
                except Exception as error:
                    self.log.warning(f"论文检索或筛选失败，降级为只互动：{error}")
                    strategy = "只互动"
            result = await self._compose(post, character, strategy, papers, max_length)
            if result:
                self.log.info(f"最终策略={result.strategy}，论文ID={[paper['paper_id'] for paper in result.papers]}")
            return result
        except Exception as error:
            self.log.warning(f"互动内容生成失败，跳过：{error}")
            return None
