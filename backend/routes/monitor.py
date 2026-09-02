from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database import get_db
from deps import CurrentUser
from models import (
    Agent,
    AgentFeedback,
    AgentRun,
    AgentScore,
    AgentSpan,
    AnnotationQueue,
    AnnotationQueueItem,
    MonitorAlert,
    MonitorAlertRule,
    MonitorSavedView,
    Session as SessionModel,
    gen_uuid,
)
from schemas import PaginatedResponse
from services.monitor.alerts import evaluate_alerts, list_alerts, monitor_summary, resolve_run_id
from services.monitor.cost import aggregate_run_cost
from services.monitor.export import build_effect_report, export_run_otel_json, maybe_dual_write_langfuse
from services.monitor.trace_sink import build_span_tree, serialize_run, serialize_span

router = APIRouter(prefix="/api/v1/monitor", tags=["monitor"])


def _serialize_score(s: AgentScore) -> dict:
    return {
        "score_name": s.score_name,
        "value": s.value,
        "data_type": s.data_type or "NUMERIC",
        "source": s.source,
        "comment": s.comment,
    }


@router.get("/summary")
def get_summary(
    user: CurrentUser,
    agent_id: Optional[str] = Query(None),
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
):
    evaluate_alerts(db, agent_id=agent_id)
    return monitor_summary(db, agent_id=agent_id, days=days)


@router.get("/runs")
def list_runs(
    user: CurrentUser,
    agent_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(AgentRun).order_by(AgentRun.started_at.desc())
    if agent_id:
        query = query.filter(AgentRun.agent_id == agent_id)
    if status:
        query = query.filter(AgentRun.status == status)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(AgentRun.summary.like(like), AgentRun.trace_id.like(like)))
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    agent_names = {}
    if rows:
        aids = {r.agent_id for r in rows}
        for a in db.query(Agent).filter(Agent.agent_id.in_(list(aids))).all():
            agent_names[a.agent_id] = a.name
    items = [serialize_run(r, agent_name=agent_names.get(r.agent_id, "")) for r in rows]
    return PaginatedResponse(total=total, page=page, page_size=page_size, items=items)


@router.get("/observations")
def list_observations(
    user: CurrentUser,
    agent_id: Optional[str] = Query(None),
    kind: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(AgentSpan).join(AgentRun, AgentSpan.run_id == AgentRun.run_id)
    query = query.order_by(AgentSpan.started_at.desc())
    if agent_id:
        query = query.filter(AgentRun.agent_id == agent_id)
    if kind:
        query = query.filter(AgentSpan.kind == kind)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(AgentSpan.name.like(like), AgentSpan.kind.like(like)))
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    run_ids = {s.run_id for s in rows}
    runs = {
        r.run_id: r
        for r in db.query(AgentRun).filter(AgentRun.run_id.in_(list(run_ids))).all()
    } if run_ids else {}
    items = []
    for span in rows:
        item = serialize_span(span)
        run = runs.get(span.run_id)
        item["agent_id"] = run.agent_id if run else ""
        item["run_status"] = run.status if run else ""
        items.append(item)
    return PaginatedResponse(total=total, page=page, page_size=page_size, items=items)


