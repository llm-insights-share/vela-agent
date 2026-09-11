"""In-memory session event bus for SSE token / status streaming."""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Dict, Optional, Set


class SessionEventBus:
    def __init__(self) -> None:
        self._subs: Dict[str, Set[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, session_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        async with self._lock:
            self._subs.setdefault(session_id, set()).add(q)
        return q

    async def unsubscribe(self, session_id: str, q: asyncio.Queue) -> None:
        async with self._lock:
            bucket = self._subs.get(session_id)
            if not bucket:
                return
            bucket.discard(q)
            if not bucket:
                self._subs.pop(session_id, None)

    def publish(self, session_id: str, event: Dict[str, Any]) -> None:
        """Non-blocking publish; drop for full queues / no subscribers."""
        if not session_id:
            return
        bucket = self._subs.get(session_id)
        if not bucket:
            return
        payload = dict(event)
        for q in list(bucket):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                try:
                    _ = q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    pass

    def publish_sync(self, session_id: str, event: Dict[str, Any]) -> None:
        self.publish(session_id, event)


session_event_bus = SessionEventBus()


def format_sse(event: Dict[str, Any]) -> str:
    data = json.dumps(event, ensure_ascii=False, default=str)
    return f"data: {data}\n\n"


async def sse_event_stream(
    session_id: str,
    *,
    heartbeat_seconds: float = 15.0,
) -> AsyncIterator[str]:
    q = await session_event_bus.subscribe(session_id)
    try:
        yield format_sse({"type": "status", "status": "subscribed", "session_id": session_id})
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=heartbeat_seconds)
            except asyncio.TimeoutError:
                yield format_sse({"type": "ping"})
                continue
            yield format_sse(event)
            et = event.get("type")
            if et in ("done", "error", "hitl"):
                break
            if et == "status" and event.get("status") in (
                "ACTIVE",
                "ERROR",
                "CLOSED",
                "HITL_WAIT",
            ):
                break
    finally:
        await session_event_bus.unsubscribe(session_id, q)


def publish_thinking_delta(
    session_id: str,
    *,
    text: str,
    field: str = "reasoning",
    turn: Optional[int] = None,
) -> None:
    if not text:
        return
    session_event_bus.publish(
        session_id,
        {
            "type": "thinking_delta",
            "field": field,
            "text": text,
            "turn": turn,
        },
    )


def publish_story_patch(session_id: str, story: Any) -> None:
    if story is None:
        return
    session_event_bus.publish(
        session_id,
        {"type": "story_patch", "story": story},
    )


def publish_status(session_id: str, status: str, **extra: Any) -> None:
    payload = {"type": "status", "status": status, **extra}
    session_event_bus.publish(session_id, payload)
