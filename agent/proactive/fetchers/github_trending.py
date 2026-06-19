"""GitHub AI Agent 热点项目采集。

用 GitHub Search API 找近期高星 / 快速涨星的 agent 相关仓库。
无 token 也能跑(速率较低)；配置 GITHUB_TOKEN 可提高上限。
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import requests

from .base import make_item

SEARCH_API = "https://api.github.com/search/repositories"


def fetch_github_trending(topic: dict, llm=None) -> list[dict]:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # 近 180 天有更新、按星标排序，逼近"当前热点"
    pushed_since = (datetime.utcnow() - timedelta(days=180)).strftime("%Y-%m-%d")
    top_n = topic.get("top_n", 10)
    items: list[dict] = []
    seen = set()

    for q in topic.get("queries", []):
        query = f"{q} pushed:>{pushed_since}"
        try:
            r = requests.get(
                SEARCH_API,
                params={"q": query, "sort": "stars", "order": "desc", "per_page": top_n},
                headers=headers,
                timeout=30,
            )
            if r.status_code != 200:
                continue
            repos = r.json().get("items", [])
        except Exception:
            continue

        for repo in repos:
            url = repo.get("html_url", "")
            if not url or url in seen:
                continue
            seen.add(url)
            stars = repo.get("stargazers_count", 0)
            desc = repo.get("description") or ""
            item = make_item(
                topic_id=topic["id"],
                source="GitHub",
                title=f"{repo.get('full_name')} (★{stars})",
                url=url,
                content=f"{desc}\nstars={stars}, language={repo.get('language')}, "
                        f"updated={repo.get('pushed_at')}",
                published_at=repo.get("created_at", ""),
            )
            items.append(item)

    # 全局按星标粗排，截断 top_n
    items.sort(key=lambda x: _stars(x), reverse=True)
    return items[: top_n]


def _stars(item: dict) -> int:
    try:
        return int(item["content"].split("stars=")[1].split(",")[0])
    except (IndexError, ValueError):
        return 0
