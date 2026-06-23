"""SQLite 持久化：已见条目 / 去重指纹 / 推送历史 / 反馈 / 自省报告。

记忆是主动型 agent 的命脉——没有它就会重复打扰且学不会用户口味。
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Optional

DB_PATH = Path(__file__).resolve().parent.parent / "proactive.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,           -- 规整 URL 的指纹
    topic_id TEXT,
    source TEXT,
    title TEXT,
    url TEXT,
    content TEXT,
    published_at TEXT,
    fetched_at REAL,
    norm_title TEXT                -- 小写去标点的标题, 供模糊去重
);
CREATE INDEX IF NOT EXISTS idx_items_fetched ON items(fetched_at);

CREATE TABLE IF NOT EXISTS judgements (
    item_id TEXT PRIMARY KEY,
    score INTEGER,
    decision TEXT,                 -- push / digest / drop
    reason TEXT,
    model TEXT,
    judged_at REAL
);

CREATE TABLE IF NOT EXISTS pushes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT,
    channel TEXT,
    pushed_at REAL,
    summary TEXT,
    score INTEGER
);

CREATE TABLE IF NOT EXISTS feedback (
    item_id TEXT PRIMARY KEY,
    signal TEXT,                   -- accepted / opened / clicked / ignored / rejected
    note TEXT,
    at REAL
);

CREATE TABLE IF NOT EXISTS reviews (         -- 评判/自省层产出
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL,
    period_start REAL,
    period_end REAL,
    report TEXT,                  -- 人类可读自省报告
    suggestions TEXT,             -- JSON: 改进建议(待人审批)
    applied INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS github_stars (    -- 追踪仓库星标, 用于检测"激增"热点
    repo TEXT PRIMARY KEY,
    stars INTEGER,
    updated REAL
);

CREATE TABLE IF NOT EXISTS source_stats (    -- 来源采纳率(个性化先验)
    source TEXT PRIMARY KEY,
    ema REAL DEFAULT 0.5,        -- 滑动平均采纳率 0..1
    n INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS usage (           -- LLM 日调用配额计数
    day TEXT,                     -- YYYY-MM-DD (本地)
    provider TEXT,
    model TEXT,
    key_idx INTEGER,
    count INTEGER DEFAULT 0,
    PRIMARY KEY (day, provider, model, key_idx)
);
"""


@contextmanager
def connect(db_path: Path = DB_PATH):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path = DB_PATH):
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def item_seen(conn, item_id: str) -> bool:
    cur = conn.execute("SELECT 1 FROM items WHERE id = ?", (item_id,))
    return cur.fetchone() is not None


def recent_norm_titles(conn, lookback_days: int) -> list[tuple[str, str]]:
    since = time.time() - lookback_days * 86400
    cur = conn.execute(
        "SELECT id, norm_title FROM items WHERE fetched_at >= ? AND norm_title != ''",
        (since,),
    )
    return [(r["id"], r["norm_title"]) for r in cur.fetchall()]


