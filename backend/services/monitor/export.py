"""Export adapters: OpenInference-compliant JSON + optional Langfuse stub."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from services.monitor.openinference_attrs import oi_kind_from_legacy


def export_run_otel_json(run: Dict[str, Any], spans: List[Dict[str, Any]]) -> str:
    """OpenInference-oriented JSON (debug download; not OTLP protobuf).

    Each span includes `openinference.span.kind` and flattened semantic attributes.
    Runtime OTLP export (if configured) goes through the SDK BatchSpanProcessor.
    """
    resource = {
        "service.name": "vela-agent",
        "agent.id": run.get("agent_id"),
        "session.id": run.get("session_id"),
    }
    otel_spans = []
    for s in spans:
        attrs = dict(s.get("attrs_json") or {})
        oi_kind = (
            s.get("openinference_span_kind")
            or attrs.get("openinference.span.kind")
            or oi_kind_from_legacy(s.get("kind") or "")
        )
        attrs["openinference.span.kind"] = oi_kind
        # Promote session/user from run when missing on span
        if run.get("session_id") and "session.id" not in attrs:
            attrs["session.id"] = run["session_id"]
        if run.get("caller_id") and "user.id" not in attrs:
            attrs["user.id"] = run["caller_id"]
        # Merge run-level evaluations if present
        run_attrs = run.get("attrs_json") or {}
        for k, v in run_attrs.items():
            if str(k).startswith("evaluations.") and k not in attrs:
                attrs[k] = v

        otel_spans.append(
            {
                "trace_id": run.get("trace_id") or run.get("run_id"),
                "span_id": s.get("span_id"),
                "parent_span_id": s.get("parent_span_id") or None,
                "name": s.get("name"),
                "openinference.span.kind": oi_kind,
                "kind": s.get("kind"),  # legacy UI column
                "start_time": s.get("started_at"),
                "duration_ms": s.get("duration_ms"),
                "attributes": attrs,
                "status": s.get("status"),
            }
        )
    payload = {
        "format": "openinference-json",
        "note": "Semantic OpenInference attributes; use OTLP exporter for collector ingest.",
        "resource": resource,
        "spans": otel_spans,
        "run": run,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def maybe_dual_write_langfuse(run: Dict[str, Any], spans: List[Dict[str, Any]]) -> None:
    """No-op unless LANGFUSE_PUBLIC_KEY is configured.

    Prefer configuring OTEL_EXPORTER_OTLP_ENDPOINT to a Langfuse/Phoenix OTLP
    endpoint instead of a proprietary SDK dual-write.
    """
    if not os.getenv("LANGFUSE_PUBLIC_KEY"):
        return
    _ = export_run_otel_json(run, spans)


def build_effect_report(
    db,
    *,
    agent_id: str,
    days: int = 7,
) -> Dict[str, Any]:
    """P4: lightweight effect report for prompt/KB change review."""
    from datetime import datetime, timedelta, timezone

    from models import AgentFeedback, AgentRun, AgentRunStatus, AgentScore, EvalJob
    from services.monitor.alerts import monitor_summary

    since = datetime.now(timezone.utc) - timedelta(days=days)
    summary = monitor_summary(db, agent_id=agent_id, days=days)
    runs = (
        db.query(AgentRun)
        .filter(AgentRun.agent_id == agent_id, AgentRun.started_at >= since)
        .order_by(AgentRun.started_at.desc())
        .limit(20)
        .all()
    )
    badcases = [r for r in runs if r.status != AgentRunStatus.SUCCESS.value]
    feedback = (
        db.query(AgentFeedback)
        .filter(AgentFeedback.agent_id == agent_id, AgentFeedback.created_at >= since, AgentFeedback.rating < 0)
        .count()
    )
    eval_jobs = (
        db.query(EvalJob)
        .filter(EvalJob.agent_id == agent_id)
        .order_by(EvalJob.created_at.desc())
        .limit(5)
        .all()
    )
    rule_scores = (
        db.query(AgentScore)
        .join(AgentRun, AgentRun.run_id == AgentScore.run_id)
        .filter(AgentRun.agent_id == agent_id, AgentScore.created_at >= since)
        .count()
    )
    return {
        "agent_id": agent_id,
        "period_days": days,
        "summary": summary,
        "badcase_count": len(badcases),
        "badcase_run_ids": [r.run_id for r in badcases[:10]],
        "negative_feedback_count": feedback,
        "eval_jobs_recent": [
            {"job_id": j.job_id, "status": j.status, "summary": j.summary or {}}
            for j in eval_jobs
        ],
        "rule_score_count": rule_scores,
        "recommendation": (
            "Review badcases before full rollout"
            if badcases or feedback
            else "Metrics stable; safe for gradual rollout"
        ),
    }
