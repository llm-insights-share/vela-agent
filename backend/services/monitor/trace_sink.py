"""Project session telemetry + OpenInference span buffer into agent_runs + agent_spans."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from models import AgentRun, AgentRunStatus, AgentScore, AgentSpan, gen_uuid, now_utc
from services.monitor.openinference_attrs import (
    attrs_for_llm_call,
    legacy_kind_for_oi,
    oi_kind_from_legacy,
)
from services.monitor.sampling import redact_span_attrs, should_sample_content
from services.monitor.span_buffer import get_turn_context


def _parse_dt(val: Any) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _usage_from_llm_calls(llm_calls: List[Dict[str, Any]]) -> tuple[int, int]:
    tin, tout = 0, 0
    for call in llm_calls or []:
        usage = ((call.get("output") or {}).get("usage") or {})
        tin += int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        tout += int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    return tin, tout


def _usage_from_oi_spans(spans: List[Dict[str, Any]]) -> tuple[int, int]:
    tin, tout = 0, 0
    for s in spans or []:
        attrs = s.get("attrs_json") or {}
        if (s.get("oi_kind") or attrs.get("openinference.span.kind")) != "LLM":
            continue
        tin += int(attrs.get("llm.token_count.prompt") or 0)
        tout += int(attrs.get("llm.token_count.completion") or 0)
    return tin, tout


def _count_tool_calls(llm_calls: List[Dict[str, Any]], run_metrics: Dict[str, Any]) -> int:
    n = int(run_metrics.get("tool_rounds") or 0)
    if n:
        return n
    total = 0
    for call in llm_calls or []:
        tcs = ((call.get("output") or {}).get("tool_calls") or [])
        total += len(tcs)
    return total


def _infer_status(
    *,
    result: Dict[str, Any],
    story_status: str = "done",
    success: bool = True,
) -> str:
    if result.get("pending_approval_id") or result.get("session_status") == "HITL_WAIT":
        return AgentRunStatus.HITL_WAIT.value
    if result.get("aborted"):
        return AgentRunStatus.ABORT.value
    rm = result.get("run_metrics") or {}
    if rm.get("timed_out"):
        return AgentRunStatus.TIMEOUT.value
    if success is False or story_status in ("error", "failed"):
        return AgentRunStatus.ERROR.value
    if not (result.get("content") or "").strip() and story_status == "done":
        return AgentRunStatus.ERROR.value
    return AgentRunStatus.SUCCESS.value


def _spans_from_oi_buffer(run_id: str, buffered: List[Dict[str, Any]]) -> List[AgentSpan]:
    """Map OpenInference buffered spans into AgentSpan rows."""
    spans: List[AgentSpan] = []
    seen: set = set()
    for rec in buffered or []:
        sid = rec.get("span_id") or gen_uuid()
        if sid in seen:
            continue
        seen.add(sid)
        attrs = dict(rec.get("attrs_json") or {})
        oi_kind = rec.get("oi_kind") or attrs.get("openinference.span.kind") or ""
        if oi_kind and "openinference.span.kind" not in attrs:
            attrs["openinference.span.kind"] = oi_kind
        kind = rec.get("kind") or legacy_kind_for_oi(str(oi_kind or "CHAIN"))
        started = rec.get("started_at")
        if isinstance(started, str):
            started = _parse_dt(started)
        spans.append(
            AgentSpan(
                span_id=sid,
                run_id=run_id,
                parent_span_id=rec.get("parent_span_id") or "",
                name=rec.get("name") or "",
                kind=kind,
                attrs_json=attrs,
                duration_ms=int(rec.get("duration_ms") or 0),
                status=rec.get("status") or "OK",
                started_at=started or now_utc(),
            )
        )
    return spans


def _spans_from_llm_calls(
    run_id: str,
    llm_calls: List[Dict[str, Any]],
    *,
    include_planned_tools: bool = False,
) -> List[AgentSpan]:
    """Fallback projection when OTEL buffer is empty. Prefer OpenInference attrs on LLM spans."""
    spans: List[AgentSpan] = []
    root_span = gen_uuid()
    spans.append(
        AgentSpan(
            span_id=root_span,
            run_id=run_id,
            parent_span_id="",
            name="agent.run",
            kind="agent",
            attrs_json={
                "openinference.span.kind": "AGENT",
                "llm_call_count": len(llm_calls or []),
            },
            duration_ms=0,
            status="OK",
        )
    )
    for call in llm_calls or []:
        dur = int(call.get("duration_ms") or 0)
        output = call.get("output") or {}
        inp = call.get("input") or {}
        oi_attrs = attrs_for_llm_call(
            model_name=call.get("model_name") or "",
            messages=inp.get("messages") or [],
            tools=inp.get("tools"),
            max_tokens=inp.get("max_tokens"),
            temperature=inp.get("temperature"),
            output_content=output.get("content"),
            output_tool_calls=output.get("tool_calls"),
            usage=output.get("usage") or {},
            raw_error=output.get("raw_error"),
            source=call.get("source"),
        )
        oi_attrs["call_id"] = call.get("call_id")
        oi_attrs["seq"] = call.get("seq")
        spans.append(
            AgentSpan(
                span_id=gen_uuid(),
                run_id=run_id,
                parent_span_id=root_span,
                name=f"chat.{call.get('source') or 'llm'}",
                kind="chat",
                attrs_json=oi_attrs,
                duration_ms=dur,
                status="OK" if output and not output.get("raw_error") else "ERROR",
                started_at=_parse_dt(call.get("created_at")) or now_utc(),
            )
        )
        # Planned tool calls from LLM output are NOT real TOOL spans (OpenInference).
        # Only include when explicitly requested for legacy debug.
        if include_planned_tools:
            for tc in output.get("tool_calls") or []:
                fn = tc.get("function") or {}
                spans.append(
                    AgentSpan(
                        span_id=gen_uuid(),
                        run_id=run_id,
                        parent_span_id=root_span,
                        name=f"execute_tool.{fn.get('name') or 'unknown'}",
                        kind="execute_tool",
                        attrs_json={
                            "openinference.span.kind": "TOOL",
                            "tool.name": fn.get("name") or "unknown",
                            "tool_call_id": tc.get("id"),
                            "tool.parameters": fn.get("arguments"),
                        },
                        duration_ms=0,
                        status="OK",
                    )
                )
    return spans


def _spans_from_story(run_id: str, story: Dict[str, Any]) -> List[AgentSpan]:
    spans: List[AgentSpan] = []
    for phase in story.get("phases") or []:
        for step in phase.get("steps") or []:
            stype = step.get("type") or "step"
            spans.append(
                AgentSpan(
                    span_id=gen_uuid(),
                    run_id=run_id,
                    parent_span_id="",
                    name=f"story.{stype}",
                    kind="internal",
                    attrs_json={
                        "openinference.span.kind": "CHAIN",
                        "phase": phase.get("id"),
                        "step": step,
                    },
                    duration_ms=0,
                    status="OK",
                )
            )
    return spans


def record_agent_run(
    db: Session,
    *,
    session,
    agent,
    result: Dict[str, Any],
    story_status: str = "done",
    success: bool = True,
    started_at: Optional[datetime] = None,
    guard_events: Optional[List[Dict[str, Any]]] = None,
) -> Optional[str]:
    """Append one AgentRun. Prefer OpenInference buffer spans when present."""
    if not session or not agent:
        return None

    turn = get_turn_context()
    run_id = (turn.run_id if turn and turn.run_id else None) or gen_uuid()
    llm_calls = list(session.llm_calls or [])
    run_metrics = dict(result.get("run_metrics") or {})
    execution_story = result.get("execution_story") or {}
    status = _infer_status(result=result, story_status=story_status, success=success)
    elapsed = int(run_metrics.get("elapsed_ms") or 0)
    if started_at is not None and not isinstance(started_at, datetime):
        started_at = _parse_dt(started_at)

    oi_spans = list(turn.spans) if turn and turn.spans else []
    if oi_spans:
        token_in, token_out = _usage_from_oi_spans(oi_spans)
        if token_in == 0 and token_out == 0:
            token_in, token_out = _usage_from_llm_calls(llm_calls)
        tool_calls = sum(
            1
            for s in oi_spans
            if (s.get("oi_kind") or (s.get("attrs_json") or {}).get("openinference.span.kind"))
            == "TOOL"
        )
        if not tool_calls:
            tool_calls = _count_tool_calls(llm_calls, run_metrics)
    else:
        token_in, token_out = _usage_from_llm_calls(llm_calls)
        if token_in == 0 and token_out == 0:
            turn_tokens = int(result.get("tokens_used") or 0)
            if turn_tokens > 0:
                token_out = turn_tokens
        tool_calls = _count_tool_calls(llm_calls, run_metrics)

    summary = (execution_story.get("summary") or "")[:500]
    if not summary:
        summary = (result.get("content") or "")[:200]

    messages = session.messages or []
    msg_index = len(messages) - 1
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "assistant":
            msg_index = i
            break

    guard_blocked = any(e.get("decision") == "block" for e in (guard_events or []))
    keep_full = should_sample_content(status=status, guard_blocked=guard_blocked)

    # Prefer W3C trace id from OI buffer
    trace_id = getattr(session, "trace_id", "") or ""
    if oi_spans:
        for s in oi_spans:
            if s.get("trace_id"):
                trace_id = s["trace_id"]
                break

    run = AgentRun(
        run_id=run_id,
        session_id=session.session_id,
        agent_id=getattr(agent, "agent_id", "") or session.agent_id,
        version_id=getattr(session, "version_id", None),
        trace_id=trace_id,
        caller_id=getattr(session, "caller_id", "") or "",
        status=status,
        started_at=started_at or now_utc(),
        ended_at=now_utc(),
        elapsed_ms=elapsed,
        token_in=token_in,
        token_out=token_out,
        tool_calls=tool_calls,
        execution_mode=result.get("execution_mode") or run_metrics.get("execution_mode") or "",
        error_code=(result.get("error_code") or "") if status == AgentRunStatus.ERROR.value else "",
        summary=summary,
        message_index=msg_index,
        attrs_json={
            "run_metrics": run_metrics,
            "guard_events": guard_events or [],
            "tokens_used_turn": result.get("tokens_used"),
            "openinference": True if oi_spans else False,
            "ab_experiment_id": getattr(session, "ab_experiment_id", None),
            "ab_arm": getattr(session, "ab_arm", None),
        },
        content_sampled=keep_full,
        ab_experiment_id=getattr(session, "ab_experiment_id", None),
        ab_arm=getattr(session, "ab_arm", None),
    )
    db.add(run)

    if oi_spans:
        spans = _spans_from_oi_buffer(run_id, oi_spans)
        # Story steps remain useful for UI narrative (CHAIN)
        spans.extend(_spans_from_story(run_id, execution_story))
    else:
        spans = _spans_from_llm_calls(run_id, llm_calls, include_planned_tools=False)
        spans.extend(_spans_from_story(run_id, execution_story))
        for ev in guard_events or []:
            spans.append(
                AgentSpan(
                    span_id=gen_uuid(),
                    run_id=run_id,
                    parent_span_id="",
                    name=f"guard.{ev.get('checkpoint') or 'unknown'}",
                    kind="guard_decision",
                    attrs_json={
                        "openinference.span.kind": "GUARDRAIL",
                        **(ev or {}),
                        "output.value": json.dumps(ev, ensure_ascii=False, default=str),
                    },
                    duration_ms=0,
                    status="BLOCK" if ev.get("decision") == "block" else "OK",
                )
            )

    for span in spans:
        if not keep_full:
            span.attrs_json = redact_span_attrs(span.attrs_json or {}, keep_full=False)
        db.add(span)

    if status == AgentRunStatus.ERROR.value and not (result.get("content") or "").strip():
        db.add(
            AgentScore(
                score_id=gen_uuid(),
                run_id=run_id,
                score_name="empty_reply",
                value=0.0,
                data_type="BOOLEAN",
                source="rule",
                comment="Assistant reply was empty",
            )
        )

    try:
        db.commit()
    except Exception:
        db.rollback()
        return None
    finally:
        try:
            from services.monitor.span_buffer import end_turn_context

            end_turn_context()
        except Exception:
            pass
    return run_id


def serialize_run(run: AgentRun, *, agent_name: str = "") -> Dict[str, Any]:
    return {
        "run_id": run.run_id,
        "session_id": run.session_id,
        "agent_id": run.agent_id,
        "agent_name": agent_name,
        "version_id": run.version_id,
        "trace_id": run.trace_id,
        "caller_id": run.caller_id,
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "ended_at": run.ended_at.isoformat() if run.ended_at else None,
        "elapsed_ms": run.elapsed_ms,
        "token_in": run.token_in,
        "token_out": run.token_out,
        "tool_calls": run.tool_calls,
        "execution_mode": run.execution_mode,
        "error_code": run.error_code,
        "summary": run.summary,
        "message_index": run.message_index,
        "attrs_json": run.attrs_json or {},
        "content_sampled": run.content_sampled,
    }


def _extract_io(attrs: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize span attrs into input/output panels (legacy + OpenInference)."""
    inp = attrs.get("input")
    out = attrs.get("output")
    if inp is None:
        inp = attrs.get("input.value")
    if out is None:
        out = attrs.get("output.value")
    if inp is None and attrs.get("arguments") is not None:
        inp = {"arguments": attrs.get("arguments")}
    if inp is None and attrs.get("tool.parameters") is not None:
        inp = attrs.get("tool.parameters")
    if out is None and attrs.get("content") is not None:
        out = {"content": attrs.get("content")}
    if out is None and attrs.get("step") is not None:
        out = attrs.get("step")
    return {"input": inp, "output": out}


def serialize_span(span: AgentSpan) -> Dict[str, Any]:
    attrs = span.attrs_json or {}
    io = _extract_io(attrs)
    oi_kind = attrs.get("openinference.span.kind") or oi_kind_from_legacy(span.kind or "")
    return {
        "span_id": span.span_id,
        "run_id": span.run_id,
        "parent_span_id": span.parent_span_id,
        "name": span.name,
        "kind": span.kind,
        "openinference_span_kind": oi_kind,
        "attrs_json": attrs,
        "input": io["input"],
        "output": io["output"],
        "duration_ms": span.duration_ms,
        "status": span.status,
        "started_at": span.started_at.isoformat() if span.started_at else None,
    }


def build_span_tree(spans: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build nested tree from flat span list."""
    by_id = {s["span_id"]: {**s, "children": []} for s in spans}
    roots: List[Dict[str, Any]] = []
    for s in spans:
        node = by_id[s["span_id"]]
        parent_id = s.get("parent_span_id") or ""
        if parent_id and parent_id in by_id:
            by_id[parent_id]["children"].append(node)
        else:
            roots.append(node)
    return roots
