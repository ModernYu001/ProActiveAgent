#!/usr/bin/env python3
"""ProActive 主入口。

用法:
  python run.py once          # 跑一轮所有话题(开发/cron 推荐)
  python run.py loop          # 常驻循环, 按各话题间隔调度
  python run.py digest        # 立刻把"攒着"的内容汇总成摘要发出
  python run.py review        # 立刻运行评判/自省层, 输出复盘 + 提议新画像
  python run.py apply-profile # 采纳自省层提议的新「关注画像」(审批)
  python run.py test          # 向所有已启用渠道发测试消息, 验证连通
  python run.py quota         # 查看今天各模型/各 key 已用配额
  python run.py feedback <item_id> <signal>   # 记录反馈: accepted/clicked/opened/ignored/rejected
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


LEARNED_PROFILE = BASE / "learned_profile.txt"
REWARD = {"accepted": 1.0, "clicked": 0.8, "opened": 0.6, "ignored": 0.2, "rejected": 0.0}


def load_cfg() -> dict:
    with open(BASE / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_profile(cfg) -> str:
    """有 learned_profile.txt(自省审批后的画像)则优先用, 否则用 config 里的。"""
    if LEARNED_PROFILE.exists():
        t = LEARNED_PROFILE.read_text(encoding="utf-8").strip()
        if t:
            return t
    return cfg.get("user_profile", "")


def cmd_once(cfg, llm):
    store.init_db()
    all_push, all_digest = [], []
    for topic in cfg["topics"]:
        if not topic.get("enabled", True):
            continue
        r = run_topic(llm, cfg, topic)
        print(f"[{r['topic']}] 抓取 {r['fetched']} / 新 {r['new']} / "
              f"推送 {len(r['push'])} / 摘要 {len(r['digest'])} / 丢弃 {r['dropped']} "
              f"/ 粗筛 {r['judge_calls']} 深判 {r['deep_calls']}")
        all_push.extend(r["push"])
        all_digest.extend(r["digest"])

    dcfg = cfg.get("delivery", {})
    if dcfg.get("send_every_run", True):
        # 每轮把本轮推送条目直接发出, 不受每日预算限制
        cap = dcfg.get("max_per_run", 15)
        all_push.sort(key=lambda x: x["score"], reverse=True)
        to_push, overflow = all_push[:cap], all_push[cap:]
    else:
        # 旧模式: 每日打扰预算 + 15% 探索名额
        budget = cfg["budget"]["max_instant_pushes_per_day"]
        with store.connect() as conn:
            used = store.pushes_today(conn)
        room = max(0, budget - used)
        to_push, overflow = _select_with_exploration(all_push, room, cfg)
    all_digest.extend(overflow)  # 超出的降级进摘要

    if to_push:
        _push_now(to_push)
    else:
        print("本轮无达到推送阈值的内容。")
    print(f"摘要队列累计 {len(all_digest)} 条(将于每日 digest 时段汇总)。")


def _select_with_exploration(items, room, cfg):
    """选取即时推送：85% 按个性化分(exploit)，15% 留给高重要性但被降权的(explore)。"""
    if room <= 0 or not items:
        return [], list(items)
    pcfg = cfg.get("personalize", {})
    ratio = pcfg.get("exploration_ratio", 0.15)
    floor = pcfg.get("explore_floor", 80)
    by_final = sorted(items, key=lambda x: x["score"], reverse=True)
    explore_n = min(room, max(1, round(room * ratio)))
    exploit = by_final[: room - explore_n]
    chosen = {id(x) for x in exploit}
    rest = [x for x in by_final if id(x) not in chosen]
    # 探索：优先选"原始重要性高(≥floor)但被个性化降权最多(raw-final 差距大)"的——
    # 即口味之外、却确实重要的内容, 防信息茧房。
    pool = [x for x in rest if x.get("raw_importance", x["score"]) >= floor]
    pool.sort(key=lambda x: x.get("raw_importance", x["score"]) - x["score"], reverse=True)
    explore = pool[:explore_n]
    if len(explore) < explore_n:                       # 不够就用普通高分补满
        ids = chosen | {id(x) for x in explore}
        explore += [x for x in by_final if id(x) not in ids][:explore_n - len(explore)]
    to_push = exploit + explore
    keep = {id(x) for x in to_push}
    overflow = [x for x in items if id(x) not in keep]
    return to_push, overflow


def _push_now(items):
    subject = f"⚡ ProActive · {len(items)} 条值得你现在看"
    html = render_html(items, "现在值得知道")
    text = render_text(items, "现在值得知道")
    tg = render_telegram(items, "现在值得知道", header="⚡️")
    web = render_web_payload(items)
    sent = deliver_all(subject, html, text, web, tg=tg)
    with store.connect() as conn:
        for i in items:
            store.record_push(conn, i["id"], ",".join(sent) or "none",
                              i.get("summary") or i.get("reason", ""), i["score"])
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
    out = critic.run_review(llm, cfg, lookback_hours=hours)
    if not out:
        print("近期无推送记录, 暂无可复盘内容。")
        return
    print("\n===== 评判/自省报告 =====\n")
    print(out["report"])
    print("\n----- 改进建议(待你审批) -----")
    for s in out["suggestions"]:
        flag = "⚠需审批" if s.get("risk") == "high" else "可自动"
        print(f"  [{flag}] {s.get('action')} → {s.get('target')}: {s.get('detail')}")
    if out.get("proposed_profile"):
        print("\n----- 自省层提议的新「关注画像」(待你审批) -----")
        print(out["proposed_profile"])
        print("\n采纳新画像 → 运行: python run.py apply-profile")
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
        print("用法: python run.py feedback <item_id> <signal>  "
              "(signal: accepted/clicked/opened/ignored/rejected)")
        return
    item_id, signal = args[0], args[1]
    store.init_db()
    cfg = load_cfg()
    alpha = cfg.get("personalize", {}).get("ema_alpha", 0.2)
    reward = REWARD.get(signal, 0.2)
    with store.connect() as conn:
        store.record_feedback(conn, item_id, signal, " ".join(args[2:]))
        row = conn.execute("SELECT source FROM items WHERE id = ?", (item_id,)).fetchone()
        if row and row["source"]:
            ema = store.update_source_ema(conn, row["source"], reward, alpha)
            print(f"来源「{row['source']}」采纳率 → {ema:.2f}")
    print(f"已记录反馈: {item_id} -> {signal}")


def cmd_apply_profile(cfg, llm):
    """审批: 把自省层提议的新画像采纳为正式画像(judge 下次起用)。"""
    from proactive.critic import PROPOSED_PROFILE
    if not PROPOSED_PROFILE.exists():
        print("无待审批画像。先 run.py review 生成提议。")
        return
    new = PROPOSED_PROFILE.read_text(encoding="utf-8").strip()
    print("=== 拟采用的新画像 ===\n" + new + "\n")
    LEARNED_PROFILE.write_text(new, encoding="utf-8")
    print(f"✅ 已采用 → {LEARNED_PROFILE.name}；判断层下次起用。撤销删此文件即可。")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "once"
    if cmd == "feedback":
        cmd_feedback(sys.argv[2:])
        return
    cfg = load_cfg()
    cfg["user_profile"] = load_profile(cfg)   # 优先用自省审批后的画像
    llm = LLMClient(cfg)
    {
        "once": cmd_once, "loop": cmd_loop,
        "digest": cmd_digest, "review": cmd_review, "quota": cmd_quota,
        "test": cmd_test, "apply-profile": cmd_apply_profile,
    }.get(cmd, cmd_once)(cfg, llm)


if __name__ == "__main__":
    main()
