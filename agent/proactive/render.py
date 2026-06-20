"""把推送条目渲染成 邮件HTML / 纯文本(Telegram) / 网页payload。"""
from __future__ import annotations

import time


def _disp(i: dict) -> str:
    """展示用文本：优先 50 字精华总结, 回退到理由。"""
    return i.get("summary") or i.get("reason") or ""


def _group_by_topic(items: list[dict]) -> list[tuple[str, list[dict]]]:
    """按话题分组, 组内按分数降序; 组间按组内最高分降序。"""
    groups: dict[str, list[dict]] = {}
    for i in items:
        groups.setdefault(i.get("topic_name", "其他"), []).append(i)
    for g in groups.values():
        g.sort(key=lambda x: x.get("score", 0), reverse=True)
    return sorted(groups.items(),
                  key=lambda kv: max(x.get("score", 0) for x in kv[1]), reverse=True)


def _line(i: dict) -> str:
    return (f"[{i['topic_name']}] ★{i['score']} {i['title']}\n"
            f"  {_disp(i)}\n  {i['url']}\n")


def render_text(items: list[dict], title: str) -> str:
    head = f"{title}（{len(items)} 条）\n" + "=" * 28 + "\n\n"
    out = []
    for name, gitems in _group_by_topic(items):
        out.append(f"【{name}】")
        out.extend(_line(i) for i in gitems)
    return head + "\n".join(out)


def render_html(items: list[dict], title: str) -> str:
    sections = []
    for name, gitems in _group_by_topic(items):
        rows = []
        for i in gitems:
            rows.append(
                f"<div style='margin:10px 0;padding:12px 14px;border:1px solid #e2e2e2;border-radius:10px'>"
                f"<div style='font-size:12px;color:#888'>★{i['score']} · {i.get('source','')}</div>"
                f"<a href='{i['url']}' style='font-size:15px;color:#1452cc;text-decoration:none'>{_esc(i['title'])}</a>"
                f"<div style='font-size:13px;color:#444;margin-top:4px'>{_esc(_disp(i))}</div>"
                f"</div>"
            )
        sections.append(
            f"<h3 style='font-size:15px;margin:18px 0 6px'>{_topic_emoji(name)} {_esc(name)}</h3>"
            + "".join(rows))
    return (f"<div style='font-family:sans-serif;max-width:680px'>"
            f"<h2 style='font-size:18px'>{title}（{len(items)} 条）</h2>"
            f"{''.join(sections)}"
            f"<p style='color:#aaa;font-size:12px'>由 ProActive 自动整理 · 标记反馈可帮它越来越懂你</p></div>")


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
    """Telegram HTML 排版：按类别分组 + 加粗标题链接 + 50字总结 + 来源/分数。"""
    out = [f"{header} <b>{_esc(title)}</b>  ·  {len(items)} 条"]
    for name, gitems in _group_by_topic(items):
        em = _topic_emoji(name)
        out.append(f"\n━━━  {em} <b>{_esc(name)}</b>  ━━━")
        for i in gitems:
            score = i.get("score", "")
            fire = " 🔥" if isinstance(score, int) and score >= 85 else ""
            out.append(f"\n<b><a href=\"{_esc(i['url'])}\">{_esc(i['title'])}</a></b>{fire}")
            disp = _disp(i)
            if disp:
                out.append(f"💡 {_esc(disp)}")
            meta = " · ".join(x for x in [i.get("source", ""), f"★{score}" if score != "" else ""] if x)
            if meta:
                out.append(f"<i>{_esc(meta)}</i>")
    out.append("\n━━━━━━━━━━\n🤖 由 ProActive 自动整理")
    return "\n".join(out)


def render_web_payload(items: list[dict]) -> dict:
    return {
        "updated": time.time(),
        "items": [
            {"topic": i["topic_name"], "score": i["score"], "title": i["title"],
             "url": i["url"], "reason": _disp(i), "source": i.get("source", "")}
            for i in items
        ],
    }


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
