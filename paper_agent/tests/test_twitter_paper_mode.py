import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from twitter_agent import twitter_agent_serial as serial
from utils.paper_recommender import Recommendation


def response(message="success", status=200):
    return SimpleNamespace(status_code=status, body=json.dumps({"code": str(status), "message": message}).encode())


class TwitterPaperModeTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # 绕过构造器，所有浏览器、数据库和模型依赖都以替身注入。
        self.agent = serial.TwitterAgent.__new__(serial.TwitterAgent)
        self.agent.log = Mock()
        self.agent.database = Mock()
        self.agent.database.get_dict_data_sql.return_value = []
        self.agent.paper_agent = SimpleNamespace(max_length=270, action_limits={"点赞": 10, "评论": 10, "转发": 10})
        self.agent.recommendation_service = SimpleNamespace(recommend=AsyncMock(return_value=Recommendation("只互动", [], "How was this evaluated?")))
        self.agent._sleep_for_phase = AsyncMock()
        self.agent._publish_proactive_paper_post = AsyncMock(return_value=False)
        self.bot = SimpleNamespace(likes=AsyncMock(return_value=response()), comments=AsyncMock(return_value=response()),
                                   transmits=AsyncMock(return_value=response()), get_one_keyword_content=AsyncMock())
        self.post = {"note_url": "https://x.com/scholar/status/123", "content": "A retrieval question",
                     "post_time_ip": datetime.now(timezone.utc).isoformat()}
        self.state = self.agent._new_proactive_post_state(post_first=True)
        self.state["attempted"] = True

    async def evaluate(self):
        return await self.agent._evaluate_and_dispatch_paper_interaction(
            self.bot, 1, "Researcher", self.state, self.post, self.state["action_counts"], "大V", domain="AI",
        )

    async def test_success_counts_once_and_repeat_skips(self):
        with patch.object(serial.random, "choice", return_value="评论"):
            performed, _, result = await self.evaluate()
            repeated, _, _ = await self.evaluate()
        self.assertTrue(performed)
        self.assertFalse(repeated)
        self.assertEqual("只互动", result["strategy"])
        self.assertEqual(1, self.state["interaction_count"])
        self.assertEqual(1, self.state["action_counts"]["评论"])
        self.bot.comments.assert_awaited_once()
        self.agent._publish_proactive_paper_post.assert_not_awaited()

    async def test_failed_exception_already_done_and_history_do_not_count(self):
        for result in (response(status=400), response("already_done"), None):
            self.bot.likes.return_value = result
            with patch.object(serial.random, "choice", return_value="点赞"):
                self.assertFalse((await self.evaluate())[0])
        self.bot.likes.side_effect = RuntimeError("browser error")
        with patch.object(serial.random, "choice", return_value="点赞"):
            self.assertFalse((await self.evaluate())[0])
        self.agent.database.get_dict_data_sql.return_value = [{"1": 1}]
        self.assertFalse((await self.evaluate())[0])
        self.assertEqual(0, self.state["interaction_count"])
        self.assertTrue(all(value == 0 for value in self.state["action_counts"].values()))

    async def test_sensitive_old_or_unknown_posts_never_reach_model(self):
        for overrides in ({"content": "Donald Trump"}, {"quoted_content": "Elon Musk"},
                          {"post_time_ip": "2020-01-01T00:00:00Z"}, {"post_time_ip": "unknown"}):
            original = dict(self.post)
            self.post.update(overrides)
            self.assertFalse((await self.evaluate())[0])
            self.post = original
        self.agent.recommendation_service.recommend.assert_not_awaited()

    async def test_recommendation_uses_supplied_content_and_obeys_action_quota(self):
        self.agent.recommendation_service.recommend.return_value = Recommendation("直接推荐", [{"paper_id": 7}], "Evidence [1]. https://arxiv.org/abs/2610.00007")
        self.state["action_counts"]["评论"] = 10
        performed, _, result = await self.evaluate()
        self.assertTrue(performed)
        self.assertEqual([7], result["paper_ids"])
        self.bot.transmits.assert_awaited_once()
        self.assertIn("2610.00007", self.bot.transmits.call_args.kwargs["content"])
        self.bot.likes.assert_not_awaited()

    async def test_interaction_target_stops_without_fixed_diary_paper(self):
        self.state["interaction_target"] = 1
        with patch.object(serial.random, "choice", return_value="评论"):
            results = await self.agent._interact_with_paper_target_posts(
                self.bot, 1, "Researcher", [self.post, dict(self.post, note_url="https://x.com/scholar/status/124")], self.state,
            )
        self.assertEqual(1, len(results))
        self.assertIsNone(self.state["paper_info"])

    async def test_full_paper_cycle_posts_diary_once_and_never_searches_keywords(self):
        planner = Mock()
        planner.fomat_action_time.return_value = {"00:00": [1]}
        planner.get_interested_information_for_account = AsyncMock(return_value=([], []))
        planner.get_paper_target_information = AsyncMock(return_value=[self.post])
        planner.get_topics_information = AsyncMock()
        planner.get_target_information = AsyncMock()
        self.agent.database.get_dict_data_sql.side_effect = lambda sql: [{"Prediction_Action_Time": None}] if "accounts_info" in sql else []
        self.agent.get_action_time = AsyncMock(return_value={})
        self.agent.get_account_character = AsyncMock(return_value="Researcher")
        self.agent._interact_with_related_paper_posts = AsyncMock()
        self.bot.login_by_cookies = AsyncMock()
        self.bot.get_user_profile = AsyncMock()
        self.bot.scroll = Mock()
        self.bot.driver = SimpleNamespace(driver=SimpleNamespace(quit=Mock()))
        with patch.object(serial, "TwitterPlanner", return_value=planner), patch.object(serial, "TwitterBot", return_value=self.bot), \
             patch.object(serial.time, "sleep"), patch.object(serial.random, "choice", return_value="评论"), \
             patch.dict("os.environ", {"FORCE_RUN_NOW": "0"}):
            await self.agent.auto_cultivation([1], paper_mode=True, force_run_now=True,
                                            max_cycles=1, topic_path="missing-topic-file.json")
        self.agent._publish_proactive_paper_post.assert_awaited_once()
        planner.get_paper_target_information.assert_awaited_once()
        planner.get_target_information.assert_not_awaited()
        planner.get_topics_information.assert_not_awaited()
        self.agent._interact_with_related_paper_posts.assert_not_awaited()
        self.bot.get_one_keyword_content.assert_not_awaited()
        self.bot.comments.assert_awaited_once()

    async def test_diary_exception_does_not_block_rag_cycle(self):
        self.agent._publish_proactive_paper_post.side_effect = RuntimeError("diary model unavailable")
        await self.test_full_paper_cycle_posts_diary_once_and_never_searches_keywords()

    async def test_bot_retains_latest_old_post_metadata_for_pruning(self):
        """浏览器传输层不能把过期帖子和发帖时间一同丢弃。"""
        bot = serial.TwitterBot.__new__(serial.TwitterBot)
        bot.log = Mock()
        bot._ensure_live_driver = AsyncMock()
        bot._has_logged_in_ui = Mock(return_value=True)
        bot.driver = Mock()
        bot.driver.driver.current_url = "https://x.com/scholar"
        bot.driver.driver.page_source = '''<article data-testid="tweet">
            <a href="/scholar/status/123"><time datetime="2020-01-01T00:00:00Z"></time></a>
            <div data-testid="tweetText">Old research update</div></article>'''
        feed = await bot.get_profile_recent_posts(1, "https://x.com/scholar")
        self.assertEqual("ok", feed.status)
        self.assertEqual([], feed.posts)
        self.assertTrue(feed.latest_confirmed)
        self.assertEqual(2020, feed.latest_post_at.year)


if __name__ == "__main__":
    unittest.main()
