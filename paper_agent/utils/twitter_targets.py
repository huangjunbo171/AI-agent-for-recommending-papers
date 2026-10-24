"""大V名单、敏感人物过滤与近期帖子元数据；不依赖浏览器实现。"""

from __future__ import annotations

import asyncio
import codecs
import json
import os
import random
import re
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup


def utc_time(value) -> Optional[datetime]:
    """只接受带时区的明确时间，避免猜测本地时区导致误删。"""
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (TypeError, ValueError):
        return None


def parse_target_line(line):
    parts = line.strip().split(",", 1)
    parsed = urlparse(parts[0].strip())
    handle = parsed.path.strip("/")
    if parsed.scheme.lower() not in {"http", "https"} or (parsed.hostname or "").lower() not in {
        "x.com", "www.x.com", "twitter.com", "www.twitter.com",
    } or not re.fullmatch(r"[A-Za-z0-9_]{1,15}", handle) or handle.lower() in {
        "home", "search", "explore", "settings", "notifications", "messages", "i",
    }:
        return None
    return {"url": f"https://x.com/{handle}", "handle": handle.lower(),
            "name": parts[1].strip() if len(parts) > 1 else ""}


class SensitivePersonFilter:
    """默认黑名单始终生效，可用JSON文件追加handles和names。"""

    def __init__(self, path=None):
        handles = {"elonmusk", "realdonaldtrump"}
        names = {"Elon Musk", "Musk", "Donald Trump", "Donald J. Trump", "Donald J Trump", "Trump", "马斯克", "特朗普", "川普"}
        configured = path or os.environ.get("TWITTER_SENSITIVE_PERSONS_PATH")
        if configured:
            payload = json.loads(Path(configured).read_text(encoding="utf-8-sig"))
            for key in ("handles", "names"):
                if not isinstance(payload.get(key, []), list) or any(not isinstance(v, str) for v in payload.get(key, [])):
                    raise ValueError("敏感人物配置的handles和names必须为字符串列表")
            handles.update(value.lower().lstrip("@") for value in payload.get("handles", []) if value.strip())
            names.update(value.strip() for value in payload.get("names", []) if value.strip())
        self.handles = handles
        aliases = handles | names
        self.patterns = [
            re.compile(re.escape(alias), re.IGNORECASE) if re.search(r"[\u3400-\u9fff]", alias)
            else re.compile(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", re.IGNORECASE)
            for alias in aliases
        ]

    def blocked(self, *values):
        text = "\n".join(str(value or "") for value in values)
        return any(pattern.search(text) for pattern in self.patterns)

    def blocked_post(self, post):
        return self.blocked(*(post.get(key) for key in (
            "content", "quoted_content", "quoted_author", "nickname", "user_url", "note_url", "target_name",
        )))


@dataclass
class TargetFeedResult:
    posts: List[dict] = field(default_factory=list)
    latest_post_at: Optional[datetime] = None
    latest_confirmed: bool = False
    status: str = "unknown"


def parse_profile_articles(html, handle):
    """从主页快照读取本人发帖；引用帖始终使用外层发帖时间。"""
    soup = BeautifulSoup(html, "html.parser")
    results = []
    for article in soup.select('article[data-testid="tweet"]'):
        context = " ".join(node.get_text(" ", strip=True) for node in article.select('[data-testid="socialContext"]'))
        if re.search(r"reposted|retweeted|转帖|轉帖|转推|轉推|转发了|轉發了", context, re.IGNORECASE):
            continue
        if article.select_one('[data-testid="placementTracking"]') or article.find_parent(attrs={"data-testid": "placementTracking"}):
            continue
        # 外层时间链接先于引用卡片；不能用引用卡片较早的时间做删号判断。
        times = article.find_all("time")
        time_node = times[0] if times else None
        anchor = time_node.find_parent("a") if time_node else None
        href = anchor.get("href", "") if anchor else ""
        match = re.search(r"/([A-Za-z0-9_]+)/status/(\d+)(?:[/?#]|$)", href)
        if not match:
            # 有帖子却无法辨认作者/时间时，保留不确定标记，禁止据后面的旧帖删号。
            results.append({"uncertain": True})
            continue
        if match.group(1).lower() != handle.lower():
            continue
        texts = article.select('[data-testid="tweetText"]')
        name = article.select_one('[data-testid="User-Name"]')
        results.append({
            "note_url": f"https://x.com/{match.group(1)}/status/{match.group(2)}",
            "user_url": f"https://x.com/{match.group(1)}",
            "nickname": name.get_text(" ", strip=True) if name else match.group(1),
            "content": texts[0].get_text(" ", strip=True) if texts else "",
            "quoted_content": " ".join(node.get_text(" ", strip=True) for node in texts[1:]),
            "quoted_author": " ".join(node.get_text(" ", strip=True) for node in article.select('[data-testid="User-Name"]')[1:]),
            "post_time_ip": time_node.get("datetime", ""),
            "is_pinned": bool(re.search(r"pinned|置顶|置頂", context, re.IGNORECASE)),
        })
    return results


def build_target_feed(items, now=None, limit=3, days=7):
    now = utc_time(now or datetime.now(timezone.utc))
    eligible = [item for item in items if not item.get("is_pinned")]
    latest = None
    confirmed = bool(eligible)
    posts, seen = [], set()
    for item in eligible:
        published = utc_time(item.get("post_time_ip"))
        if item.get("uncertain") or published is None or published > now:
            confirmed = False
            continue
        latest = max(latest, published) if latest else published
        url = item.get("note_url")
        if now - timedelta(days=days) <= published <= now and url and item.get("content") and url not in seen:
            seen.add(url)
            posts.append(item)
    posts.sort(key=lambda post: utc_time(post["post_time_ip"]), reverse=True)
    return TargetFeedResult(posts[:limit], latest, confirmed and latest is not None, "ok" if items else "empty")


def remove_stale_target(path, handle):
    """重读名单并仅删除对应账号；备份保留BOM、换行与其他行的原始字节。"""
    path = Path(path)
    for _ in range(3):
        stat = path.stat()
        original = path.read_bytes()
        bom = codecs.BOM_UTF8 if original.startswith(codecs.BOM_UTF8) else b""
        lines = original[len(bom):].decode("utf-8").splitlines(keepends=True)
        kept = [line for line in lines if not (parse_target_line(line) and parse_target_line(line)["handle"] == handle.lower())]
        if kept == lines:
            return False
        replacement = bom + "".join(kept).encode("utf-8")
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
            temp_path = Path(temporary.name)
            temporary.write(replacement)
        try:
            # 外部修改发生时重试读取，避免把刚加入名单的其他账号覆盖掉。
            current = path.stat()
            if (stat.st_mtime_ns, stat.st_size) != (current.st_mtime_ns, current.st_size):
                continue
            backup = path.with_name(path.name + f".bak.{datetime.now(timezone.utc):%Y%m%dT%H%M%S}.{uuid.uuid4().hex[:8]}")
            backup.write_bytes(original)
            os.replace(temp_path, path)
            return True
        finally:
            temp_path.unlink(missing_ok=True)
    raise RuntimeError("名单在清理期间持续变动，本次不删除账号")


async def collect_target_posts(account_id, bot, path, log, *, now=None, sensitive=None):
    """每轮实时检查随机3到5个账号，不使用旧缓存作删号依据。"""
    now = utc_time(now or datetime.now(timezone.utc))
    sensitive = sensitive or SensitivePersonFilter()
    path = Path(path)
    if not path.exists():
        log.info(f"大V人物文件不存在：{path}")
        return []
    targets = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        target = parse_target_line(line)
        if not target:
            continue
        if sensitive.blocked(target["url"], target["name"]):
            log.info(f"跳过黑名单账号：{target['url']}")
            continue
        targets.setdefault(target["handle"], target)
    selected = random.sample(list(targets.values()), min(len(targets), random.randint(3, 5)))
    log.info(f"账号{account_id}本轮抽取{len(selected)}个大V：{[target['url'] for target in selected]}")
    posts, seen = [], set()
    for target in selected:
        try:
            scale = max(0.0, float(os.environ.get("TWITTER_SLEEP_SCALE", "1")))
        except ValueError:
            scale = 1.0
        await asyncio.sleep(random.uniform(3, 5) * scale)
        try:
            feed = await bot.get_profile_recent_posts(account_id, target["url"], limit=3, days=7)
            if feed.status != "ok":
                log.info(f"账号{target['url']}抓取状态={feed.status}，跳过且不删号")
                continue
            latest = utc_time(feed.latest_post_at)
            if feed.latest_confirmed and latest is not None and latest < now - timedelta(days=30):
                deleted = remove_stale_target(path, target["handle"])
                log.info(f"账号{target['url']}最新有效帖={latest.isoformat()}，超过30天，删除结果={deleted}")
                continue
            for post in feed.posts:
                post = dict(post, target_name=target["name"])
                published = utc_time(post.get("post_time_ip"))
                if not published or not now - timedelta(days=7) <= published <= now:
                    continue
                if sensitive.blocked_post(post):
                    log.info(f"跳过涉及黑名单人物的帖子：{post.get('note_url')}")
                    continue
                if post.get("note_url") and post.get("content") and post["note_url"] not in seen:
                    seen.add(post["note_url"])
                    posts.append(post)
            log.info(f"账号{target['url']}一周内获取{len(feed.posts)}条候选帖")
        except Exception as error:
            log.warning(f"账号{target['url']}抓取或清理失败，跳过且不继续删除：{error}")
    return posts
