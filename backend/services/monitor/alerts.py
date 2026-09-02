"""Monitor alert rules: success rate drop, token spike, tool error rate."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib import request as urlrequest

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import AgentRun, AgentRunStatus, MonitorAlert, MonitorAlertRule, gen_uuid, now_utc


def _window_start(hours: int = 24) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=hours)


def _baseline_start(hours: int = 168) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=hours)


def _fire_webhook(url: str, payload: Dict[str, Any]) -> None:
    if not url:
        return
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urlrequest.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urlrequest.urlopen(req, timeout=5)
    except Exception:
        pass


def evaluate_configured_rules(
    db: Session,
    *,
    agent_id: Optional[str] = None,
    window_hours: int = 24,
) -> List[MonitorAlert]:
    """Evaluate user-configured alert rules."""
    rules = db.query(MonitorAlertRule).filter(MonitorAlertRule.enabled.is_(True)).all()
    if not rules:
        return []

    since = _window_start(window_hours)
    q = db.query(AgentRun).filter(AgentRun.started_at >= since)
    if agent_id:
        q = q.filter(AgentRun.agent_id == agent_id)
    runs = q.all()
    if not runs:
        return []

    total = len(runs)
    success = sum(1 for r in runs if r.status == AgentRunStatus.SUCCESS.value)
    errors = sum(1 for r in runs if r.status == AgentRunStatus.ERROR.value)
    success_rate = success / total if total else 0.0
    error_rate = errors / total if total else 0.0
    avg_tokens = sum((r.token_in or 0) + (r.token_out or 0) for r in runs) / total

    alerts: List[MonitorAlert] = []
    for rule in rules:
        if rule.agent_id and agent_id and rule.agent_id != agent_id:
            continue
        if rule.agent_id and not agent_id:
            continue

        metric_val = None
        if rule.metric == "success_rate":
            metric_val = success_rate
        elif rule.metric == "error_rate":
            metric_val = error_rate
        elif rule.metric == "avg_tokens":
            metric_val = avg_tokens

        if metric_val is None:
            continue

        severity = None
        if rule.threshold_alert and metric_val >= rule.threshold_alert:
            severity = "critical"
        elif rule.threshold_warning and metric_val >= rule.threshold_warning:
            severity = "warning"
        if rule.metric in ("success_rate",) and rule.threshold_alert:
            if metric_val <= rule.threshold_alert:
                severity = "critical"
            elif rule.threshold_warning and metric_val <= rule.threshold_warning:
                severity = "warning"

        if not severity:
            continue

        existing = (
            db.query(MonitorAlert)
            .filter(
                MonitorAlert.rule_name == rule.name,
                MonitorAlert.agent_id == (agent_id or rule.agent_id or ""),
                MonitorAlert.created_at >= since,
                MonitorAlert.acknowledged.is_(False),
            )
            .first()
        )
        if existing:
            continue

        msg = f"{rule.name}: {rule.metric}={metric_val:.4f}"
        alert = MonitorAlert(
            alert_id=gen_uuid(),
            rule_name=rule.name,
            severity=severity,
            message=msg,
            agent_id=agent_id or rule.agent_id or "",
            attrs_json={"metric": rule.metric, "value": metric_val, "rule_id": rule.rule_id},
        )
        db.add(alert)
        alerts.append(alert)
        if rule.webhook_url:
            _fire_webhook(
                rule.webhook_url,
                {"rule": rule.name, "metric": rule.metric, "value": metric_val, "severity": severity},
            )

    if alerts:
        db.commit()
    return alerts


def evaluate_alerts(
    db: Session,
    *,
    agent_id: Optional[str] = None,
    window_hours: int = 24,
) -> List[MonitorAlert]:
    """Evaluate rules and persist new alerts (dedupe by rule+agent within window)."""
    configured = evaluate_configured_rules(db, agent_id=agent_id, window_hours=window_hours)
    alerts: List[MonitorAlert] = list(configured)
    since = _window_start(window_hours)
    q = db.query(AgentRun).filter(AgentRun.started_at >= since)
    if agent_id:
        q = q.filter(AgentRun.agent_id == agent_id)
    runs = q.all()
    if not runs:
        return alerts

    total = len(runs)
    success = sum(1 for r in runs if r.status == AgentRunStatus.SUCCESS.value)
    success_rate = success / total if total else 0.0
    avg_tokens = sum((r.token_in or 0) + (r.token_out or 0) for r in runs) / total
    timeouts = sum(1 for r in runs if r.status == AgentRunStatus.TIMEOUT.value)
    errors = sum(1 for r in runs if r.status == AgentRunStatus.ERROR.value)

    baseline_q = db.query(AgentRun).filter(
        AgentRun.started_at >= _baseline_start(168),
        AgentRun.started_at < since,
    )
    if agent_id:
        baseline_q = baseline_q.filter(AgentRun.agent_id == agent_id)
    baseline_runs = baseline_q.all()
    baseline_success = (
        sum(1 for r in baseline_runs if r.status == AgentRunStatus.SUCCESS.value) / len(baseline_runs)
        if baseline_runs
        else None
    )
    baseline_tokens = (
        sum((r.token_in or 0) + (r.token_out or 0) for r in baseline_runs) / len(baseline_runs)
        if baseline_runs
        else None
    )

    def _maybe_add(rule: str, severity: str, message: str, attrs: Dict[str, Any]):
        existing = (
            db.query(MonitorAlert)
            .filter(
                MonitorAlert.rule_name == rule,
                MonitorAlert.agent_id == (agent_id or ""),
                MonitorAlert.created_at >= since,
                MonitorAlert.acknowledged.is_(False),
            )
            .first()
        )
        if existing:
            return
        alert = MonitorAlert(
            alert_id=gen_uuid(),
            rule_name=rule,
            severity=severity,
            message=message,
            agent_id=agent_id or "",
            attrs_json=attrs,
        )
        db.add(alert)
        alerts.append(alert)

    if baseline_success is not None and success_rate < baseline_success - 0.15:
        _maybe_add(
            "success_rate_drop",
            "critical",
            f"Success rate {success_rate:.0%} dropped vs 7d baseline {baseline_success:.0%}",
            {"success_rate": success_rate, "baseline": baseline_success, "total": total},
        )
    if baseline_tokens and avg_tokens > baseline_tokens * 1.5:
        _maybe_add(
            "token_spike",
            "warning",
            f"Avg tokens {avg_tokens:.0f} exceeds baseline {baseline_tokens:.0f} by >50%",
            {"avg_tokens": avg_tokens, "baseline_tokens": baseline_tokens},
        )
    if timeouts >= 3:
        _maybe_add(
            "connect_timeout",
            "warning",
            f"{timeouts} timeout runs in last {window_hours}h",
            {"timeouts": timeouts},
        )
    if errors / total > 0.3 if total else False:
        _maybe_add(
            "high_error_rate",
            "critical",
            f"Error rate {errors}/{total} in last {window_hours}h",
            {"errors": errors, "total": total},
        )

    if alerts:
        db.commit()
    return alerts


def list_alerts(db: Session, *, acknowledged: Optional[bool] = None, limit: int = 50) -> List[Dict[str, Any]]:
    q = db.query(MonitorAlert).order_by(MonitorAlert.created_at.desc())
    if acknowledged is not None:
        q = q.filter(MonitorAlert.acknowledged.is_(acknowledged))
    rows = q.limit(limit).all()
    return [
        {
            "alert_id": a.alert_id,
            "rule_name": a.rule_name,
            "severity": a.severity,
            "message": a.message,
            "run_id": a.run_id,
            "agent_id": a.agent_id,
            "acknowledged": a.acknowledged,
            "attrs_json": a.attrs_json or {},
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in rows
    ]


def monitor_summary(db: Session, *, agent_id: Optional[str] = None, days: int = 7) -> Dict[str, Any]:
    from services.monitor.cost import aggregate_run_cost

    since = datetime.now(timezone.utc) - timedelta(days=days)
    q = db.query(AgentRun).filter(AgentRun.started_at >= since)
    if agent_id:
        q = q.filter(AgentRun.agent_id == agent_id)
    runs = q.all()
    total = len(runs)
    if not total:
        return {
            "total_runs": 0,
            "success_rate": 0.0,
            "error_rate": 0.0,
            "hitl_rate": 0.0,
            "avg_elapsed_ms": 0,
            "p95_elapsed_ms": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "tool_failure_proxy": 0.0,
            "trace_complete_rate": 1.0,
            "timeseries": [],
        }

    success = sum(1 for r in runs if r.status == AgentRunStatus.SUCCESS.value)
    errors = sum(1 for r in runs if r.status == AgentRunStatus.ERROR.value)
    hitl = sum(1 for r in runs if r.status == AgentRunStatus.HITL_WAIT.value)
    elapsed = sorted(r.elapsed_ms or 0 for r in runs)
    p95 = elapsed[int(len(elapsed) * 0.95)] if elapsed else 0
    tokens = sum((r.token_in or 0) + (r.token_out or 0) for r in runs)
    guard_blocks = sum(
        1
        for r in runs
        for ev in (r.attrs_json or {}).get("guard_events") or []
        if ev.get("decision") == "block"
    )

    from models import AgentSpan

    run_ids = [r.run_id for r in runs]
    spans_by_run: Dict[str, int] = {}
    if run_ids:
        for rid, cnt in (
            db.query(AgentSpan.run_id, func.count())
            .filter(AgentSpan.run_id.in_(run_ids))
            .group_by(AgentSpan.run_id)
            .all()
        ):
            spans_by_run[rid] = cnt
    with_spans = sum(1 for r in runs if spans_by_run.get(r.run_id, 0) > 0)

    cost_info = aggregate_run_cost(runs)
    timeseries = _build_timeseries(runs, days=days)

    return {
        "total_runs": total,
        "success_rate": round(success / total, 4),
        "error_rate": round(errors / total, 4),
        "hitl_rate": round(hitl / total, 4),
        "avg_elapsed_ms": round(sum(elapsed) / total),
        "p95_elapsed_ms": p95,
        "total_tokens": tokens,
        "estimated_cost_usd": cost_info["estimated_cost_usd"],
        "guard_block_count": guard_blocks,
        "trace_complete_rate": round(with_spans / total, 4),
        "negative_feedback_rate": _feedback_rate(db, agent_id, since),
        "timeseries": timeseries,
    }


def _build_timeseries(runs: List[AgentRun], *, days: int) -> List[Dict[str, Any]]:
    buckets: Dict[str, Dict[str, Any]] = {}
    for r in runs:
        if not r.started_at:
            continue
        key = r.started_at.strftime("%Y-%m-%d")
        b = buckets.setdefault(key, {"date": key, "runs": 0, "errors": 0, "elapsed_sum": 0})
        b["runs"] += 1
        if r.status == AgentRunStatus.ERROR.value:
            b["errors"] += 1
        b["elapsed_sum"] += r.elapsed_ms or 0
    rows = []
    for key in sorted(buckets.keys()):
        b = buckets[key]
        runs_n = b["runs"] or 1
        rows.append(
            {
                "date": key,
                "runs": b["runs"],
                "error_rate": round(b["errors"] / runs_n, 4),
                "avg_elapsed_ms": round(b["elapsed_sum"] / runs_n),
            }
        )
    return rows[-min(days, 30):]


def _feedback_rate(db: Session, agent_id: Optional[str], since: datetime) -> float:
    from models import AgentFeedback

    q = db.query(AgentFeedback).filter(AgentFeedback.created_at >= since)
    if agent_id:
        q = q.filter(AgentFeedback.agent_id == agent_id)
    items = q.all()
    if not items:
        return 0.0
    negative = sum(1 for f in items if (f.rating or 0) < 0)
    return round(negative / len(items), 4)


def resolve_run_id(
    db: Session,
    *,
    run_id: Optional[str],
    session_id: str,
    message_index: int,
) -> Optional[str]:
    if run_id:
        return run_id
    if not session_id or message_index < 0:
        return None
    run = (
        db.query(AgentRun)
        .filter(
            AgentRun.session_id == session_id,
            AgentRun.message_index == message_index,
        )
        .order_by(AgentRun.started_at.desc())
        .first()
    )
    return run.run_id if run else None
