"""网页投递：生成静态 feed.json + index.html，供 modernyu.org 托管。

把 WEB_OUT_DIR 指向你网站的发布目录(或用 rsync/CI 同步过去)即可。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

HTML_TEMPLATE = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ProActive · 资讯精选</title>
<style>
 body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:760px;margin:0 auto;padding:24px;background:#0b0c10;color:#e8e8e8}}
 h1{{font-size:20px}} .upd{{color:#888;font-size:13px;margin-bottom:20px}}
 .card{{background:#16181d;border:1px solid #23262d;border-radius:12px;padding:14px 16px;margin:12px 0}}
 .tag{{display:inline-block;font-size:12px;color:#7fd1ff;background:#102530;padding:2px 8px;border-radius:6px;margin-right:6px}}
 .score{{float:right;color:#9ae6b4;font-size:13px}}
 a{{color:#cfe8ff;text-decoration:none}} a:hover{{text-decoration:underline}}
 .reason{{color:#aaa;font-size:13px;margin-top:6px}}
</style></head><body>
<h1>ProActive · 资讯精选</h1>
<div class="upd">更新于 {updated}</div>
{cards}
</body></html>"""

CARD = """<div class="card"><span class="score">★{score}</span>
<span class="tag">{topic}</span><a href="{url}" target="_blank">{title}</a>
<div class="reason">{reason} · {source}</div></div>"""


def publish_web(payload: dict) -> bool:
    out_dir = Path(os.getenv("WEB_OUT_DIR", "./web_out"))
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        # 1) 机器可读 feed
        (out_dir / "feed.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        # 2) 人可读页面
        cards = "\n".join(
            CARD.format(
                score=i.get("score", ""), topic=i.get("topic", ""),
                url=i.get("url", "#"), title=_esc(i.get("title", "")),
                reason=_esc(i.get("reason", "")), source=_esc(i.get("source", "")),
            )
            for i in payload.get("items", [])
        )
        html = HTML_TEMPLATE.format(
            updated=time.strftime("%Y-%m-%d %H:%M", time.localtime(payload.get("updated", time.time()))),
            cards=cards or "<p>暂无新内容</p>",
        )
        (out_dir / "index.html").write_text(html, encoding="utf-8")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[web] 生成失败: {e}")
        return False


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
