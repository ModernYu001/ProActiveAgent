"""Item 标准结构与构造工具。"""
from __future__ import annotations

import time

from ..dedup import fingerprint, normalize_title


def make_item(topic_id: str, source: str, title: str, url: str,
              content: str = "", published_at: str = "", content_full: str = "") -> dict:
    return {
        "id": fingerprint(url),
        "topic_id": topic_id,
        "source": source,
        "title": (title or "").strip(),
        "url": url,
        "content": (content or "").strip(),
        "content_full": (content_full or "").strip(),   # 正文(供第二段深判), 不入库
        "published_at": published_at,
        "fetched_at": time.time(),
        "norm_title": normalize_title(title),
    }
