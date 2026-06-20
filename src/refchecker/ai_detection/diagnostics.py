"""In-memory ring buffer of recent AI-detection runs, for the Settings debugger.

Every call to :func:`run_detection` records one event here — backend used,
outcome band/score, abstain/error reason, and duration — so a user (or we) can
see *why* detection produced no band (e.g. ``unavailable: deps_not_installed``,
``inconclusive: too_short``) without digging through server logs. Bounded and
thread-safe; holds no manuscript text (only metadata).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Deque, Dict, List

_CAP = 60
_lock = threading.Lock()
_events: Deque[Dict[str, object]] = deque(maxlen=_CAP)


def record(event: Dict[str, object]) -> None:
    """Append one detection event (a small, text-free metadata dict)."""
    ev = dict(event)
    ev.setdefault("ts", time.strftime("%Y-%m-%d %H:%M:%S"))
    with _lock:
        _events.append(ev)


def events() -> List[Dict[str, object]]:
    """Recent events, newest first."""
    with _lock:
        return list(reversed(_events))


def clear() -> None:
    with _lock:
        _events.clear()
