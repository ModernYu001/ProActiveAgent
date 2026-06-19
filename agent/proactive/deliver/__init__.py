"""交付渠道适配器：邮件 / Telegram / 网页。按 .env 开关决定启用哪些。"""
import os

from .email_ch import send_email
from .telegram_ch import send_telegram
from .web_ch import publish_web


def deliver_all(subject: str, html: str, text: str, web_payload: dict | None = None,
                tg: str | None = None) -> list[str]:
    """向所有启用的渠道投递；返回成功的渠道名列表。
    tg: Telegram 专用的 HTML 富文本; 不传则回退到 text。
    """
    sent = []
    if os.getenv("EMAIL_ENABLED", "false").lower() == "true":
        if send_email(subject, html, text):
            sent.append("email")
    if os.getenv("TELEGRAM_ENABLED", "false").lower() == "true":
        if send_telegram(tg or text):
            sent.append("telegram")
    if os.getenv("WEB_ENABLED", "false").lower() == "true" and web_payload is not None:
        if publish_web(web_payload):
            sent.append("web")
    return sent
