"""判断层 ★ —— 决定一条新条目值不值得现在打扰用户。

硬规则粗筛 + LLM 语义打分。输出 0-100 重要性分 + 一句理由。
这是整个系统体验的命门：判断准 = 贴心；判断滥 = 干扰。
"""
from __future__ import annotations

import json

JUDGE_SYSTEM = """你是一个资讯重要性评判官，为一位有明确关注画像的用户把关。
你的唯一目标：只让"用户真的想第一时间知道"的条目通过，宁缺毋滥。
对每条资讯输出 0-100 的重要性分，并给一句中文理由(20字内)。
评分维度：
- 相关度：是否命中用户关注画像。
- 新颖性：是不是旧闻翻炒/日常更新(这类要大幅扣分)。
- 影响力：事件本身的量级与影响范围。
- 紧迫性：是否需要"现在"知道(突发要加分)。
营销软文、标题党、无信息量的内容一律低分(<30)。
只输出 JSON：{"score": int, "reason": str}"""


def hard_filter(item: dict, topic: dict) -> bool:
    """返回 True 表示直接淘汰(不进 LLM)，省调用。"""
    title = (item.get("title") or "").lower()
    if len(title) < 6:
        return True
    spam = ["sponsored", "推广", "广告", "coupon", "discount code", "best deals"]
    return any(s in title for s in spam)


def judge_item(llm, route: dict, item: dict, topic: dict, user_profile: str) -> dict:
    """返回 {score, reason}。LLM 失败时给保守低分，避免误推。"""
    hint = topic.get("importance_hint", "")
    user_msg = (
        f"用户关注画像:\n{user_profile}\n\n"
        f"本话题额外重要性提示: {hint}\n\n"
        f"待评判条目:\n"
        f"- 来源: {item.get('source')}\n"
        f"- 标题: {item.get('title')}\n"
        f"- 摘要: {(item.get('content') or '')[:600]}\n"
        f"- 时间: {item.get('published_at')}\n"
    )
    try:
        out = llm.complete_json(route, JUDGE_SYSTEM, user_msg, temperature=0.1, max_tokens=200)
        score = int(out.get("score", 0))
        score = max(0, min(100, score))
        reason = str(out.get("reason", ""))[:60]
        return {"score": score, "reason": reason, "ok": True}
    except Exception as e:  # noqa: BLE001
        return {"score": 0, "reason": f"判断失败(保守丢弃): {e}", "ok": False}


BATCH_SYSTEM = """你是一个资讯重要性评判官，为一位有明确关注画像的用户把关。
目标：只让"用户真的想第一时间知道"的条目得高分，宁缺毋滥。
我会给你一批条目(带编号 i)。对每条给 0-100 重要性分 + 一句中文理由(20字内)。
评分维度：相关度(命中画像)、新颖性(旧闻/日常更新大幅扣分)、影响力、紧迫性(突发加分)。
营销软文/标题党/无信息量一律 <30。
只输出 JSON：{"results":[{"i":0,"score":int,"reason":str}, ...]}，每条都要有。"""


def judge_batch(llm, route: dict, items: list[dict], topic: dict, user_profile: str) -> list[dict]:
    """一次 LLM 调用评分多条，省配额。返回与 items 等长的 [{score, reason, ok}]。"""
    if not items:
        return []
    hint = topic.get("importance_hint", "")
    lines = []
    for idx, it in enumerate(items):
        lines.append(
            f"[i={idx}] 来源:{it.get('source')} | 标题:{it.get('title')} | "
            f"摘要:{(it.get('content') or '')[:300]}"
        )
    user_msg = (
        f"用户关注画像:\n{user_profile}\n\n本话题重要性提示: {hint}\n\n"
        f"待评判 {len(items)} 条:\n" + "\n".join(lines)
    )
    try:
        out = llm.complete_json(route, BATCH_SYSTEM, user_msg,
                                temperature=0.1, max_tokens=min(2048, 80 * len(items)))
        by_i = {int(r["i"]): r for r in out.get("results", [])}
        res = []
        for idx in range(len(items)):
            r = by_i.get(idx)
            if r is None:
                res.append({"score": 0, "reason": "未返回评分(保守丢弃)", "ok": False})
            else:
                s = max(0, min(100, int(r.get("score", 0))))
                res.append({"score": s, "reason": str(r.get("reason", ""))[:60], "ok": True})
        return res
    except Exception as e:  # noqa: BLE001
        # 整批失败：保守全丢，等下一轮(避免误推)
        return [{"score": 0, "reason": f"批量判断失败: {e}", "ok": False} for _ in items]


def decide(score: int, thresholds: dict) -> str:
    if score >= thresholds["push"]:
        return "push"
    if score >= thresholds["digest"]:
        return "digest"
    return "drop"
