"""Tavily 搜索采集器（主力新闻源）。

Tavily 是面向 LLM 的搜索 API：返回带正文摘要、真实链接、相关度分、发布时间，
比 Google News RSS 质量高。用于时政/科技AI/AI独角兽三类话题的高频抓取。
"""
from __future__ import annotations

import os
from datetime import datetime
from urllib.parse import urlparse

import requests

from .. import store
from .base import make_item

TAVILY_URL = "https://api.tavily.com/search"


def _monthly_limit() -> int:
    credits = float(os.getenv("TAVILY_MONTHLY_CREDITS", "1000"))
    ratio = float(os.getenv("TAVILY_BUDGET_RATIO", "0.8"))
    return int(credits * ratio)


def fetch_tavily(topic: dict, llm=None) -> list[dict]:
    key = os.getenv("TAVILY_API_KEY", "").strip()
    if not key:
        print("[tavily] 未配置 TAVILY_API_KEY, 跳过")
        return []

    # 月度额度硬控：每个搜索查询 = 1 点, 到 80% 上限即停, 绝不超
    limit = _monthly_limit()
    month = datetime.now().strftime("%Y-%m")
    with store.connect() as conn:
        used = store.get_usage(conn, month, "tavily", "search", 0)

    days = topic.get("days", 1)
    max_results = topic.get("max_results", 10)
    tav_topic = topic.get("tavily_topic", "news")   # news / general
    items: list[dict] = []
    seen = set()

    for q in topic.get("queries", []):
        if used >= limit:
            print(f"[tavily] 本月额度已达 {used}/{limit}(80%上限), 暂停搜索至下月")
            break
        body = {
            "api_key": key,
            "query": q,
            "topic": tav_topic,
            "max_results": max_results,
            "search_depth": "basic",
            "include_answer": False,
        }
        if tav_topic == "news":
            body["days"] = days
        try:
            r = requests.post(TAVILY_URL, json=body, timeout=30)
            if r.status_code != 200:
                print(f"[tavily] HTTP {r.status_code}: {r.text[:150]}")
                continue
            results = r.json().get("results", [])
        except Exception as e:  # noqa: BLE001
            print(f"[tavily] 请求失败: {e}")
            continue

        # 计一次额度(成功调用即消耗 1 点)
        used += 1
        with store.connect() as conn:
            store.incr_usage(conn, month, "tavily", "search", 0)

        for res in results:
            url = res.get("url", "")
            if not url or url in seen:
                continue
            seen.add(url)
            src = urlparse(url).netloc.replace("www.", "") or "Tavily"
            items.append(make_item(
                topic_id=topic["id"],
                source=src,
                title=res.get("title", ""),
                url=url,
                content=res.get("content", ""),
                published_at=res.get("published_date", "") or "",
            ))
    return items
