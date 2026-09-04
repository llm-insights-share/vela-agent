"""In-process span buffer for Postgres dual-write (OpenInference)."""

from __future__ import annotations

import contextvars
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.monitor.openinference_attrs import legacy_kind_for_oi, oi_kind_from_legacy

_turn_ctx: contextvars.ContextVar[Optional["TurnTraceContext"]] = contextvars.ContextVar(
    "vela_turn_trace_ctx", default=None
)

try:
    from opentelemetry.sdk.trace import SpanProcessor as _OtelSpanProcessor
except ImportError:  # pragma: no cover
    _OtelSpanProcessor = object  # type: ignore[misc, assignment]


@dataclass
class TurnTraceContext:
    run_id: str
    session_id: str = ""
    agent_id: str = ""
    user_id: str = ""
    spans: List[Dict[str, Any]] = field(default_factory=list)
    otel_enabled: bool = True


def get_turn_context() -> Optional[TurnTraceContext]:
    return _turn_ctx.get()


def start_turn_context(
    *,
    run_id: str,
    session_id: str = "",
    agent_id: str = "",
    user_id: str = "",
    otel_enabled: bool = True,
) -> TurnTraceContext:
    ctx = TurnTraceContext(
        run_id=run_id,
        session_id=session_id,
        agent_id=agent_id,
        user_id=user_id,
        otel_enabled=otel_enabled,
    )
    _turn_ctx.set(ctx)
    return ctx


def end_turn_context() -> Optional[TurnTraceContext]:
    ctx = _turn_ctx.get()
    _turn_ctx.set(None)
    return ctx


def append_span_record(record: Dict[str, Any]) -> None:
    ctx = _turn_ctx.get()
    if ctx is None:
        return
    ctx.spans.append(record)


def _ns_to_dt(ns: Optional[int]) -> Optional[datetime]:
    if not ns:
        return None
    try:
        return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def serialize_readable_span(span: Any) -> Dict[str, Any]:
    """Convert OTEL ReadableSpan to a plain dict for Postgres projection."""
    attrs = dict(getattr(span, "attributes", None) or {})
    oi_kind = str(attrs.get("openinference.span.kind") or "")
    if not oi_kind:
        oi_kind = oi_kind_from_legacy(str(getattr(span, "kind", "") or "internal"))
    legacy = legacy_kind_for_oi(oi_kind)

    status = getattr(span, "status", None)
    status_code = "OK"
    if status is not None:
        code = getattr(status, "status_code", None)
        name = getattr(code, "name", None) or str(code or "")
        if name in ("ERROR", "StatusCode.ERROR"):
            status_code = "ERROR"

    start_ns = getattr(span, "start_time", None)
    end_ns = getattr(span, "end_time", None)
    duration_ms = 0
    if start_ns and end_ns and end_ns >= start_ns:
        duration_ms = int((end_ns - start_ns) / 1e6)

    ctx = span.get_span_context() if hasattr(span, "get_span_context") else None
    parent = getattr(span, "parent", None)
    parent_span_id = ""
    if parent is not None:
        parent_span_id = format(getattr(parent, "span_id", 0) or 0, "016x")
        if parent_span_id == "0000000000000000":
            parent_span_id = ""

    span_id = format(getattr(ctx, "span_id", 0) or 0, "016x") if ctx else ""
    trace_id = format(getattr(ctx, "trace_id", 0) or 0, "032x") if ctx else ""

    return {
        "span_id": span_id,
        "trace_id": trace_id,
        "parent_span_id": parent_span_id,
        "name": getattr(span, "name", "") or "",
        "kind": legacy,
        "oi_kind": oi_kind,
        "attrs_json": dict(attrs),
        "duration_ms": duration_ms,
        "status": status_code,
        "started_at": _ns_to_dt(start_ns),
        "ended_at": _ns_to_dt(end_ns),
    }


class BufferSpanProcessor(_OtelSpanProcessor):
    """OTEL SpanProcessor that mirrors ended spans into TurnTraceContext."""

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        return

    def on_end(self, span: Any) -> None:
        try:
            record = serialize_readable_span(span)
            append_span_record(record)
        except Exception:
            return

    def shutdown(self) -> None:
        return

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


def now_monotonic_ns() -> int:
    return time.time_ns()
