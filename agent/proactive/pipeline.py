"""一轮监控的编排：采集 → 去重 → 两段式判断(粗筛→读正文深判) → 个性化先验 → 分档。"""
from __future__ import annotations

import time

from . import store
from .dedup import is_duplicate_title
from .fetchers import fetch_topic
from .judge import (apply_source_prior, decide, hard_filter, judge_batch,
                    judge_deep)


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def run_topic(llm, cfg: dict, topic: dict) -> dict:
    result = {"topic": topic["id"], "push": [], "digest": [], "fetched": 0,
              "new": 0, "dropped": 0, "judge_calls": 0, "deep_calls": 0}

    items = fetch_topic(topic, llm)
    result["fetched"] = len(items)

    dedup_cfg = cfg["dedup"]
    judge_route = cfg["models"]["judge"]
    thresholds = cfg["thresholds"]
    profile = cfg["user_profile"]
    jcfg = cfg.get("judge", {})
    pcfg = cfg.get("personalize", {})
    batch_size = jcfg.get("batch_size", 15)
    triage_floor = jcfg.get("triage_floor", 50)
    deep_max = jcfg.get("deep_max_chars", 4000)
    prior_w = pcfg.get("source_prior_weight", 15)

    # ---- 去重 + 硬规则 ----
    survivors = []
    with store.connect() as conn:
        seen_titles = store.recent_norm_titles(conn, dedup_cfg["lookback_days"])
        for item in items:
            if store.item_seen(conn, item["id"]):
                continue
            if is_duplicate_title(item["norm_title"], seen_titles,
                                  dedup_cfg["title_similarity_threshold"]):
                store.save_item(conn, item)
                continue
            result["new"] += 1
            store.save_item(conn, item)
            seen_titles.append((item["id"], item["norm_title"]))
            if hard_filter(item, topic):
                store.save_judgement(conn, item["id"], 0, "drop", "硬规则淘汰", "rule")
                result["dropped"] += 1
                continue
            survivors.append(item)

    # ---- 第一段：批量粗筛(标题+摘要) ----
    triaged = []   # 过了初筛、待深判
    for batch in _chunks(survivors, batch_size):
        verdicts = judge_batch(llm, judge_route, batch, topic, profile)
        result["judge_calls"] += 1
        if verdicts and all(not v["ok"] for v in verdicts):
            print(f"  ⚠ 判断失败 [{topic['id']}]: {verdicts[0]['reason']}")
        with store.connect() as conn:
            for item, j in zip(batch, verdicts):
                if j["score"] >= triage_floor:
                    item["_base"] = j["score"]
                    item["reason"] = j["reason"]
                    triaged.append(item)
                else:
                    store.save_judgement(conn, item["id"], j["score"], "drop",
                                         j["reason"], judge_route["preferred"])
                    result["dropped"] += 1

    # ---- 第二段：读正文深判(仅初筛通过者) + 来源个性化先验 ----
    for item in triaged:
        deep = judge_deep(llm, judge_route, item, topic, profile, deep_max)
        if deep["ok"]:
            result["deep_calls"] += 1
        raw = deep["score"]                       # 原始重要性(供探索用)
        with store.connect() as conn:
            ema = store.get_source_ema(conn, item.get("source", ""))
        final = apply_source_prior(raw, ema, prior_w)   # 个性化调整后分数
        d = decide(final, thresholds)
        disp = deep.get("summary") or deep["reason"]    # 展示用 50 字总结
        with store.connect() as conn:
            store.save_judgement(conn, item["id"], final, d, disp,
                                 judge_route["preferred"])
        enriched = {**item, "score": final, "raw_importance": raw,
                    "reason": deep["reason"], "summary": deep.get("summary", ""),
                    "topic_name": topic.get("name", topic["id"])}
        if d == "push":
            result["push"].append(enriched)
        elif d == "digest":
            result["digest"].append(enriched)
        else:
            result["dropped"] += 1

    return result
