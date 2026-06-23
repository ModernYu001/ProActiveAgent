"""GitHub AI 热点项目采集。

抓"真正的热点"而非"历史最高星"——两类信号：
  ① 近期新创建的高星项目（新锐）。
  ② 已追踪项目的**星标激增**（trending 的本质；按周可重现，不被永久去重）。
靠本地 github_stars 表对比上次星标数来检测激增。
无 token 也能跑(速率较低)；配置 GITHUB_TOKEN 可提高上限。
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import requests

from .. import store
from .base import make_item

SEARCH_API = "https://api.github.com/search/repositories"


def fetch_github_trending(topic: dict, llm=None) -> list[dict]:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    created_days = topic.get("created_within_days", 120)
    surge_min = topic.get("surge_min_stars", 200)
    top_n = topic.get("top_n", 10)
    pool = topic.get("track_pool", 30)            # 每查询追踪多少仓库
    created_since = (datetime.utcnow() - timedelta(days=created_days)).strftime("%Y-%m-%d")
    week = datetime.utcnow().strftime("%Y-W%U")   # 激增条目按周分桶
    new_items, surge_items = [], []
    seen = set()

    for q in topic.get("queries", []):
        try:
            r = requests.get(
                SEARCH_API,
                params={"q": f"{q} pushed:>{created_since}", "sort": "stars",
                        "order": "desc", "per_page": pool},
                headers=headers, timeout=30)
            if r.status_code != 200:
                continue
            repos = r.json().get("items", [])
        except Exception:
            continue

        with store.connect() as conn:
            for repo in repos:
                full = repo.get("full_name", "")
                url = repo.get("html_url", "")
                if not url or full in seen:
                    continue
                seen.add(full)
                stars = repo.get("stargazers_count", 0)
                desc = repo.get("description") or ""
                created = (repo.get("created_at") or "")[:10]
                is_new = created >= created_since
                prev = store.get_repo_stars(conn, full)
                store.set_repo_stars(conn, full, stars)
                delta = (stars - prev) if prev is not None else 0
                meta = f"{desc}\nstars={stars}, +{delta} since last, language={repo.get('language')}, created={created}"

                if prev is None and is_new:                    # ① 首次见到的新锐项目
                    new_items.append(make_item(
                        topic["id"], "GitHub", f"{full} (★{stars}, 新项目)", url, meta, created))
                elif prev is not None and delta >= surge_min:  # ② 星标激增
                    surge_items.append((delta, make_item(
                        topic["id"], "GitHub", f"{full} 🔥 +{delta}★ (现 {stars})", url, meta,
                        created, id_seed=f"{url}#surge-{week}")))

    surge_items.sort(key=lambda x: x[0], reverse=True)         # 涨得猛的优先
    out = [it for _, it in surge_items] + new_items
    return out[:top_n]
