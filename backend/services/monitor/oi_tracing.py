"""Helpers to create OpenInference-instrumented OTEL spans."""

from __future__ import annotations

import contextlib
from typing import Any, Dict, Iterator, Optional

from services.monitor.openinference_attrs import otel_attribute_pairs
from services.monitor.otel_setup import get_tracer, is_otel_enabled


@contextlib.contextmanager
def oi_span(
    name: str,
    attrs: Optional[Dict[str, Any]] = None,
    *,
    record_exception: bool = True,
) -> Iterator[Any]:
    """Start an OTEL span with OpenInference attributes (no-op if disabled)."""
    if not is_otel_enabled():
        yield None
        return

    try:
        from opentelemetry import trace
        from opentelemetry.trace import Status, StatusCode
    except ImportError:
        yield None
        return

    tracer = get_tracer()
    pairs = otel_attribute_pairs(attrs or {})
    with tracer.start_as_current_span(name) as span:
        if pairs:
            span.set_attributes(pairs)
        try:
            yield span
        except Exception as e:
            if span is not None and record_exception:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)[:500]))
            raise


def set_span_attrs(span: Any, attrs: Dict[str, Any]) -> None:
    if span is None or not attrs:
        return
    try:
        span.set_attributes(otel_attribute_pairs(attrs))
    except Exception:
        pass


def mark_span_error(span: Any, message: str = "") -> None:
    if span is None:
        return
    try:
        from opentelemetry.trace import Status, StatusCode

        span.set_status(Status(StatusCode.ERROR, (message or "")[:500]))
    except Exception:
        pass


def mark_span_ok(span: Any) -> None:
    if span is None:
        return
    try:
        from opentelemetry.trace import Status, StatusCode

        span.set_status(Status(StatusCode.OK))
    except Exception:
        pass
