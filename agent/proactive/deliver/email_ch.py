"""邮件投递(SMTP)。"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def send_email(subject: str, html: str, text: str) -> bool:
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    pw = os.getenv("SMTP_PASS")
    to = os.getenv("EMAIL_TO", user)
    if not all([host, user, pw, to]):
        print("[email] 缺少 SMTP 配置, 跳过")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(user, pw)
            server.sendmail(user, [a.strip() for a in to.split(",")], msg.as_string())
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[email] 发送失败: {e}")
        return False
