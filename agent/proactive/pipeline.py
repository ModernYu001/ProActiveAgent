"""一轮监控的编排：采集 → 去重 → 判断 → 行动。"""
from __future__ import annotations

import time

from . import store
from .dedup import is_duplicate_title
from .fetchers import fetch_topic
from .judge import decide, hard_filter, judge_batch


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def run_topic(llm, cfg: dict, topic: dict) -> dict:
    """处理单个话题：采集 → 去重 → 硬规则 → 批量 LLM 判断 → 分档。"""
    result = {"topic": topic["id"], "push": [], "digest": [], "fetched": 0,
              "new": 0, "dropped": 0, "judge_calls": 0}

    items = fetch_topic(topic, llm)
    result["fetched"] = len(items)

    dedup_cfg = cfg["dedup"]
    judge_route = cfg["models"]["judge"]
    thresholds = cfg["thresholds"]
    profile = cfg["user_profile"]
    batch_size = cfg.get("judge", {}).get("batch_size", 12)

    survivors = []  # 通过去重+硬规则、待 LLM 判断的新条目
    with store.connect() as conn:
        seen_titles = store.recent_norm_titles(conn, dedup_cfg["lookback_days"])
        for item in items:
            if store.item_seen(conn, item["id"]):           # 1) 精确去重
                continue
            if is_duplicate_title(item["norm_title"], seen_titles,   # 2) 标题去重
                                  dedup_cfg["title_similarity_threshold"]):
                store.save_item(conn, item)
                continue
            result["new"] += 1
            store.save_item(conn, item)
            seen_titles.append((item["id"], item["norm_title"]))
            if hard_filter(item, topic):                    # 3) 硬规则(免费)
                store.save_judgement(conn, item["id"], 0, "drop", "硬规则淘汰", "rule")
                result["dropped"] += 1
                continue
            survivors.append(item)

    # 4) 批量 LLM 判断：N 条/次调用，大幅省配额
    for batch in _chunks(survivors, batch_size):
        verdicts = judge_batch(llm, judge_route, batch, topic, profile)
        result["judge_calls"] += 1
        # 整批失败时把真正的报错打出来(最常见: 模型 id 不对 / 配额用尽 / 端点不通)
        if verdicts and all(not v["ok"] for v in verdicts):
            print(f"  ⚠ 判断失败 [{topic['id']}]: {verdicts[0]['reason']}")
        with store.connect() as conn:
            for item, j in zip(batch, verdicts):
                d = decide(j["score"], thresholds)
                store.save_judgement(conn, item["id"], j["score"], d, j["reason"],
                                     judge_route["preferred"])
                enriched = {**item, "score": j["score"], "reason": j["reason"],
                            "topic_name": topic.get("name", topic["id"])}
                if d == "push":
                    result["push"].append(enriched)
                elif d == "digest":
                    result["digest"].append(enriched)
                else:
                    result["dropped"] += 1

    return result