@router.get("/sessions")
def list_sessions(
    user: CurrentUser,
    agent_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(SessionModel).order_by(SessionModel.last_active_at.desc())
    if agent_id:
        query = query.filter(SessionModel.agent_id == agent_id)
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    items = []
    for s in rows:
        runs = db.query(AgentRun).filter(AgentRun.session_id == s.session_id).all()
        cost = aggregate_run_cost(runs)
        items.append(
            {
                "session_id": s.session_id,
                "agent_id": s.agent_id,
                "title": s.title or "",
                "status": s.status.value if hasattr(s.status, "value") else s.status,
                "caller_id": s.caller_id,
                "token_used": s.token_used or 0,
                "run_count": len(runs),
                "estimated_cost_usd": cost["estimated_cost_usd"],
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "last_active_at": s.last_active_at.isoformat() if s.last_active_at else None,
            }
        )
    return PaginatedResponse(total=total, page=page, page_size=page_size, items=items)


@router.get("/users")
def list_user_usage(
    user: CurrentUser,
    agent_id: Optional[str] = Query(None),
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
):
    from datetime import datetime, timedelta, timezone

    since = datetime.now(timezone.utc) - timedelta(days=days)
    q = db.query(AgentRun).filter(AgentRun.started_at >= since)
    if agent_id:
        q = q.filter(AgentRun.agent_id == agent_id)
    runs = q.all()
    by_user: dict = {}
    for r in runs:
        uid = r.caller_id or "anonymous"
        bucket = by_user.setdefault(
            uid,
            {"user_id": uid, "run_count": 0, "total_tokens": 0, "estimated_cost_usd": 0.0},
        )
        bucket["run_count"] += 1
        bucket["total_tokens"] += (r.token_in or 0) + (r.token_out or 0)
    for uid, bucket in by_user.items():
        user_runs = [r for r in runs if (r.caller_id or "anonymous") == uid]
        bucket["estimated_cost_usd"] = aggregate_run_cost(user_runs)["estimated_cost_usd"]
    items = sorted(by_user.values(), key=lambda x: x["run_count"], reverse=True)
    return {"items": items, "days": days}


@router.get("/runs/{run_id}")
def get_run(run_id: str, user: CurrentUser, db: Session = Depends(get_db)):
    run = db.query(AgentRun).filter(AgentRun.run_id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run 不存在")
    agent = db.query(Agent).filter(Agent.agent_id == run.agent_id).first()
    spans = db.query(AgentSpan).filter(AgentSpan.run_id == run_id).order_by(AgentSpan.started_at.asc()).all()
    scores = db.query(AgentScore).filter(AgentScore.run_id == run_id).all()
    feedback = db.query(AgentFeedback).filter(AgentFeedback.run_id == run_id).all()
    payload = serialize_run(run, agent_name=agent.name if agent else "")
    span_items = [serialize_span(s) for s in spans]
    maybe_dual_write_langfuse(payload, span_items)
    return {
        **payload,
        "spans": span_items,
        "span_tree": build_span_tree(span_items),
        "scores": [_serialize_score(s) for s in scores],
        "feedback": [
            {
                "feedback_id": f.feedback_id,
                "rating": f.rating,
                "reason": f.reason,
                "message_index": f.message_index,
            }
            for f in feedback
        ],
        "chat_url": f"/agents/{run.agent_id}/chat?session={run.session_id}",
    }


@router.get("/runs/{run_id}/export/otel")
def export_run_otel(run_id: str, user: CurrentUser, db: Session = Depends(get_db)):
    run = db.query(AgentRun).filter(AgentRun.run_id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run 不存在")
    agent = db.query(Agent).filter(Agent.agent_id == run.agent_id).first()
    spans = db.query(AgentSpan).filter(AgentSpan.run_id == run_id).all()
    payload = serialize_run(run, agent_name=agent.name if agent else "")
    span_items = [serialize_span(s) for s in spans]
    return {"format": "otel-json", "payload": export_run_otel_json(payload, span_items)}


@router.get("/alerts")
def get_alerts(
    user: CurrentUser,
    acknowledged: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return {"items": list_alerts(db, acknowledged=acknowledged, limit=limit)}


@router.get("/alert-rules")
def list_alert_rules(user: CurrentUser, db: Session = Depends(get_db)):
    rows = db.query(MonitorAlertRule).order_by(MonitorAlertRule.created_at.desc()).all()
    return {
        "items": [
            {
                "rule_id": r.rule_id,
                "name": r.name,
                "metric": r.metric,
                "threshold_warning": r.threshold_warning,
                "threshold_alert": r.threshold_alert,
                "webhook_url": r.webhook_url,
                "enabled": r.enabled,
                "agent_id": r.agent_id,
            }
            for r in rows
        ]
    }


@router.post("/alert-rules", status_code=201)
def create_alert_rule(data: dict, user: CurrentUser, db: Session = Depends(get_db)):
    name = (data.get("name") or "").strip()
    metric = (data.get("metric") or "").strip()
    if not name or not metric:
        raise HTTPException(status_code=400, detail="name 与 metric 必填")
    row = MonitorAlertRule(
        rule_id=gen_uuid(),
        name=name,
        metric=metric,
        threshold_warning=float(data.get("threshold_warning") or 0),
        threshold_alert=float(data.get("threshold_alert") or 0),
        webhook_url=data.get("webhook_url") or "",
        enabled=bool(data.get("enabled", True)),
        agent_id=data.get("agent_id") or "",
    )
    db.add(row)
    db.commit()
    return {"rule_id": row.rule_id}


@router.patch("/alert-rules/{rule_id}")
def update_alert_rule(rule_id: str, data: dict, user: CurrentUser, db: Session = Depends(get_db)):
    row = db.query(MonitorAlertRule).filter(MonitorAlertRule.rule_id == rule_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="规则不存在")
    for key in ("name", "metric", "webhook_url", "agent_id"):
        if key in data:
            setattr(row, key, data.get(key) or "")
    for key in ("threshold_warning", "threshold_alert"):
        if key in data:
            setattr(row, key, float(data.get(key) or 0))
    if "enabled" in data:
        row.enabled = bool(data.get("enabled"))
    db.commit()
    return {"ok": True}


@router.delete("/alert-rules/{rule_id}")
def delete_alert_rule(rule_id: str, user: CurrentUser, db: Session = Depends(get_db)):
    row = db.query(MonitorAlertRule).filter(MonitorAlertRule.rule_id == rule_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="规则不存在")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.post("/alerts/{alert_id}/ack")
def ack_alert(alert_id: str, user: CurrentUser, db: Session = Depends(get_db)):
    row = db.query(MonitorAlert).filter(MonitorAlert.alert_id == alert_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Alert 不存在")
    row.acknowledged = True
    db.commit()
    return {"ok": True}


@router.get("/saved-views")
def list_saved_views(user: CurrentUser, db: Session = Depends(get_db)):
    uid = getattr(user, "user_id", "") or ""
    rows = (
        db.query(MonitorSavedView)
        .filter(or_(MonitorSavedView.user_id == uid, MonitorSavedView.user_id == ""))
        .order_by(MonitorSavedView.created_at.desc())
        .all()
    )
    return {
        "items": [
            {
                "view_id": v.view_id,
                "name": v.name,
                "path": v.path,
                "filters_json": v.filters_json or {},
            }
            for v in rows
        ]
    }


@router.post("/saved-views", status_code=201)
def create_saved_view(data: dict, user: CurrentUser, db: Session = Depends(get_db)):
    name = (data.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name 必填")
    row = MonitorSavedView(
        view_id=gen_uuid(),
        name=name,
        path=data.get("path") or "runs",
        filters_json=data.get("filters_json") or {},
        user_id=getattr(user, "user_id", "") or "",
    )
    db.add(row)
    db.commit()
    return {"view_id": row.view_id}


@router.post("/feedback")
def submit_feedback(data: dict, user: CurrentUser, db: Session = Depends(get_db)):
    rating = int(data.get("rating") or 0)
    if rating not in (-1, 0, 1):
        raise HTTPException(status_code=400, detail="rating 必须为 -1/0/1")

    session_id = data.get("session_id") or ""
    message_index = int(data.get("message_index") or -1)
    resolved_run_id = resolve_run_id(
        db,
        run_id=data.get("run_id"),
        session_id=session_id,
        message_index=message_index,
    )

    fb = AgentFeedback(
        feedback_id=gen_uuid(),
        session_id=session_id,
        run_id=resolved_run_id,
        agent_id=data.get("agent_id") or "",
        message_index=message_index,
        rating=rating,
        reason=data.get("reason") or "",
        user_id=getattr(user, "user_id", "") or "",
    )
    db.add(fb)
    if resolved_run_id:
        db.add(
            AgentScore(
                score_id=gen_uuid(),
                run_id=resolved_run_id,
                score_name="user_feedback",
                value=float(rating),
                data_type="NUMERIC",
                source="user",
                comment=fb.reason,
            )
        )
    db.commit()
    return {"feedback_id": fb.feedback_id, "run_id": resolved_run_id}


@router.get("/reports/effect")
def effect_report(
    user: CurrentUser,
    agent_id: str = Query(...),
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
):
    return build_effect_report(db, agent_id=agent_id, days=days)
