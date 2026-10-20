"""Reddit 采集器（首选原生 JSON / OAuth API，支持 RSS 与 Tavily 智能兜底）。

覆盖领域：
- 热门 / 全球时事突发 (r/worldnews, r/news, r/technology)
- AI 行业重磅 (r/LocalLLaMA, r/Singularity, r/ArtificialInteligence, r/ClaudeAI, r/ChatGPT)
- AI 独角兽与投融资 (r/startups, r/venturecapital, r/YCombinator)
- 🎁 AI 羊毛与福利 (免费 API 额度、赠金、兑换码、免费等级优惠)
"""
from __future__ import annotations

import html
import os
import random
import re
import xml.etree.ElementTree as ET
from datetime import datetime

import requests
from dotenv import load_dotenv

from .. import store
from .base import make_item

load_dotenv()

REDDIT_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 (ProActive-Agent/1.0)",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 (ProActive/1.0)",
    "ProActive-Topic-Monitor/1.0 (Autonomous Agent by u/modern_agent)",
]


def _clean_html_text(raw_html: str) -> str:
    """去除 HTML 标签，保留纯文本并反转义。"""
    if not raw_html:
        return ""
    text = re.sub(r"<[^<]+?>", " ", html.unescape(raw_html))
    return " ".join(text.split())


def _parse_reddit_json_children(children: list[dict], subreddits: list[str]) -> list[dict]:
    """解析 Reddit 标准 JSON 结构的帖子列表。"""
    results: list[dict] = []
    for c in children:
        data = c.get("data", {})
        title = data.get("title", "").strip()
        permalink = data.get("permalink", "")
        link = f"https://www.reddit.com{permalink}" if permalink else data.get("url", "")
        selftext = data.get("selftext", "").strip()
        created_utc = data.get("created_utc", 0)
        published_at = datetime.utcfromtimestamp(created_utc).isoformat() + "Z" if created_utc else ""
        sub_name = data.get("subreddit", "") or (subreddits[0] if subreddits else "reddit")
        score = data.get("score", 0)
        comments = data.get("num_comments", 0)

        # 构造丰富摘要
        summary = selftext[:400] if selftext else f"Upvotes: {score} | Comments: {comments}"

        if title and link:
            results.append({
                "title": title,
                "url": link,
                "content": summary,
                "content_full": selftext[:4000] if selftext else summary,
                "published_at": published_at,
                "sub_name": sub_name,
            })
    return results


def _fetch_reddit_public_json(subreddits: list[str], sort: str = "hot", limit: int = 15) -> list[dict]:
    """尝试通过 Reddit 公开 .json 端点拉取。"""
    sub_str = "+".join(subreddits)
    url = f"https://www.reddit.com/r/{sub_str}/{sort}.json?limit={limit}"
    ua = random.choice(REDDIT_USER_AGENTS)
    headers = {
        "User-Agent": ua,
        "Accept": "application/json",
    }
    resp = requests.get(url, headers=headers, timeout=10)
    if resp.status_code != 200:
        raise RuntimeError(f"Reddit public JSON returned HTTP {resp.status_code}")

    data = resp.json()
    children = data.get("data", {}).get("children", [])
    return _parse_reddit_json_children(children, subreddits)


