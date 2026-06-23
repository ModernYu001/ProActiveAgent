"""Telegram 投递(Bot API)。

获取 chat_id：把你的 bot 加进对话发一条消息，访问
https://api.telegram.org/bot<token>/getUpdates 取 chat.id。

长消息按"行边界"拆成多条发——绝不在标签中间截断(否则 Telegram 报
can't parse entities)。排版里每行标签都是自闭合配对的, 按换行拆分即安全。
"""
from __future__ import annotations

import os

import requests

LIMIT = 3800   # 留余量, Telegram 硬上限 4096


def _chunk_by_lines(text: str, limit: int = LIMIT) -> list[str]:
    chunks, cur = [], ""
    for line in text.split("\n"):
        # 极端情况: 单行超长 → 硬切(罕见, 标题/总结都很短)
        while len(line) > limit:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if cur and len(cur) + len(line) + 1 > limit:
            chunks.append(cur)
            cur = ""
        cur = f"{cur}\n{line}" if cur else line
    if cur:
        chunks.append(cur)
    return chunks


def send_telegram(text: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[telegram] 缺少 token/chat_id, 跳过")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    ok_all = True
    for chunk in _chunk_by_lines(text):
        try:
            r = requests.post(url, json={
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }, timeout=30)
            if r.status_code != 200:
                print(f"[telegram] HTTP {r.status_code}: {r.text[:200]}")
                ok_all = False
        except Exception as e:  # noqa: BLE001
            print(f"[telegram] 发送失败: {e}")
            ok_all = False
    return ok_all
