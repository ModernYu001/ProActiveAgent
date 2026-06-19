#!/usr/bin/env python3
"""诊断脚本：查清代理与 Gemini 上真实可用的模型 id / 密钥是否有效。
把输出整段贴回给助手即可帮你改对 config.yaml。

  ./.venv/bin/python list_models.py
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

from proactive.llm import LLMClient  # noqa: E402


def main():
    llm = LLMClient()

    print("=" * 56)
    print("① 代理 (34.97...:8000) 上真实可用的模型 id")
    print("   GROK_BASE_URL =", os.getenv("GROK_BASE_URL"))
    print("=" * 56)
    try:
        models = llm.list_proxy_models()
        if models:
            for m in models:
                print("   •", m)
        else:
            print("   (返回空列表)")
    except Exception as e:  # noqa: BLE001
        print("   获取失败:", e)

    print()
    print("=" * 56)
    print("② Gemini 直连密钥自检")
    print("=" * 56)
    keys = llm.gemini_keys
    if not keys:
        print("   .env 里没有 GEMINI_API_KEYS")
    for i, k in enumerate(keys):
        masked = k[:10] + "…" + k[-4:]
        try:
            status, body = llm.gemini_raw(k)
            if status == 200:
                names = [m["name"].replace("models/", "")
                         for m in __import__("json").loads(body).get("models", [])]
                print(f"   key#{i} {masked}: ✅ 有效, 可用模型:")
                for n in names:
                    if "gemini" in n:
                        print("       •", n)
            else:
                print(f"   key#{i} {masked}: ❌ HTTP {status}")
                print("       报错:", body[:200])
        except Exception as e:  # noqa: BLE001
            print(f"   key#{i} {masked}: 请求异常 {e}")

    print()
    print("=" * 56)
    print("③ grok 实际调用自测 (用 .env 的 GROK_MODEL)")
    print("   当前 GROK_MODEL =", os.getenv("GROK_MODEL"))
    print("=" * 56)
    try:
        out = llm._grok(llm.grok_model, "你是测试助手", "回复 OK", 0.0, 10)
        print("   ✅ grok 响应:", out.strip()[:50])
    except Exception as e:  # noqa: BLE001
        print("   ❌ grok 调用失败:", str(e)[:200])
        print("   → 把上面①里的某个 id 填到 .env 的 GROK_MODEL 再试")


if __name__ == "__main__":
    main()