def _fetch_reddit_oauth_json(subreddits: list[str], sort: str = "hot", limit: int = 15) -> list[dict]:
    """使用 Reddit 官方 OAuth API 拉取标准 JSON。"""
    client_id = os.getenv("REDDIT_CLIENT_ID", "").strip()
    client_secret = os.getenv("REDDIT_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return []

    auth = requests.auth.HTTPBasicAuth(client_id, client_secret)
    token_resp = requests.post(
        "https://www.reddit.com/api/v1/access_token",
        auth=auth,
        data={"grant_type": "client_credentials"},
        headers={"User-Agent": "ProActive-Agent/1.0"},
        timeout=10,
    )
    if token_resp.status_code != 200:
        raise RuntimeError(f"Reddit OAuth token failed: {token_resp.status_code}")

    token = token_resp.json().get("access_token")
    if not token:
        raise RuntimeError("Reddit OAuth token missing")

    sub_str = "+".join(subreddits)
    url = f"https://oauth.reddit.com/r/{sub_str}/{sort}?limit={limit}"
    resp = requests.get(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "ProActive-Agent/1.0",
        },
        timeout=12,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Reddit OAuth API returned {resp.status_code}")

    children = resp.json().get("data", {}).get("children", [])
    return _parse_reddit_json_children(children, subreddits)


def _fetch_reddit_rss(subreddits: list[str], sort: str = "hot", limit: int = 15) -> list[dict]:
    """通过 Reddit 公开 RSS 抓取多个 subreddit。"""
    sub_str = "+".join(subreddits)
    url = f"https://www.reddit.com/r/{sub_str}/{sort}.rss?limit={limit}"
    ua = random.choice(REDDIT_USER_AGENTS)
    headers = {
        "User-Agent": ua,
        "Accept": "application/atom+xml,application/xml,text/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    resp = requests.get(url, headers=headers, timeout=12)
    if resp.status_code != 200:
        raise RuntimeError(f"Reddit RSS returned HTTP {resp.status_code}")

    root = ET.fromstring(resp.text)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    results: list[dict] = []

    for entry in root.findall("atom:entry", ns):
        title_el = entry.find("atom:title", ns)
        link_el = entry.find("atom:link", ns)
        published_el = entry.find("atom:published", ns) or entry.find("atom:updated", ns)
        content_el = entry.find("atom:content", ns)
        category_el = entry.find("atom:category", ns)

        title = (title_el.text or "").strip() if title_el is not None else ""
        link = link_el.attrib.get("href", "").strip() if link_el is not None else ""
        published_at = (published_el.text or "").strip() if published_el is not None else ""
        raw_content = content_el.text if content_el is not None else ""
        clean_text = _clean_html_text(raw_content)

        sub_name = ""
        if category_el is not None and "term" in category_el.attrib:
            sub_name = category_el.attrib["term"]
        elif "/r/" in link:
            match = re.search(r"/r/([^/]+)/", link)
            if match:
                sub_name = match.group(1)

        if title and link:
            results.append({
                "title": title,
                "url": link,
                "content": clean_text[:400],
                "content_full": clean_text[:4000],
                "published_at": published_at,
                "sub_name": sub_name or (subreddits[0] if subreddits else "reddit"),
            })
    return results


def _monthly_limit() -> int:
    credits = float(os.getenv("TAVILY_MONTHLY_CREDITS", "1000"))
    ratio = float(os.getenv("TAVILY_BUDGET_RATIO", "1.0"))
    return int(credits * ratio)


def _tavily_keys() -> list[str]:
    raw = os.getenv("TAVILY_API_KEYS", "").strip() or os.getenv("TAVILY_API_KEY", "").strip()
    return [k.strip() for k in raw.split(",") if k.strip()]


def _pick_key(month: str, limit: int) -> tuple[str, int]:
    keys = _tavily_keys()
    if not keys:
        return "", -1
    with store.connect() as conn:
        used = [store.get_usage(conn, month, "tavily", "search", i) for i in range(len(keys))]
    candidates = [(used[i], i) for i in range(len(keys)) if used[i] < limit]
    if not candidates:
        return "", -1
    _, i = min(candidates)
    return keys[i], i


def _fetch_reddit_via_tavily(subreddits: list[str], queries: list[str], days: int = 7, max_results: int = 8) -> list[dict]:
    """通过 Tavily 搜索 Reddit 目标社区与关键词（include_domains 过滤，抗反爬能力强）。"""
    limit = _monthly_limit()
    month = datetime.now().strftime("%Y-%m")
    api_key, key_idx = _pick_key(month, limit)
    if not api_key:
        print("[reddit:tavily_fallback] Tavily 本月配额已耗尽，跳过 Tavily 兜底")
        return []

    raw_query = queries[0] if queries else "hot discussion"
    clean_query = re.sub(r"\b(OR|AND|NOT)\b", " ", raw_query)
    clean_query = " ".join(clean_query.split())
    sub_tag = subreddits[0] if subreddits else ""
    q_str = f"{clean_query} {sub_tag}".strip()

    payload = {
        "api_key": api_key,
        "query": q_str,
        "include_domains": ["reddit.com"],
        "search_depth": "advanced",
        "include_raw_content": True,
        "max_results": max_results,
    }
    resp = requests.post("https://api.tavily.com/search", json=payload, timeout=20)
    if resp.status_code != 200:
        return []

    with store.connect() as conn:
        store.incr_usage(conn, month, "tavily", "search", key_idx)
        store.incr_usage(conn, month, "tavily", "search", key_idx)

    data = resp.json()
    results: list[dict] = []
    for r in data.get("results", []):
        url = r.get("url", "").strip()
        title = r.get("title", "").strip()
        content = r.get("content", "").strip()
        raw_full = r.get("raw_content", "") or content
        pub = r.get("published_date", "") or ""

        match = re.search(r"reddit\.com/r/([^/]+)/", url)
        sub_name = match.group(1) if match else (subreddits[0] if subreddits else "reddit")

        if title and url:
            results.append({
                "title": title,
                "url": url,
                "content": content[:400],
                "content_full": raw_full[:4000],
                "published_at": pub,
                "sub_name": sub_name,
            })
    return results


def fetch_reddit(topic: dict, llm=None) -> list[dict]:
    """主采集函数：JSON 首选，自动降级适配。"""
    subreddits = topic.get("subreddits", [])
    sort = topic.get("sort", "hot")
    limit = topic.get("max_results", 10)
    queries = topic.get("queries", [])
    days = topic.get("days", 3)
    tid = topic.get("id", "reddit")

    raw_posts: list[dict] = []

    # 1. 优先使用 Reddit OAuth 官方 JSON API (如已配置 Client ID)
    if os.getenv("REDDIT_CLIENT_ID"):
        try:
            raw_posts = _fetch_reddit_oauth_json(subreddits, sort=sort, limit=limit)
        except Exception as e:
            print(f"[reddit:{tid}] OAuth JSON 拉取异常: {e}, 降级尝试公开端点")

    # 2. 尝试公开 .json 端点
    if not raw_posts and subreddits:
        try:
            raw_posts = _fetch_reddit_public_json(subreddits, sort=sort, limit=limit)
        except Exception:
            # 公开 .json 遇到 403 时静默切换到 RSS / Tavily
            pass

    # 3. 尝试公开 RSS Feed
    if not raw_posts and subreddits:
        try:
            raw_posts = _fetch_reddit_rss(subreddits, sort=sort, limit=limit)
        except Exception as e:
            print(f"[reddit:{tid}] 直连受限 ({e}), 自动切换 Tavily 搜索兜底")
            try:
                raw_posts = _fetch_reddit_via_tavily(subreddits, queries, days=days, max_results=limit)
            except Exception as e2:
                print(f"[reddit:{tid}] Tavily 兜底失败: {e2}")

    # 4. 若无 subreddits 但有 queries，直接走 Tavily
    if not raw_posts and not subreddits and queries:
        try:
            raw_posts = _fetch_reddit_via_tavily(subreddits, queries, days=days, max_results=limit)
        except Exception as e:
            print(f"[reddit:{tid}] Tavily 搜索失败: {e}")

    items: list[dict] = []
    seen = set()
    for p in raw_posts:
        url = p.get("url", "").strip()
        title = p.get("title", "").strip()
        if not title or not url or url in seen:
            continue
        seen.add(url)
        sub_name = p.get("sub_name", "reddit")
        source_label = f"Reddit/r/{sub_name}"

        items.append(make_item(
            topic_id=topic["id"],
            source=source_label,
            title=title,
            url=url,
            content=p.get("content", ""),
            content_full=p.get("content_full", ""),
            published_at=p.get("published_at", ""),
        ))

    return items
