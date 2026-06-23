"""Item 标准结构与构造工具。"""
from __future__ import annotations

import hashlib
import time

from ..dedup import fingerprint, normalize_title


def make_item(topic_id: str, source: str, title: str, url: str,
              content: str = "", published_at: str = "", content_full: str = "",
              id_seed: str = "") -> dict:
    # id_seed 提供时直接哈希(绕过 URL 规整去掉 fragment), 让"同一仓库不同周的激增"成为不同条目
    item_id = (hashlib.sha1(id_seed.encode("utf-8")).hexdigest() if id_seed
               else fingerprint(url))
    return {
        "id": item_id,
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
