"""评判 / 自省层 ★ —— 后台周期运行的元 agent。

回答一个问题：过去这段时间，agent 是在"乱发干扰"还是"贴心懂用户"？
用更强的模型(grok)做：
  1. 数据汇总：推送 + 当时判断 + 用户反馈(打开/点击/忽略/否决)。
  2. 自一致性回看：事后重评每条推送当时是否真的值得打扰。
  3. 模式定位：哪个来源/话题在持续制造噪音。
  4. 产出：人类可读自省报告 + 改进建议(JSON, 待人审批)。

与反馈层分工：反馈层=实时单条调参数(快反射)；评判层=周期全局调策略(慢思考)。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import store

PROPOSED_PROFILE = Path(__file__).resolve().parent.parent / "proposed_profile.txt"

PROFILE_SYSTEM = """你在维护一位用户的"关注画像"——它会被判断层用来决定推送什么。
依据：用户对历史推送的反馈(accepted/clicked=喜欢, ignored/rejected=不喜欢)，以及各来源采纳率。
在**保留原画像主旨**的前提下，微调出一版更懂用户的新画像：强化他明显偏好的主题/来源，弱化他持续忽略/反感的。
不要大改、不要臆测、不要写成清单。输出一段自然语言画像(150字内)，只输出画像文本本身。"""


def propose_profile(llm, route: dict, current_profile: str, dataset: list[dict],
                    source_stats: list[dict]) -> str | None:
    """用反馈 + 来源采纳率重写一版 user_profile，写入 proposed_profile.txt 待人审批。"""
    fb = [d for d in dataset if d.get("feedback")]
    if not fb and not source_stats:
        return None
    fb_lines = "\n".join(
        f"- [{d.get('feedback')}] {d.get('title')} ({d.get('topic_id')})" for d in fb[:40])
    src_lines = "\n".join(
        f"- {s['source']}: 采纳率 {s['ema']:.2f} (n={s['n']})" for s in source_stats[:20])
    user_msg = (f"原画像:\n{current_profile}\n\n反馈记录:\n{fb_lines or '(暂无显式反馈)'}\n\n"
                f"来源采纳率:\n{src_lines or '(暂无)'}\n\n请给出微调后的新画像文本。")
    try:
        new_profile = llm.complete(route, PROFILE_SYSTEM, user_msg,
                                   temperature=0.4, max_tokens=400).strip()
    except Exception:  # noqa: BLE001
        return None
    if new_profile:
        PROPOSED_PROFILE.write_text(new_profile, encoding="utf-8")
    return new_profile

CRITIC_SYSTEM = """你是一个主动型资讯 agent 的"总编审/质检官"。
你要冷静复盘这个 agent 最近的推送表现，判断它是在【乱发干扰消息】还是【贴心理解了用户】。
依据用户反馈信号(accepted=认可, opened=打开, clicked=点了原文, ignored=忽略, rejected=明确反感, null=无反馈)，
以及你自己事后重评"这条当时真的值得即时打扰吗"。

请严格输出 JSON：
{
  "verdict": "贴心" | "尚可" | "偏吵" | "干扰严重",
  "precision_estimate": 0-100,         // 估计推送里"用户真想看"的占比
  "report": "中文复盘, 200字内, 指出做得好/差的地方与典型案例",
  "noisy_sources": ["持续制造噪音的来源或话题id"],
  "suggestions": [                       // 具体、可执行、保守的改进建议
    {"action": "lower_threshold"|"raise_threshold"|"downweight_source"|"add_blocklist"|"edit_judge_prompt",
     "target": "话题id/来源/关键词", "detail": "一句话说明", "risk": "low"|"high"}
  ]
}"""


def run_review(llm, cfg: dict, lookback_hours: int = 24) -> dict | None:
    route = cfg["models"]["critic"]
    current_profile = cfg.get("user_profile", "")
    since = time.time() - lookback_hours * 3600
    with store.connect() as conn:
        dataset = store.fetch_review_dataset(conn, since)
        source_stats = store.top_source_stats(conn, 20)

    if not dataset:
        return None

    lines = []
    for d in dataset:
        lines.append(
            f"- [{d.get('topic_id')}] {d.get('title')} | 当时分={d.get('push_score')} "
            f"| 理由={d.get('judge_reason')} | 反馈={d.get('feedback') or '无'}"
        )
    user_msg = (
        f"最近 {lookback_hours} 小时共推送 {len(dataset)} 条。逐条如下：\n"
        + "\n".join(lines)
        + "\n\n请按要求复盘并输出 JSON。"
    )

    try:
        result = llm.complete_json(route, CRITIC_SYSTEM, user_msg,
                                   temperature=0.3, max_tokens=1200)
    except Exception as e:  # noqa: BLE001
        result = {"verdict": "复盘失败", "report": f"评判层调用失败: {e}",
                  "precision_estimate": None, "noisy_sources": [], "suggestions": []}

    report = (
        f"裁定: {result.get('verdict')}  |  估计推送精确率: {result.get('precision_estimate')}%\n\n"
        f"{result.get('report', '')}\n\n"
        f"噪音来源: {', '.join(result.get('noisy_sources', [])) or '无'}"
    )
    suggestions = result.get("suggestions", [])

    # 重写画像(待人审批): 写入 proposed_profile.txt
    new_profile = propose_profile(llm, route, current_profile, dataset, source_stats)

    with store.connect() as conn:
        store.save_review(conn, since, time.time(), report, suggestions)

    return {"report": report, "suggestions": suggestions, "raw": result,
            "proposed_profile": new_profile}
