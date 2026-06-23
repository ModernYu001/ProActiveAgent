#!/usr/bin/env python3
"""grok 调试：抓原始响应, 分析"空响应"成因。
用法: ./.venv/bin/python debug_grok.py
把完整输出贴回给助手。
"""
import json
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

BASE = os.getenv("GROK_BASE_URL", "").rstrip("/")
KEY = os.getenv("GROK_API_KEY", "")
MODEL = os.getenv("GROK_MODEL", "grok-4.20-fast")
H = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

SYS = ('你可以访问 X(Twitter) 实时信息。列出过去 24 小时关于 "AI breaking news" 最重要的内容。'
       '只输出 JSON：{"items":[{"title":"","url":"","summary":"","source":""}]}')
USER = "主题: AI breaking news, 最多 5 条"


def stream(messages, model, max_tokens, tag):
    print(f"\n{'='*54}\n{tag}  (model={model}, max_tokens={max_tokens}, stream)\n{'='*54}")
    body = {"model": model, "messages": messages, "temperature": 0.1,
            "max_tokens": max_tokens, "stream": True}
    try:
        r = requests.post(f"{BASE}/chat/completions", json=body, headers=H, timeout=90, stream=True)
    except Exception as e:
        print("  请求异常:", e); return
    print("  HTTP", r.status_code)
    n = 0
    content = ""
    fields = set()
    for line in r.iter_lines(decode_unicode=True):
        if not line:
            continue
        n += 1
        if n <= 6:
            print("  SSE>", line[:220])              # 原始前几行
        if line.startswith("data:"):
            d = line[5:].strip()
            if d == "[DONE]":
                continue
            try:
                delta = json.loads(d)["choices"][0].get("delta", {})
                fields.update(delta.keys())
                content += delta.get("content") or ""
            except Exception:
                pass
    print(f"  总SSE行={n} | delta出现过的字段={fields or '无'} | content拼接长度={len(content)}")
    if content:
        print("  content预览:", content[:200])


def nonstream(messages, model, max_tokens, tag):
    print(f"\n{'='*54}\n{tag}  (model={model}, 非流式)\n{'='*54}")
    body = {"model": model, "messages": messages, "temperature": 0.1,
            "max_tokens": max_tokens, "stream": False}
    try:
        r = requests.post(f"{BASE}/chat/completions", json=body, headers=H, timeout=90)
    except Exception as e:
        print("  请求异常:", e); return
    print("  HTTP", r.status_code, "| body长度", len(r.text))
    print("  body前 800 字:\n", r.text[:800])


if __name__ == "__main__":
    print("BASE=", BASE, "MODEL=", MODEL)
    stream([{"role": "user", "content": "用一句话介绍你自己"}], MODEL, 200, "① 基线·简单提问")
    stream([{"role": "system", "content": SYS}, {"role": "user", "content": USER}], MODEL, 3000,
           "② grok_x 同款提示")
    nonstream([{"role": "system", "content": SYS}, {"role": "user", "content": USER}], MODEL, 3000,
              "③ grok_x 同款·非流式看原始body")
    stream([{"role": "system", "content": SYS}, {"role": "user", "content": USER}],
           "grok-4.20-0309-non-reasoning", 3000, "④ 换 non-reasoning 模型")
