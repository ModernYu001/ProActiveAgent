"""Slack 投递(Incoming Webhook)。

配置(.env / 环境变量):
    SLACK_ENABLED=true
    SLACK_WEBHOOK=https://hooks.slack.com/services/...

长消息按行边界拆成多条发, 与 Telegram 渠道同策略, 避免单条过长难读。
URL 独占一行, Slack 会自动识别为可点链接, 无需额外格式。
"""
from __future__ import annotations

import os

import requests

LIMIT = 3800


def _chunk_by_lines(text: str, limit: int = LIMIT) -> list[str]:
    chunks, cur = [], ""
    for line in text.split("\n"):
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


def send_slack(text: str, subject: str | None = None) -> bool:
    webhook = os.getenv("SLACK_WEBHOOK")
    if not webhook:
        print("[slack] 缺少 SLACK_WEBHOOK, 跳过")
        return False
    body = f"*{subject}*\n\n{text}" if subject else text
    ok_all = True
    for chunk in _chunk_by_lines(body):
        try:
            r = requests.post(webhook, json={"text": chunk}, timeout=30)
            if r.status_code != 200:
                print(f"[slack] HTTP {r.status_code}: {r.text[:200]}")
                ok_all = False
        except Exception as e:  # noqa: BLE001
            print(f"[slack] 发送失败: {e}")
            ok_all = False
    return ok_all
