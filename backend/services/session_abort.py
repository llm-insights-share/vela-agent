"""Process-local cooperative abort flags for Agent sessions.

Keyed by session_id only — works for every Agent. Compatible with FastAPI
BackgroundTasks that run asyncio.run() on a new event loop (threading.Event).
"""

from __future__ import annotations

import threading
from typing import Dict

_lock = threading.Lock()
_events: Dict[str, threading.Event] = {}


def request_abort(session_id: str) -> None:
    sid = (session_id or "").strip()
    if not sid:
        return
    with _lock:
        ev = _events.get(sid)
        if ev is None:
            ev = threading.Event()
            _events[sid] = ev
        ev.set()


def is_aborted(session_id: str) -> bool:
    sid = (session_id or "").strip()
    if not sid:
        return False
    with _lock:
        ev = _events.get(sid)
        return bool(ev and ev.is_set())


def clear_abort(session_id: str) -> None:
    sid = (session_id or "").strip()
    if not sid:
        return
    with _lock:
        ev = _events.pop(sid, None)
        if ev is not None:
            ev.clear()
