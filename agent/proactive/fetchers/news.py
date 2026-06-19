"""新闻采集：用 Google News RSS（无需密钥、稳健）按关键词查询。

适用于：时政/突发、科技/AI、AI 独角兽 三类话题。
"""
from __future__ import annotations

from urllib.parse import quote_plus

import feedparser

from .base import make_item

GOOGLE_NEWS = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


def fetch_news_rss(topic: dict, llm=None) -> list[dict]:
    items: list[dict] = []
    seen_ids = set()
    per_query = topic.get("per_query", 15)
    for q in topic.get("queries", []):
        url = GOOGLE_NEWS.format(q=quote_plus(q))
        try:
            feed = feedparser.parse(url)
        except Exception:
            continue
        for entry in feed.entries[:per_query]:
            link = entry.get("link", "")
            if not link:
                continue
            source = ""
            if entry.get("source") and isinstance(entry.source, dict):
                source = entry.source.get("title", "")
            item = make_item(
                topic_id=topic["id"],
                source=source or "GoogleNews",
                title=entry.get("title", ""),
                url=link,
                content=entry.get("summary", ""),
                published_at=entry.get("published", ""),
            )
            if item["id"] in seen_ids:
                continue
            seen_ids.add(item["id"])
            items.append(item)
    return items
