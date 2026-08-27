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


def _tavily_keys() -> list[str]:
    """支持多 key 分担：TAVILY_API_KEYS(逗号分隔) 优先, 兼容旧 TAVILY_API_KEY。"""
    raw = os.getenv("TAVILY_API_KEYS", "").strip() or os.getenv("TAVILY_API_KEY", "").strip()
    return [k.strip() for k in raw.split(",") if k.strip()]


def _pick_key(month: str, limit: int) -> tuple[str, int]:
    """返回 (key, key_idx)：本月还有额度的 key 里选用得最少的; 全用尽则 ("", -1)。"""
    keys = _tavily_keys()
    with store.connect() as conn:
        used = [store.get_usage(conn, month, "tavily", "search", i) for i in range(len(keys))]
    candidates = [(used[i], i) for i in range(len(keys)) if used[i] < limit]
    if not candidates:
        return "", -1
    _, i = min(candidates)
    return keys[i], i


def fetch_tavily(topic: dict, llm=None) -> list[dict]:
    keys = _tavily_keys()
    if not keys:
        print("[tavily] 未配置 TAVILY_API_KEY(S), 跳过")
        return []

    # 月度额度硬控：每个查询按 key 单独计数, 到上限即停, 绝不超
    limit = _monthly_limit()
    month = datetime.now().strftime("%Y-%m")

    days = topic.get("days", 1)
    max_results = topic.get("max_results", 10)
    tav_topic = topic.get("tavily_topic", "news")   # news / general
    depth = topic.get("search_depth", "basic")      # basic=1点 / advanced=2点
    raw = bool(topic.get("include_raw_content", False))
    cost = 2 if depth == "advanced" else 1
    items: list[dict] = []
    seen = set()

    for q in topic.get("queries", []):
        key, key_idx = _pick_key(month, limit)
        if not key:
            print(f"[tavily] 所有 {len(keys)} 个 key 本月额度均已用尽({limit}/key), 暂停搜索至下月")
            break
        body = {
            "api_key": key,
            "query": q,
            "topic": tav_topic,
            "max_results": max_results,
            "search_depth": depth,
            "include_raw_content": raw,
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

        # 计额度(basic=1 / advanced=2 点) → 记到实际使用的 key_idx
        with store.connect() as conn:
            for _ in range(cost):
                store.incr_usage(conn, month, "tavily", "search", key_idx)

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
                content_full=res.get("raw_content", "") or "",   # advanced 带回的正文
            ))
    return items
