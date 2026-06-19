"""Telegram 投递(Bot API)。

获取 chat_id：把你的 bot 加进对话发一条消息，访问
https://api.telegram.org/bot<token>/getUpdates 取 chat.id。
"""
from __future__ import annotations

import os

import requests


def send_telegram(text: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[telegram] 缺少 token/chat_id, 跳过")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    # Telegram 单条上限 4096 字符
    try:
        r = requests.post(url, json={
            "chat_id": chat_id,
            "text": text[:4000],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=30)
        if r.status_code != 200:
            print(f"[telegram] HTTP {r.status_code}: {r.text[:200]}")
            return False
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[telegram] 发送失败: {e}")
        return False
