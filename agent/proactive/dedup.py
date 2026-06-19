"""去重：精确指纹 + 标题模糊相似度。避免同一事件被反复推送。

MVP 用标题模糊匹配；产品化可升级为向量语义去重(见架构文档 §3.3)。
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse, urlunparse

try:
    from rapidfuzz import fuzz
    _HAVE_RAPIDFUZZ = True
except ImportError:  # 退化到标准库
    from difflib import SequenceMatcher
    _HAVE_RAPIDFUZZ = False

_TRACKING = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
             "gclid", "fbclid", "ref", "ref_src", "spm"}


def canonical_url(url: str) -> str:
    try:
        p = urlparse(url)
        query = "&".join(
            kv for kv in p.query.split("&")
            if kv and kv.split("=")[0].lower() not in _TRACKING
        )
        return urlunparse((p.scheme, p.netloc.lower(), p.path.rstrip("/"), "", query, ""))
    except Exception:
        return url


def fingerprint(url: str) -> str:
    return hashlib.sha1(canonical_url(url).encode("utf-8")).hexdigest()


def normalize_title(title: str) -> str:
    t = (title or "").lower()
    t = re.sub(r"[^\w一-鿿 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _ratio(a: str, b: str) -> float:
    if _HAVE_RAPIDFUZZ:
        return fuzz.token_set_ratio(a, b)
    return SequenceMatcher(None, a, b).ratio() * 100


def is_duplicate_title(norm_title: str, seen: list[tuple[str, str]], threshold: float) -> bool:
    """seen 是 [(id, norm_title)]，来自最近 N 天的已见条目。"""
    if not norm_title:
        return False
    for _id, prev in seen:
        if _ratio(norm_title, prev) >= threshold:
            return True
    return False
