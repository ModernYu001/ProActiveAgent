#!/usr/bin/env python3
"""ProActive 主入口。

用法:
  python run.py once          # 跑一轮所有话题(开发/cron 推荐)
  python run.py loop          # 常驻循环, 按各话题间隔调度
  python run.py digest        # 立刻把"攒着"的内容汇总成摘要发出
  python run.py review        # 立刻运行评判/自省层, 输出复盘报告
  python run.py test          # 向所有已启用渠道发测试消息, 验证连通
  python run.py quota         # 查看今天各模型/各 key 已用配额
  python run.py feedback <item_id> <signal>   # 记录反馈: accepted/opened/clicked/ignored/rejected
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / ".env", override=True)   # .env 优先于 shell 环境变量

from proactive import store, critic               # noqa: E402
from proactive.llm import LLMClient               # noqa: E402
from proactive.pipeline import run_topic          # noqa: E402
from proactive.render import (render_html, render_text,  # noqa: E402
                              render_web_payload, render_telegram)
from proactive.deliver import deliver_all         # noqa: E402


def _esc_tg(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def load_cfg() -> dict:
    with open(BASE / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def cmd_once(cfg, llm):
    store.init_db()
    all_push, all_digest = [], []
    for topic in cfg["topics"]:
        if not topic.get("enabled", True):
            continue
        r = run_topic(llm, cfg, topic)
        print(f"[{r['topic']}] 抓取 {r['fetched']} / 新 {r['new']} / "
              f"推送 {len(r['push'])} / 摘要 {len(r['digest'])} / 丢弃 {r['dropped']} "
              f"/ LLM调用 {r['judge_calls']}")
        all_push.extend(r["push"])
        all_digest.extend(r["digest"])

    # 打扰预算
    budget = cfg["budget"]["max_instant_pushes_per_day"]
    with store.connect() as conn:
        used = store.pushes_today(conn)
    room = max(0, budget - used)
    all_push.sort(key=lambda x: x["score"], reverse=True)
    to_push, overflow = all_push[:room], all_push[room:]
    all_digest.extend(overflow)  # 超预算的降级进摘要

    if to_push:
        _push_now(to_push)
    else:
        print("本轮无达到即时推送阈值的内容(或已用满当日预算)。")
    print(f"摘要队列累计 {len(all_digest)} 条(将于每日 digest 时段汇总)。")


def _push_now(items):
    subject = f"⚡ ProActive · {len(items)} 条值得你现在看"
    html = render_html(items, "现在值得知道")
    text = render_text(items, "现在值得知道")
    tg = render_telegram(items, "现在值得知道", header="⚡️")
    web = render_web_payload(items)
    sent = deliver_all(subject, html, text, web, tg=tg)
    with store.connect() as conn:
        for i in items:
            store.record_push(conn, i["id"], ",".join(sent) or "none", i["reason"], i["score"])
    print(f"已即时推送 {len(items)} 条 → 渠道: {sent or '无(检查 .env 渠道开关)'}")


def cmd_digest(cfg, llm):
    """把判断为 digest、且尚未推送过的条目汇总。"""
    store.init_db()
    with store.connect() as conn:
        cur = conn.execute(
            """SELECT i.id, i.title, i.url, i.source, j.score, j.reason, i.topic_id
               FROM judgements j JOIN items i ON i.id = j.item_id
               LEFT JOIN pushes p ON p.item_id = j.item_id
               WHERE j.decision = 'digest' AND p.id IS NULL
               ORDER BY j.score DESC LIMIT 40""")
        rows = [dict(r) for r in cur.fetchall()]
    if not rows:
        print("无待汇总内容。")
        return
    name_map = {t["id"]: t.get("name", t["id"]) for t in cfg["topics"]}
    items = [{**r, "topic_name": name_map.get(r["topic_id"], r["topic_id"])} for r in rows]
    subject = f"📰 ProActive · 每日摘要（{len(items)} 条）"
    sent = deliver_all(subject, render_html(items, "每日摘要"),
                       render_text(items, "每日摘要"), render_web_payload(items),
                       tg=render_telegram(items, "每日摘要", header="📰"))
    with store.connect() as conn:
        for i in items:
            store.record_push(conn, i["id"], ",".join(sent) or "none", i["reason"], i["score"])
    print(f"已发送每日摘要 {len(items)} 条 → {sent}")


def cmd_review(cfg, llm):
    store.init_db()
    hours = cfg["schedule"]["critic_interval_hours"]
    out = critic.run_review(llm, cfg["models"]["critic"], lookback_hours=hours)
    if not out:
        print("近期无推送记录, 暂无可复盘内容。")
        return
    print("\n===== 评判/自省报告 =====\n")
    print(out["report"])
    print("\n----- 改进建议(待你审批) -----")
    for s in out["suggestions"]:
        flag = "⚠需审批" if s.get("risk") == "high" else "可自动"
        print(f"  [{flag}] {s.get('action')} → {s.get('target')}: {s.get('detail')}")
    # 同时把报告作为一封邮件/消息发给用户
    tg_review = f"🔎 <b>ProActive 自省报告</b>\n➖➖➖➖➖➖➖➖➖➖\n<pre>{_esc_tg(out['report'])}</pre>"
    deliver_all("🔎 ProActive 自省报告", f"<pre>{out['report']}</pre>", out["report"], None, tg=tg_review)


def cmd_loop(cfg, llm):
    """常驻：按每个话题自己的 interval_min 调度 + 周期自省。"""
    store.init_db()
    next_run = {t["id"]: 0 for t in cfg["topics"]}
    next_review = 0
    review_gap = cfg["schedule"]["critic_interval_hours"] * 3600
    print("ProActive loop 启动。Ctrl-C 退出。")
    try:
        while True:
            now = time.time()
            due = []
            for topic in cfg["topics"]:
                if not topic.get("enabled", True):
                    continue
                if now >= next_run[topic["id"]]:
                    due.append(topic)
                    interval = topic.get("interval_min", cfg["schedule"]["default_interval_min"])
                    next_run[topic["id"]] = now + interval * 60
            if due:
                # 复用 once 的处理路径, 但只跑到期的话题
                cfg_due = {**cfg, "topics": due}
                cmd_once(cfg_due, llm)
            if now >= next_review:
                cmd_review(cfg, llm)
                next_review = now + review_gap
            time.sleep(60)
    except KeyboardInterrupt:
        print("\n已退出。")


def cmd_test(cfg, llm):
    """向所有已启用渠道发一条测试消息, 验证连通(不依赖有无新闻)。"""
    import time as _t
    text = ("✅ ProActive 测试消息\n各渠道连通正常。这条是手动测试, 非真实资讯。")
    html = ("<b>✅ ProActive 测试消息</b>\n各渠道连通正常。这条是手动测试, 非真实资讯。")
    tg = ("✅ <b>ProActive 测试消息</b>\n➖➖➖➖➖➖➖➖➖➖\n"
          "🤖 各渠道连通正常。\n<i>这条是手动测试, 非真实资讯。</i>")
    web = {"updated": _t.time(), "items": [{
        "topic": "测试", "score": 100, "title": "渠道连通测试",
        "url": "https://modernyu.org", "reason": "这是一条测试", "source": "ProActive"}]}
    sent = deliver_all("ProActive 测试", html, text, web, tg=tg)
    print("测试已发送 → 成功渠道:", sent or "无 (检查 .env 渠道开关与凭据)")


def cmd_quota(cfg, llm):
    import os
    from datetime import datetime
    store.init_db()
    day = datetime.now().strftime("%Y-%m-%d")
    month = datetime.now().strftime("%Y-%m")
    with store.connect() as conn:
        rows = store.usage_today(conn, day)
        tav_used = store.get_usage(conn, month, "tavily", "search", 0)
    quotas = cfg.get("quotas", {})
    print(f"今日 ({day}) LLM 配额使用：")
    if not rows:
        print("  尚无调用。")
    for r in rows:
        limit = quotas.get(r["provider"], {}).get(r["model"], "∞")
        print(f"  {r['provider']:7} {r['model']:24} key#{r['key_idx']}: {r['count']}/{limit}")
    tav_limit = int(float(os.getenv("TAVILY_MONTHLY_CREDITS", "1000")) *
                    float(os.getenv("TAVILY_BUDGET_RATIO", "0.8")))
    print(f"本月 ({month}) Tavily 搜索点数: {tav_used}/{tav_limit} (80%上限)")


def cmd_feedback(args):
    if len(args) < 2:
        print("用法: python run.py feedback <item_id> <signal> [note]")
        return
    store.init_db()
    with store.connect() as conn:
        store.record_feedback(conn, args[0], args[1], " ".join(args[2:]))
    print(f"已记录反馈: {args[0]} -> {args[1]}")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "once"
    if cmd == "feedback":
        cmd_feedback(sys.argv[2:])
        return
    cfg = load_cfg()
    llm = LLMClient(cfg)
    {
        "once": cmd_once, "loop": cmd_loop,
        "digest": cmd_digest, "review": cmd_review, "quota": cmd_quota,
        "test": cmd_test,
    }.get(cmd, cmd_once)(cfg, llm)


if __name__ == "__main__":
    main()
