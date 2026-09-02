"""Optional export adapters (OTel / Langfuse stub)."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List


def export_run_otel_json(run: Dict[str, Any], spans: List[Dict[str, Any]]) -> str:
    """Minimal OTel-compatible JSON for external collectors."""
    resource = {
        "service.name": "vela-agent",
        "agent.id": run.get("agent_id"),
        "session.id": run.get("session_id"),
    }
    otel_spans = []
    for s in spans:
        otel_spans.append(
            {
                "trace_id": run.get("trace_id") or run.get("run_id"),
                "span_id": s.get("span_id"),
                "parent_span_id": s.get("parent_span_id") or None,
                "name": s.get("name"),
                "kind": s.get("kind"),
                "start_time": s.get("started_at"),
                "duration_ms": s.get("duration_ms"),
                "attributes": s.get("attrs_json") or {},
                "status": s.get("status"),
            }
        )
    payload = {"resource": resource, "spans": otel_spans, "run": run}
    return json.dumps(payload, ensure_ascii=False, indent=2)


def maybe_dual_write_langfuse(run: Dict[str, Any], spans: List[Dict[str, Any]]) -> None:
    """No-op unless LANGFUSE_PUBLIC_KEY is configured."""
    if not os.getenv("LANGFUSE_PUBLIC_KEY"):
        return
    # Placeholder: integrate Langfuse SDK when credentials present.
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
