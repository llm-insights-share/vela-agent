"""Tests for session event bus and SSE formatting."""

import asyncio
import json

import pytest

from services.session_events import (
    SessionEventBus,
    format_sse,
    publish_thinking_delta,
    session_event_bus,
)


def test_format_sse_json():
    out = format_sse({"type": "ping"})
    assert out.startswith("data: ")
    assert out.endswith("\n\n")
    payload = json.loads(out[len("data: "):-2])
    assert payload["type"] == "ping"


@pytest.mark.asyncio
async def test_bus_publish_to_subscribers():
    bus = SessionEventBus()
    q1 = await bus.subscribe("s1")
    q2 = await bus.subscribe("s1")
    bus.publish("s1", {"type": "thinking_delta", "text": "hi"})
    e1 = await asyncio.wait_for(q1.get(), timeout=1)
    e2 = await asyncio.wait_for(q2.get(), timeout=1)
    assert e1["text"] == "hi"
    assert e2["text"] == "hi"
    await bus.unsubscribe("s1", q1)
    await bus.unsubscribe("s1", q2)


def test_publish_no_subscribers_ok():
    # Must not raise
    publish_thinking_delta("no-such-session", text="x")
    session_event_bus.publish("no-such-session", {"type": "ping"})


@pytest.mark.asyncio
async def test_queue_full_drops_oldest():
    bus = SessionEventBus()
    q = await bus.subscribe("full")
    # Fill beyond maxsize=256
    for i in range(300):
        bus.publish("full", {"type": "thinking_delta", "text": str(i)})
    # Should still be able to drain without hanging
    got = 0
    while not q.empty():
        await q.get()
        got += 1
        if got > 300:
            break
    assert got <= 256
    await bus.unsubscribe("full", q)


def test_accumulate_stream_chunks_logic():
    """Mirror model_provider stream accumulation for reasoning/content."""
    reasoning_parts = []
    content_parts = []
    chunks = [
        {"choices": [{"delta": {"reasoning_content": "想"}}]},
        {"choices": [{"delta": {"reasoning_content": "法"}}]},
        {"choices": [{"delta": {"content": "答"}}]},
        {"choices": [{"delta": {"content": "案"}}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ]
    for chunk in chunks:
        delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
        rc = delta.get("reasoning_content") or delta.get("thinking")
        if isinstance(rc, str) and rc:
            reasoning_parts.append(rc)
        ct = delta.get("content")
        if isinstance(ct, str) and ct:
            content_parts.append(ct)
    assert "".join(reasoning_parts) == "想法"
    assert "".join(content_parts) == "答案"
