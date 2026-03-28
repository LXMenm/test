"""轻量级兼容回退命中统计（进程内）。"""

from __future__ import annotations

from collections import Counter
from threading import Lock
from typing import Dict

_LOCK = Lock()
_COUNTER: Counter[str] = Counter()


def record_fallback_hit(name: str) -> None:
    key = str(name or "").strip()
    if not key:
        return
    with _LOCK:
        _COUNTER[key] += 1


def get_fallback_stats() -> Dict[str, int]:
    with _LOCK:
        return dict(sorted(_COUNTER.items(), key=lambda item: item[0]))


def reset_fallback_stats() -> None:
    with _LOCK:
        _COUNTER.clear()
