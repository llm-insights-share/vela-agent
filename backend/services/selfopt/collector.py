"""Collect failure / feedback trajectories for reflection."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from models import AgentFeedback, AgentRun, AgentRunStatus, AgentSpan


def collect_trajectories(
    db: Session,
    *,
    agent_id: str,
    window_start: Optional[datetime] = None,
    window_end: Optional[datetime] = None,
    limit: int = 40,
) -> List[Dict[str, Any]]:
    end = window_end or datetime.now(timezone.utc)
    start = window_start or (end - timedelta(days=7))

    bad_statuses = {
        AgentRunStatus.ERROR.value,
        AgentRunStatus.ABORT.value,
        AgentRunStatus.TIMEOUT.value,
        AgentRunStatus.HITL_WAIT.value,
    }
    runs = (
        db.query(AgentRun)
        .filter(
            AgentRun.agent_id == agent_id,
            AgentRun.started_at >= start,
            AgentRun.started_at <= end,
        )
        .order_by(AgentRun.started_at.desc())
        .limit(limit * 3)
        .all()
    )

    feedback_neg = (
        db.query(AgentFeedback)
        .filter(
            AgentFeedback.agent_id == agent_id,
            AgentFeedback.rating < 0,
            AgentFeedback.created_at >= start,
            AgentFeedback.created_at <= end,
        )
        .all()
    )
    neg_run_ids = {f.run_id for f in feedback_neg if f.run_id}

    selected: List[AgentRun] = []
    for r in runs:
        if r.status in bad_statuses or r.run_id in neg_run_ids:
            selected.append(r)
        if len(selected) >= limit:
            break

    # If too few failures, include low-signal recent runs for prompt context
    if len(selected) < 5:
        for r in runs:
            if r not in selected:
                selected.append(r)
            if len(selected) >= min(10, limit):
                break

    out: List[Dict[str, Any]] = []
    for r in selected:
        spans = (
            db.query(AgentSpan)
            .filter(AgentSpan.run_id == r.run_id)
            .order_by(AgentSpan.started_at.asc())
            .limit(30)
            .all()
        )
        fb = [f for f in feedback_neg if f.run_id == r.run_id]
        out.append(
            {
                "run_id": r.run_id,
                "session_id": r.session_id,
                "status": r.status,
                "summary": (r.summary or "")[:500],
                "error_code": r.error_code or "",
                "elapsed_ms": r.elapsed_ms,
                "token_in": r.token_in,
                "token_out": r.token_out,
                "tool_calls": r.tool_calls,
                "feedback": [{"rating": f.rating, "reason": f.reason or ""} for f in fb],
                "spans": [
                    {
                        "span_id": s.span_id,
                        "name": s.name,
                        "kind": s.kind,
                        "status": s.status,
                        "duration_ms": s.duration_ms,
                    }
                    for s in spans
                ],
            }
        )
    return out
