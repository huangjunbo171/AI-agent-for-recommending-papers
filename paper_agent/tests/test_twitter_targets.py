import codecs
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.twitter_targets import (
    SensitivePersonFilter, TargetFeedResult, build_target_feed,
    collect_target_posts, parse_profile_articles, parse_target_line, remove_stale_target, utc_time,
)


NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)


def post(days=1, identifier=1, **overrides):
    fields = dict(note_url=f"https://x.com/scholar/status/{identifier}", user_url="https://x.com/scholar",
                  content="A retrieval research question", post_time_ip=(NOW - timedelta(days=days)).isoformat())
    fields.update(overrides)
    return fields


def article(handle="scholar", identifier=1, timestamp=None, context="", quote="", text="Retrieval study"):
    timestamp = timestamp or NOW.isoformat()
    return f'''<article data-testid="tweet"><div data-testid="socialContext">{context}</div>
      <div data-testid="User-Name">{handle}</div>
      <a href="/{handle}/status/{identifier}"><time datetime="{timestamp}"></time></a>
      <div data-testid="tweetText">{text}</div>{quote}</article>'''


class TargetHelpersTest(unittest.TestCase):
    def test_normalizes_list_lines_and_rejects_non_profiles(self):
        self.assertEqual("scholar", parse_target_line("https://twitter.com/Scholar/, Scholar Name")["handle"])
        self.assertEqual("https://x.com/Scholar", parse_target_line("https://twitter.com/Scholar/, Scholar Name")["url"])
        for line in ("Scholar Name", "https://evil.example/scholar", "https://x.com/home", "https://x.com/scholar/status/1"):
            self.assertIsNone(parse_target_line(line))

    def test_sensitive_aliases_have_english_boundaries(self):
        sensitive = SensitivePersonFilter()
        for text in ("https://x.com/ElonMusk", "Donald Trump", "Musk's tweet", "Trump said", "马斯克的观点", "特朗普", "@realDonaldTrump"):
            self.assertTrue(sensitive.blocked(text))
        for text in ("muskrat", "trumpet", "Trumpeter", "retrieval paper"):
            self.assertFalse(sensitive.blocked(text))
        self.assertTrue(sensitive.blocked_post({"quoted_author": "Elon Musk"}))
        self.assertTrue(sensitive.blocked_post({"quoted_content": "Donald Trump spoke"}))
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "blocked.json"
            path.write_text(json.dumps({"handles": ["another"], "names": ["Another Name"]}), encoding="utf-8")
            extended = SensitivePersonFilter(path)
            self.assertTrue(extended.blocked("@another"))
            self.assertTrue(extended.blocked("马斯克"))

    def test_seven_day_boundary_and_timezone(self):
        feed = build_target_feed([post(7, 1), post(7.001, 2), post(-1, 3), post(0, 4)], NOW)
        self.assertEqual([4, 1], [int(p["note_url"].split("/")[-1]) for p in feed.posts])
        self.assertFalse(feed.latest_confirmed)  # 未来时间也不能作为删号依据。
        self.assertIsNone(utc_time("2026-10-24T12:00:00"))
        self.assertEqual(NOW, utc_time("2026-10-24T20:00:00+08:00"))

    def test_pinned_and_reposted_old_posts_do_not_make_account_stale(self):
        html = article(identifier=1, timestamp=(NOW - timedelta(days=200)).isoformat(), context="置顶")
        html += article("other", 2, (NOW - timedelta(days=100)).isoformat(), context="Scholar reposted")
        html += article(identifier=3)
        feed = build_target_feed(parse_profile_articles(html, "scholar"), NOW)
        self.assertTrue(feed.latest_confirmed)
        self.assertEqual(NOW, feed.latest_post_at)
        self.assertEqual(["https://x.com/scholar/status/3"], [p["note_url"] for p in feed.posts])

    def test_quote_uses_outer_time_and_exposes_quoted_content(self):
        quote = '<a href="/other/status/9"><time datetime="2020-01-01T00:00:00Z"></time></a><div data-testid="tweetText">Elon Musk</div>'
        parsed = parse_profile_articles(article(quote=quote), "scholar")
        self.assertEqual(NOW.isoformat(), parsed[0]["post_time_ip"])
        self.assertEqual("Elon Musk", parsed[0]["quoted_content"])

    def test_missing_time_or_pinned_only_never_confirms_latest(self):
        for items in ([{"uncertain": True}, post(90)], [post(90, is_pinned=True)], [], [post(90, post_time_ip="unknown")]):
            self.assertFalse(build_target_feed(items, NOW).latest_confirmed)

    def test_removal_preserves_other_lines_encoding_and_backup(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "targets.txt"
            original = codecs.BOM_UTF8 + b"# comment\r\nhttps://twitter.com/Scholar, Name  \r\nhttps://x.com/other, Other\r\n"
            path.write_bytes(original)
            self.assertTrue(remove_stale_target(path, "scholar"))
            self.assertEqual(codecs.BOM_UTF8 + b"# comment\r\nhttps://x.com/other, Other\r\n", path.read_bytes())
            self.assertEqual(original, next(Path(root).glob("*.bak.*")).read_bytes())
            self.assertFalse(remove_stale_target(path, "scholar"))


class TargetCollectionTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "targets.txt"
        self.log = Mock()
        self.bot = Mock()
        self.bot.get_profile_recent_posts = AsyncMock()
        self.env = patch.dict("os.environ", {"TWITTER_SLEEP_SCALE": "0"})
        self.env.start()
        self.addCleanup(self.env.stop)

    async def test_samples_three_to_five_unique_allowed_accounts(self):
        self.path.write_text("\n".join(f"https://x.com/user{i}, Scholar {i}" for i in range(6)) +
                             "\nhttps://twitter.com/user0, Duplicate\nhttps://x.com/ElonMusk, Elon Musk", encoding="utf-8")
        self.bot.get_profile_recent_posts.return_value = TargetFeedResult([post()], NOW, True, "ok")
        with patch("utils.twitter_targets.random.randint", return_value=4):
            result = await collect_target_posts(1, self.bot, self.path, self.log, now=NOW)
        urls = [call.args[1] for call in self.bot.get_profile_recent_posts.call_args_list]
        self.assertEqual(4, len(set(urls)))
        self.assertFalse(any("elon" in url.lower() for url in urls))
        self.assertEqual(1, len(result))  # 重复帖子URL只处理一次。

    async def test_only_confirmed_latest_older_than_thirty_days_is_removed(self):
        for days, status, confirmed, removed in (
            (31, "ok", True, True), (30, "ok", True, False), (10, "ok", True, False),
            (31, "error", True, False), (31, "ok", False, False), (31, "empty", False, False),
        ):
            with self.subTest(days=days, status=status, confirmed=confirmed):
                self.path.write_text("https://x.com/scholar, Scholar\n", encoding="utf-8")
                self.bot.get_profile_recent_posts.return_value = TargetFeedResult([], NOW - timedelta(days=days), confirmed, status)
                await collect_target_posts(1, self.bot, self.path, self.log, now=NOW)
                self.assertEqual(removed, "scholar" not in self.path.read_text(encoding="utf-8"))

    async def test_rereads_file_before_removal_and_filters_posts(self):
        self.path.write_text("https://x.com/scholar, Scholar\n", encoding="utf-8")

        async def fetch(*args, **kwargs):
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write("https://x.com/newuser, New Scholar\n")
            return TargetFeedResult([], NOW - timedelta(days=31), True, "ok")

        self.bot.get_profile_recent_posts.side_effect = fetch
        await collect_target_posts(1, self.bot, self.path, self.log, now=NOW)
        self.assertEqual("https://x.com/newuser, New Scholar\n", self.path.read_text(encoding="utf-8"))
        self.bot.get_profile_recent_posts.side_effect = None
        self.bot.get_profile_recent_posts.return_value = TargetFeedResult([
            post(content="Donald Trump"), post(8, 2), post(1, 3), post(1, 4, post_time_ip="unknown"),
        ], NOW, True, "ok")
        result = await collect_target_posts(1, self.bot, self.path, self.log, now=NOW)
        self.assertEqual(["https://x.com/scholar/status/3"], [p["note_url"] for p in result])

    async def test_missing_file_and_fetch_failure_leave_list_intact(self):
        self.assertEqual([], await collect_target_posts(1, self.bot, self.path, self.log, now=NOW))
        original = "https://x.com/scholar, Scholar\n"
        self.path.write_text(original, encoding="utf-8")
        self.bot.get_profile_recent_posts.side_effect = RuntimeError("network error")
        self.assertEqual([], await collect_target_posts(1, self.bot, self.path, self.log, now=NOW))
        self.assertEqual(original, self.path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