def save_item(conn, item: dict):
    conn.execute(
        """INSERT OR IGNORE INTO items
           (id, topic_id, source, title, url, content, published_at, fetched_at, norm_title)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            item["id"], item.get("topic_id"), item.get("source"), item.get("title"),
            item.get("url"), item.get("content"), item.get("published_at"),
            item.get("fetched_at", time.time()), item.get("norm_title", ""),
        ),
    )


def save_judgement(conn, item_id: str, score: int, decision: str, reason: str, model: str):
    conn.execute(
        """INSERT OR REPLACE INTO judgements
           (item_id, score, decision, reason, model, judged_at) VALUES (?,?,?,?,?,?)""",
        (item_id, score, decision, reason, model, time.time()),
    )


def record_push(conn, item_id: str, channel: str, summary: str, score: int):
    conn.execute(
        "INSERT INTO pushes (item_id, channel, pushed_at, summary, score) VALUES (?,?,?,?,?)",
        (item_id, channel, time.time(), summary, score),
    )


def pushes_today(conn) -> int:
    start = time.time() - 86400
    cur = conn.execute("SELECT COUNT(DISTINCT item_id) AS n FROM pushes WHERE pushed_at >= ?", (start,))
    return cur.fetchone()["n"]


def record_feedback(conn, item_id: str, signal: str, note: str = ""):
    conn.execute(
        "INSERT OR REPLACE INTO feedback (item_id, signal, note, at) VALUES (?,?,?,?)",
        (item_id, signal, note, time.time()),
    )


def save_review(conn, period_start: float, period_end: float, report: str, suggestions: dict):
    conn.execute(
        """INSERT INTO reviews (created_at, period_start, period_end, report, suggestions)
           VALUES (?,?,?,?,?)""",
        (time.time(), period_start, period_end, report, json.dumps(suggestions, ensure_ascii=False)),
    )


def get_repo_stars(conn, repo: str):
    cur = conn.execute("SELECT stars FROM github_stars WHERE repo = ?", (repo,))
    row = cur.fetchone()
    return row["stars"] if row else None


def set_repo_stars(conn, repo: str, stars: int):
    conn.execute("INSERT OR REPLACE INTO github_stars (repo, stars, updated) VALUES (?,?,?)",
                 (repo, stars, time.time()))


def get_source_ema(conn, source: str) -> float:
    cur = conn.execute("SELECT ema FROM source_stats WHERE source = ?", (source,))
    row = cur.fetchone()
    return row["ema"] if row else 0.5      # 无历史 → 中性 0.5


def update_source_ema(conn, source: str, reward: float, alpha: float):
    """reward∈[0,1]: 采纳=1 / 点击=0.8 / 打开=0.6 / 忽略=0.2 / 否决=0。"""
    cur = conn.execute("SELECT ema, n FROM source_stats WHERE source = ?", (source,))
    row = cur.fetchone()
    if row:
        ema = (1 - alpha) * row["ema"] + alpha * reward
        n = row["n"] + 1
        conn.execute("UPDATE source_stats SET ema = ?, n = ? WHERE source = ?", (ema, n, source))
    else:
        ema = (1 - alpha) * 0.5 + alpha * reward
        conn.execute("INSERT INTO source_stats (source, ema, n) VALUES (?,?,1)", (source, ema))
    return ema


def top_source_stats(conn, limit: int = 30) -> list[dict]:
    cur = conn.execute(
        "SELECT source, ema, n FROM source_stats WHERE n > 0 ORDER BY n DESC LIMIT ?", (limit,))
    return [dict(r) for r in cur.fetchall()]


def get_usage(conn, day: str, provider: str, model: str, key_idx: int) -> int:
    cur = conn.execute(
        "SELECT count FROM usage WHERE day=? AND provider=? AND model=? AND key_idx=?",
        (day, provider, model, key_idx),
    )
    row = cur.fetchone()
    return row["count"] if row else 0


def incr_usage(conn, day: str, provider: str, model: str, key_idx: int):
    conn.execute(
        """INSERT INTO usage (day, provider, model, key_idx, count) VALUES (?,?,?,?,1)
           ON CONFLICT(day, provider, model, key_idx)
           DO UPDATE SET count = count + 1""",
        (day, provider, model, key_idx),
    )


def usage_today(conn, day: str) -> list[dict]:
    cur = conn.execute(
        "SELECT provider, model, key_idx, count FROM usage WHERE day=? ORDER BY provider, model, key_idx",
        (day,),
    )
    return [dict(r) for r in cur.fetchall()]


def fetch_review_dataset(conn, since: float) -> list[dict]:
    """汇总评判层需要的数据：推送 + 当时判断 + 用户反馈。"""
    cur = conn.execute(
        """
        SELECT p.item_id, p.summary, p.score AS push_score, p.pushed_at,
               i.title, i.url, i.topic_id, i.source,
               j.reason AS judge_reason,
               f.signal AS feedback
        FROM pushes p
        LEFT JOIN items i ON i.id = p.item_id
        LEFT JOIN judgements j ON j.item_id = p.item_id
        LEFT JOIN feedback f ON f.item_id = p.item_id
        WHERE p.pushed_at >= ?
        ORDER BY p.pushed_at DESC
        """,
        (since,),
    )
    return [dict(r) for r in cur.fetchall()]
