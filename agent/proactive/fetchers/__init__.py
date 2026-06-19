"""采集器：把异构来源标准化成统一的 Item。"""
from .news import fetch_news_rss
from .github_trending import fetch_github_trending
from .tavily_news import fetch_tavily
from .grok_x import fetch_grok_x

FETCHERS = {
    "news_rss": fetch_news_rss,          # Google News RSS (旧, 仍可用)
    "github_trending": fetch_github_trending,
    "tavily": fetch_tavily,              # 主力新闻源
    "grok_x": fetch_grok_x,              # X 补充源 (每天1次)
}


def fetch_topic(topic: dict, llm=None) -> list[dict]:
    fn = FETCHERS.get(topic["type"])
    if not fn:
        return []
    return fn(topic, llm)
