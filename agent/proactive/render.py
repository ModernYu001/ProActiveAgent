"""把推送条目渲染成 邮件HTML / 纯文本(Telegram) / 网页payload。"""
from __future__ import annotations

import time


def _line(i: dict) -> str:
    return (f"[{i['topic_name']}] ★{i['score']} {i['title']}\n"
            f"  理由: {i['reason']}\n  {i['url']}\n")


def render_text(items: list[dict], title: str) -> str:
    head = f"{title}（{len(items)} 条）\n" + "=" * 28 + "\n\n"
    return head + "\n".join(_line(i) for i in items)


def render_html(items: list[dict], title: str) -> str:
    rows = []
    for i in items:
        rows.append(
            f"<div style='margin:14px 0;padding:12px 14px;border:1px solid #e2e2e2;border-radius:10px'>"
            f"<div style='font-size:12px;color:#888'>{i['topic_name']} · ★{i['score']} · {i.get('source','')}</div>"
            f"<a href='{i['url']}' style='font-size:15px;color:#1452cc;text-decoration:none'>{_esc(i['title'])}</a>"
            f"<div style='font-size:13px;color:#666;margin-top:4px'>为什么值得看：{_esc(i['reason'])}</div>"
            f"</div>"
        )
    return (f"<div style='font-family:sans-serif;max-width:680px'>"
            f"<h2 style='font-size:18px'>{title}（{len(items)} 条）</h2>"
            f"{''.join(rows)}"
            f"<p style='color:#aaa;font-size:12px'>由 ProActive 自动整理 · 回复本邮件或在面板标记反馈可帮它越来越懂你</p></div>")


_TOPIC_EMOJI = [
    ("GitHub", "🐙"), ("时政", "🌍"), ("突发", "🚨"),
    ("科技", "🤖"), ("AI 行业", "🤖"), ("独角兽", "🦄"),
]


def _topic_emoji(name: str) -> str:
    for k, e in _TOPIC_EMOJI:
        if k in (name or ""):
            return e
    return "📌"


def render_telegram(items: list[dict], title: str, header: str = "⚡️") -> str:
    """Telegram HTML 排版：话题 emoji + 加粗标题链接 + 理由 + 来源/分数。"""
    out = [f"{header} <b>{_esc(title)}</b>  ·  {len(items)} 条", "➖➖➖➖➖➖➖➖➖➖"]
    for i in items:
        em = _topic_emoji(i.get("topic_name", ""))
        score = i.get("score", "")
        fire = " 🔥" if isinstance(score, int) and score >= 85 else ""
        out.append(f"\n{em} <b><a href=\"{_esc(i['url'])}\">{_esc(i['title'])}</a></b>{fire}")
        if i.get("reason"):
            out.append(f"💡 {_esc(i['reason'])}")
        meta = " · ".join(x for x in [i.get("source", ""), f"★{score}" if score != "" else ""] if x)
        if meta:
            out.append(f"<i>{_esc(meta)}</i>")
    out.append("\n➖➖➖➖➖➖➖➖➖➖\n🤖 由 ProActive 自动整理")
    return "\n".join(out)


def render_web_payload(items: list[dict]) -> dict:
    return {
        "updated": time.time(),
        "items": [
            {"topic": i["topic_name"], "score": i["score"], "title": i["title"],
             "url": i["url"], "reason": i["reason"], "source": i.get("source", "")}
            for i in items
        ],
    }


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
