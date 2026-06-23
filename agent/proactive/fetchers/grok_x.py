"""grok-X 采集器（补充源，每天 1 次）。

用 grok 拉取过去 24h 内 X(Twitter) 上的热点/独家。
注意：能否真正"实时访问 X"取决于代理是否开启了 xAI 的 Live Search 能力。
若代理不支持, grok 可能返回空或泛泛内容——本采集器会优雅返回 []，不影响主流程
(Tavily 仍是主力)。判断层会照常对返回内容打分, 编造/低质内容会被低分淘汰。
"""
from __future__ import annotations

import os

from ..llm import LLMClient
from .base import make_item

GROK_X_SYSTEM = """你可以访问 X(Twitter) 的实时信息。
列出过去 24 小时内、关于给定主题、最重要/最可信/讨论度最高的内容。
要求：宁缺毋滥；不要编造链接；优先给原始 X 链接或权威新闻原链。
严格只输出 JSON 对象，不要任何解释文字、不要 markdown 代码块、不要尾随逗号。
格式：{"items":[{"title":"一句话标题","url":"原始链接","summary":"要点(40字内)","source":"账号或媒体名"}]}"""


def fetch_grok_x(topic: dict, llm=None) -> list[dict]:
    llm = llm or LLMClient()
    n = topic.get("max_results", 10)
    queries = "、".join(topic.get("queries", []))
    hint = topic.get("importance_hint", "")
    route = {
        "provider": "grok",
        "preferred": os.getenv("GROK_MODEL", "grok-4.20-fast"),
        "fallback": ["grok-4.20-0309-non-reasoning"],
    }
    user = (f"主题/关键词：{queries}\n额外侧重：{hint}\n"
            f"最多 {n} 条，按重要性排序。")
    tid = topic.get("id", "?")
    try:
        out = llm.complete_json(route, GROK_X_SYSTEM, user, temperature=0.1, max_tokens=3000)
    except Exception as e:  # noqa: BLE001
        print(f"[grok_x:{tid}] 拉取失败(grok 多次空响应, 本轮跳过, 不影响其他源): {e}")
        return []

    items: list[dict] = []
    seen = set()
    for it in out.get("items", []):
        title = (it.get("title") or "").strip()
        if not title:
            continue
        url = (it.get("url") or "").strip()
        # 无链接也保留, 用标题构造稳定 id
        key_url = url or f"grokx://{topic['id']}/{title}"
        if key_url in seen:
            continue
        seen.add(key_url)
        items.append(make_item(
            topic_id=topic["id"],
            source=it.get("source", "X/grok"),
            title=title,
            url=key_url,
            content=it.get("summary", ""),
            published_at="",
        ))
    return items
