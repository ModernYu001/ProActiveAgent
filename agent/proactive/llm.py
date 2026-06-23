"""统一 LLM 客户端：grok(OpenAI 兼容代理) + Gemini(原生 API)。

★ 配额感知：每个模型/每个 key 有每日上限，本地按天计数。
  调用前自动挑"今天还有额度"的 key/模型；额度用尽则按 fallback 链降级。
  这样不会在你紧张的免费配额上爆掉。

配额(每个 key/天, 在 config.yaml > quotas 配置)：
  gemini-3.1-flash-lite: 300   gemini-2.5-flash: 10   gemini-3-flash: 10
  grok: 40 (单 key)
两个 Gemini key → flash-lite 实际每天约 600 次，配合"批量判断"足够高频盯梢。
"""
from __future__ import annotations

import itertools
import json
import os
import re
import time
from datetime import datetime

import requests

from . import store


class LLMError(RuntimeError):
    pass


class QuotaExhausted(LLMError):
    pass


class UpstreamError(LLMError):   # 代理上游返回错误(如 403): 不可重试, 立即失败
    pass


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


class LLMClient:
    def __init__(self, cfg: dict | None = None):
        keys = os.getenv("GEMINI_API_KEYS", "").strip()
        self.gemini_keys = [k.strip() for k in keys.split(",") if k.strip()]

        self.grok_base = os.getenv("GROK_BASE_URL", "").rstrip("/")
        self.grok_key = os.getenv("GROK_API_KEY", "")
        self.grok_model = os.getenv("GROK_MODEL", "grok")

        # 配额表：{provider: {model: per_key_daily_limit}}；None=不限(用于自测脚本)
        self.quotas = (cfg or {}).get("quotas") if cfg else None
        # 每分钟限频(RPM){provider:{model:rpm}}, 设计值取实际的 ~2/3 留余量
        self.rate_limits = (cfg or {}).get("rate_limits", {}) if cfg else {}
        self._last_call = {}   # (provider, model, key_idx) -> 上次调用时间戳
        self.timeout = 60

    def _throttle(self, provider: str, model: str, key_idx: int):
        """按 RPM 限频：与上次同 (model,key) 调用间隔不足则 sleep 补足。"""
        rpm = self.rate_limits.get(provider, {}).get(model)
        if not rpm:
            return
        min_interval = 60.0 / rpm
        k = (provider, model, key_idx)
        wait = min_interval - (time.time() - self._last_call.get(k, 0.0))
        if wait > 0:
            time.sleep(wait)
        self._last_call[k] = time.time()

    # ---------- 配额 ----------
    def _limit(self, provider: str, model: str) -> int | None:
        if not self.quotas:
            return None
        return self.quotas.get(provider, {}).get(model)

    def _pick_key(self, provider: str, model: str, n_keys: int) -> int:
        """返回今天还有额度的 key 下标；都用尽则抛 QuotaExhausted。"""
        limit = self._limit(provider, model)
        day = _today()
        with store.connect() as conn:
            counts = [store.get_usage(conn, day, provider, model, i) for i in range(n_keys)]
        if limit is None:
            # 不限额：选用得最少的 key 做负载均衡
            return min(range(n_keys), key=lambda i: counts[i])
        candidates = [(counts[i], i) for i in range(n_keys) if counts[i] < limit]
        if not candidates:
            raise QuotaExhausted(f"{provider}:{model} 今日 {n_keys} 个 key 配额均已用尽({limit}/key)")
        return min(candidates)[1]

    def _count(self, provider: str, model: str, key_idx: int):
        with store.connect() as conn:
            store.incr_usage(conn, _today(), provider, model, key_idx)

    # ---------- 对外主入口 ----------
    def complete(self, route: dict, system: str, user: str,
                 temperature: float = 0.2, max_tokens: int = 1024) -> str:
        provider = route.get("provider", "gemini")
        chain = [route["preferred"]] + list(route.get("fallback", []))
        errors = []

        for model in chain:
            try:
                if provider == "grok":
                    return self._grok(model, system, user, temperature, max_tokens)
                return self._gemini(model, system, user, temperature, max_tokens)
            except QuotaExhausted as e:
                errors.append(str(e))
            except Exception as e:  # noqa: BLE001
                errors.append(f"{provider}:{model} -> {e}")

        fb_provider = route.get("fallback_provider")
        if fb_provider and fb_provider != provider:
            for model in route.get("fallback_models", []):   # 跨 provider 专用列表
                try:
                    if fb_provider == "grok":
                        return self._grok(model, system, user, temperature, max_tokens)
                    return self._gemini(model, system, user, temperature, max_tokens)
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{fb_provider}:{model} -> {e}")

        raise LLMError("所有模型均失败/配额用尽: " + " | ".join(errors))

    def complete_json(self, route: dict, system: str, user: str, **kw) -> dict:
        return _extract_json(self.complete(route, system, user, **kw))

    # ---------- Gemini 原生 ----------
    def _gemini(self, model: str, system: str, user: str,
                temperature: float, max_tokens: int) -> str:
        if not self.gemini_keys:
            raise LLMError("未配置 GEMINI_API_KEYS")
        key_idx = self._pick_key("gemini", model, len(self.gemini_keys))
        key = self.gemini_keys[key_idx]
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model}:generateContent?key={key}")
        body = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
        }
        # 429(限频/瞬时) 与网络异常 → 等待重试; 重试耗尽再标记当日用尽并回退
        backoffs = [8, 16, 30, 60]
        for attempt in range(len(backoffs) + 1):
            self._throttle("gemini", model, key_idx)   # 先按 RPM 节流
            try:
                r = requests.post(url, json=body, timeout=self.timeout)
            except Exception as e:  # noqa: BLE001 网络瞬时异常 → 重试
                if attempt < len(backoffs):
                    print(f"[gemini] {model} 网络异常, 等待 {backoffs[attempt]}s 重试…")
                    time.sleep(backoffs[attempt])
                    continue
                raise LLMError(f"gemini 网络多次失败: {e}")
            if r.status_code == 200:
                self._count("gemini", model, key_idx)
                data = r.json()
                try:
                    return data["candidates"][0]["content"]["parts"][0]["text"]
                except (KeyError, IndexError):
                    raise LLMError(f"无法解析 Gemini 响应: {json.dumps(data)[:200]}")
            if r.status_code == 429:
                if attempt < len(backoffs):
                    print(f"[gemini] {model} 429 限流, 等待 {backoffs[attempt]}s 重试…")
                    time.sleep(backoffs[attempt])
                    continue
                self._mark_exhausted("gemini", model, key_idx)   # 多次仍 429=当日用尽
                raise QuotaExhausted(f"gemini:{model} key#{key_idx} 429 重试耗尽")
            raise LLMError(f"HTTP {r.status_code}: {r.text[:200]}")
        raise LLMError("gemini 未知失败")

    def _mark_exhausted(self, provider: str, model: str, key_idx: int):
        limit = self._limit(provider, model) or 9999
        day = _today()
        with store.connect() as conn:
            cur = store.get_usage(conn, day, provider, model, key_idx)
            for _ in range(max(0, limit - cur)):
                store.incr_usage(conn, day, provider, model, key_idx)

    # ---------- grok / OpenAI 兼容 ----------
    def _grok(self, model: str, system: str, user: str,
              temperature: float, max_tokens: int) -> str:
        if not self.grok_base:
            raise LLMError("未配置 GROK_BASE_URL")
        self._pick_key("grok", "grok", 1)  # 配额检查(单 key)
        url = f"{self.grok_base}/chat/completions"
        headers = {"Authorization": f"Bearer {self.grok_key}", "Content-Type": "application/json"}
        # 默认流式：该代理非流式会返回空响应(Expecting value)。GROK_STREAM=false 可关。
        stream = os.getenv("GROK_STREAM", "true").lower() == "true"
        body = {
            "model": model if model != "grok" else self.grok_model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": temperature, "max_tokens": max_tokens, "stream": stream,
        }
        # 空响应自动重试：最多 N 次, 拿到非空即返回。空响应不计配额(仅成功才 _count)。
        attempts = int(os.getenv("GROK_MAX_ATTEMPTS", "3"))
        last = "空响应"
        for i in range(max(1, attempts)):
            try:
                if stream:
                    text = self._grok_stream(url, headers, body)
                else:
                    r = requests.post(url, json=body, headers=headers, timeout=self.timeout)
                    if r.status_code != 200:
                        raise LLMError(f"HTTP {r.status_code}: {r.text[:200]}")
                    text = r.json()["choices"][0]["message"]["content"]
                if text and text.strip():
                    self._count("grok", "grok", 0)   # 仅非空成功才计 1 次
                    return text
                last = "grok 返回为空"
                if i + 1 < attempts:
                    print(f"[grok] 第 {i+1} 次空响应, 重试…")
            except LLMError:
                raise                                 # HTTP 错误不重试, 直接走回退
            except Exception as e:  # noqa: BLE001     # 网络等瞬时异常: 重试
                last = str(e)
        raise LLMError(f"grok 连续 {attempts} 次未取到内容: {last}")

    def _grok_stream(self, url: str, headers: dict, body: dict) -> str:
        """解析 OpenAI 风格 SSE 流，拼出完整文本。"""
        r = requests.post(url, json=body, headers=headers, timeout=self.timeout, stream=True)
        if r.status_code != 200:
            raise LLMError(f"HTTP {r.status_code}: {r.text[:200]}")
        parts = []
        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue
            if line.startswith("data:"):
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                # 流里裹着的上游错误(如 403): 立即抛出, 不当空响应去重试
                if isinstance(obj, dict) and obj.get("error"):
                    err = obj["error"]
                    msg = err.get("message") if isinstance(err, dict) else str(err)
                    raise UpstreamError(f"grok 上游错误: {msg}")
                try:
                    piece = obj["choices"][0].get("delta", {}).get("content") or ""
                    if piece:
                        parts.append(piece)
                except (KeyError, IndexError):
                    continue
        return "".join(parts)

    def list_gemini_models(self) -> list[str]:
        if not self.gemini_keys:
            return []
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={self.gemini_keys[0]}"
        r = requests.get(url, timeout=self.timeout)
        r.raise_for_status()
        return [m["name"].replace("models/", "") for m in r.json().get("models", [])]

    def gemini_raw(self, key: str):
        """返回 (status_code, body_text)，用于诊断密钥/端点问题。"""
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
        r = requests.get(url, timeout=self.timeout)
        return r.status_code, r.text

    def list_proxy_models(self) -> list[str]:
        """列出代理(34.97...:8000)上真实可用的模型 id（含 grok / 可能含 gemini）。"""
        if not self.grok_base:
            return []
        url = f"{self.grok_base}/models"
        r = requests.get(url, headers={"Authorization": f"Bearer {self.grok_key}"},
                         timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        return [m.get("id") for m in data.get("data", data if isinstance(data, list) else [])]


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    # 1) 优先取 ```json ... ``` 代码块内容
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    # 2) 截取第一个 { 到最后一个 }
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        text = text[start:end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 3) 去掉尾随逗号再试
    cleaned = re.sub(r",(\s*[}\]])", r"\1", text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # 4) 截断兜底：只抢救 items 数组里完整的对象
    objs = re.findall(r"\{[^{}]*\}", cleaned)
    if objs:
        salvaged = "[" + ",".join(objs) + "]"
        try:
            return {"items": json.loads(salvaged), "results": json.loads(salvaged)}
        except json.JSONDecodeError:
            pass
    raise json.JSONDecodeError("无法解析为 JSON", text[:80], 0)
