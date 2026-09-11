"""Aggregate A/B experiment metrics by arm."""
from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import AgentFeedback, AgentRun, AgentRunStatus, SelfOptABExperiment, Session as SessionModel


def _arm_metrics(db: Session, *, experiment_id: str, arm: str) -> Dict[str, Any]:
    sessions = (
        db.query(SessionModel)
        .filter(
            SessionModel.ab_experiment_id == experiment_id,
            SessionModel.ab_arm == arm,
        )
        .all()
    )
    active_sessions = [s for s in sessions if (s.messages or [])]
    empty_sessions = [s for s in sessions if not (s.messages or [])]
    # Metrics only over sessions that actually chatted (empty ones burn rr but have no runs)
    session_ids = [s.session_id for s in active_sessions]
    all_session_ids = [s.session_id for s in sessions]
    session_count = len(session_ids)

    runs_q = db.query(AgentRun).filter(AgentRun.ab_experiment_id == experiment_id)
    # Prefer run.ab_arm; fall back via session (include empty-session ids for legacy runs)
    runs = [r for r in runs_q.all() if (r.ab_arm == arm) or (
        not r.ab_arm and r.session_id in all_session_ids
    )]
    run_count = len(runs)
    success = sum(1 for r in runs if r.status == AgentRunStatus.SUCCESS.value)
    error = sum(1 for r in runs if r.status == AgentRunStatus.ERROR.value)
    hitl = sum(1 for r in runs if r.status == AgentRunStatus.HITL_WAIT.value)
    avg_elapsed = (sum(r.elapsed_ms or 0 for r in runs) / run_count) if run_count else 0
    avg_tokens = (
        sum((r.token_in or 0) + (r.token_out or 0) for r in runs) / run_count if run_count else 0
    )

    thumbs_up = 0
    thumbs_down = 0
    if session_ids:
        fbs = (
            db.query(AgentFeedback)
            .filter(AgentFeedback.session_id.in_(session_ids))
            .all()
        )
        for f in fbs:
            if f.rating and f.rating > 0:
                thumbs_up += 1
            elif f.rating and f.rating < 0:
                thumbs_down += 1

    return {
        "arm": arm,
        "session_count": session_count,
        "assigned_session_count": len(sessions),
        "empty_session_count": len(empty_sessions),
        "run_count": run_count,
        "success_count": success,
        "error_count": error,
        "hitl_count": hitl,
        "success_rate": (success / run_count) if run_count else None,
        "avg_elapsed_ms": round(avg_elapsed, 1),
        "avg_tokens": round(avg_tokens, 1),
        "thumbs_up": thumbs_up,
        "thumbs_down": thumbs_down,
    }


def build_ab_report(db: Session, *, experiment_id: str) -> Dict[str, Any]:
    exp = (
        db.query(SelfOptABExperiment)
        .filter(SelfOptABExperiment.experiment_id == experiment_id)
        .first()
    )
    if not exp:
        return {}
    control = _arm_metrics(db, experiment_id=experiment_id, arm="control")
    treatment = _arm_metrics(db, experiment_id=experiment_id, arm="treatment")
    delta: Dict[str, Optional[float]] = {}
    for key in ("success_rate", "avg_elapsed_ms", "avg_tokens", "error_count", "hitl_count"):
        c, t = control.get(key), treatment.get(key)
        if c is None or t is None:
            delta[key] = None
        else:
            delta[key] = round(float(t) - float(c), 4)

    rr = int(exp.rr_counter or 0)
    expected_treatment = (rr + 1) // 2  # odd turns: 1,3,5...
    expected_control = rr // 2
    actual_c = int(control.get("assigned_session_count") or control.get("session_count") or 0)
    actual_t = int(treatment.get("assigned_session_count") or treatment.get("session_count") or 0)
    assignment_ok = actual_c == expected_control and actual_t == expected_treatment

    return {
        "experiment_id": exp.experiment_id,
        "agent_id": exp.agent_id,
        "status": exp.status,
        "strategy": exp.strategy,
        "rr_counter": exp.rr_counter,
        "control_version_id": exp.control_version_id,
        "treatment_version_id": exp.treatment_version_id,
        "control": control,
        "treatment": treatment,
        "delta": delta,
        "decision": exp.decision,
        "assignment": {
            "rule": "odd→treatment, even→control",
            "rr_counter": rr,
            "expected_control_sessions": expected_control,
            "expected_treatment_sessions": expected_treatment,
            "actual_control_sessions": actual_c,
            "actual_treatment_sessions": actual_t,
            "control_empty_sessions": control.get("empty_session_count") or 0,
            "treatment_empty_sessions": treatment.get("empty_session_count") or 0,
            "balanced": assignment_ok,
        },
    }
