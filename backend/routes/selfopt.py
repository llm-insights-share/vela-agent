"""SelfOptGateway REST API."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from deps import CurrentUser
from models import Agent, SelfOptABExperiment, SelfOptJob, SelfOptProposal
from services.selfopt.config import (
    SelfOptConfig,
    is_globally_enabled,
    load_selfopt_config,
)
from services.selfopt.ab_report import build_ab_report
from services.selfopt.pipeline import run_selfopt_job
from services.selfopt.promote import (
    abort_experiment,
    keep_control,
    promote_experiment,
    start_ab_from_proposal,
)

router = APIRouter(prefix="/api/v1/selfopt", tags=["selfopt"])


def _require_global_enabled():
    if not is_globally_enabled():
        raise HTTPException(status_code=403, detail="selfopt_disabled")


class JobCreate(BaseModel):
    agent_id: str
    window_days: int = Field(default=7, ge=1, le=90)
    dataset_id: Optional[str] = None
    reflect_model_service_id: Optional[str] = None


class StartAbRequest(BaseModel):
    target_sessions: int = Field(default=40, ge=2, le=10000)
    min_sessions: int = Field(default=10, ge=1, le=10000)


class DecisionRequest(BaseModel):
    note: str = ""


class AgentPolicyUpdate(BaseModel):
    selfopt_enabled: Optional[bool] = None


def _job_dict(j: SelfOptJob) -> Dict[str, Any]:
    return {
        "job_id": j.job_id,
        "agent_id": j.agent_id,
        "job_label": j.job_label or j.job_id,
        "window_start": j.window_start,
        "window_end": j.window_end,
        "status": j.status,
        "stats_json": j.stats_json or {},
        "created_at": j.created_at,
        "updated_at": j.updated_at,
    }


def _proposal_dict(p: SelfOptProposal) -> Dict[str, Any]:
    return {
        "proposal_id": p.proposal_id,
        "job_id": p.job_id,
        "agent_id": p.agent_id,
        "base_version_id": p.base_version_id,
        "candidate_version_id": p.candidate_version_id,
        "change_kind": p.change_kind,
        "risk_tier": p.risk_tier,
        "diff_json": p.diff_json or {},
        "rationale": p.rationale or "",
        "evidence_run_ids": p.evidence_run_ids or [],
        "eval_before_job_id": p.eval_before_job_id or "",
        "eval_after_job_id": p.eval_after_job_id or "",
        "eval_report_json": p.eval_report_json or {},
        "status": p.status,
        "created_at": p.created_at,
        "updated_at": p.updated_at,
    }


def _exp_dict(e: SelfOptABExperiment) -> Dict[str, Any]:
    return {
        "experiment_id": e.experiment_id,
        "agent_id": e.agent_id,
        "proposal_id": e.proposal_id,
        "control_version_id": e.control_version_id,
        "treatment_version_id": e.treatment_version_id,
        "strategy": e.strategy,
        "rr_counter": e.rr_counter,
        "status": e.status,
        "started_at": e.started_at,
        "ended_at": e.ended_at,
        "min_sessions": e.min_sessions,
        "target_sessions": e.target_sessions,
        "decision": e.decision,
        "decided_by": e.decided_by,
        "decided_at": e.decided_at,
        "decision_note": e.decision_note,
    }


def _job_stage_bundle(
    job: SelfOptJob,
    proposals: List[SelfOptProposal],
    experiments: List[SelfOptABExperiment],
) -> Dict[str, Any]:
    """Build clickable closed-loop stages + per-stage payloads for one job."""
    stats = job.stats_json or {}
    traj = int(stats.get("trajectory_count") or 0)
    findings = int(stats.get("finding_count") or 0)
    pending_review = sum(1 for p in proposals if p.status == "pending_review")
    evaluated = sum(1 for p in proposals if p.status == "evaluated")
    ab_running = sum(1 for p in proposals if p.status == "ab_running")
    promoted = sum(1 for p in proposals if p.status == "promoted")
    rejected = sum(1 for p in proposals if p.status in ("rejected", "aborted"))
    running_exps = [e for e in experiments if e.status == "running"]
    decided_exps = [e for e in experiments if e.decision and e.decision != "pending"]

    if job.status == "failed":
        stage = "reflect"
    elif job.status == "running":
        stage = "reflect" if traj > 0 else "collect"
    elif running_exps or ab_running:
        stage = "ab"
    elif pending_review > 0:
        stage = "review"
    elif decided_exps or promoted or rejected:
        stage = "decide"
    elif evaluated > 0 or any(p.eval_report_json for p in proposals):
        stage = "gate"
    elif findings > 0 or proposals:
        stage = "reflect"
    elif traj > 0:
        stage = "collect"
    else:
        stage = "collect"

    stage_keys = [
        ("collect", "轨迹采集"),
        ("reflect", "反思提案"),
        ("gate", "离线评测"),
        ("review", "人工审阅"),
        ("ab", "轮询 A/B"),
        ("decide", "正式上线 / 保持当前"),
    ]
    stages = [
        {"key": k, "label": lab, "active": stage == k}
        for k, lab in stage_keys
    ]

    gate_summaries = []
    for p in proposals:
        rep = p.eval_report_json or {}
        if rep:
            gate_summaries.append(
                {
                    "proposal_id": p.proposal_id,
                    "status": p.status,
                    "passed": rep.get("passed"),
                    "summary": rep.get("summary") or rep.get("message") or rep,
                }
            )

    stage_payloads = {
        "collect": {
            "trajectory_count": traj,
            "window_start": job.window_start,
            "window_end": job.window_end,
            "status": job.status,
        },
        "reflect": {
            "finding_count": findings,
            "proposal_count": int(stats.get("proposal_count") or len(proposals)),
            "reflect_model_service_id": stats.get("reflect_model_service_id") or "",
            "reflect_model_name": stats.get("reflect_model_name") or "",
            "status": job.status,
            "error": stats.get("error"),
        },
        "gate": {
            "evaluated_count": evaluated,
            "reports": gate_summaries,
            "proposal_statuses": [
                {"proposal_id": p.proposal_id, "status": p.status} for p in proposals
            ],
        },
        "review": {
            "pending_review": pending_review,
            "proposals": [
                {
                    "proposal_id": p.proposal_id,
                    "status": p.status,
                    "risk_tier": p.risk_tier,
                    "change_kind": p.change_kind,
                    "rationale": (p.rationale or "")[:200],
                }
                for p in proposals
            ],
        },
        "ab": {
            "running_count": len(running_exps),
            "experiments": [
                {
                    "experiment_id": e.experiment_id,
                    "proposal_id": e.proposal_id,
                    "status": e.status,
                    "rr_counter": e.rr_counter,
                    "decision": e.decision,
                    "target_sessions": e.target_sessions,
                    "min_sessions": e.min_sessions,
                }
                for e in experiments
            ],
        },
        "decide": {
            "promoted": promoted,
            "rejected": rejected,
            "decisions": [
                {
                    "experiment_id": e.experiment_id,
                    "decision": e.decision,
                    "decided_by": e.decided_by,
                    "decided_at": e.decided_at,
                    "decision_note": e.decision_note,
                    "status": e.status,
                }
                for e in experiments
                if e.decision and e.decision != "pending"
            ],
        },
    }
    return {
        "current_stage": stage,
        "stages": stages,
        "stage_payloads": stage_payloads,
    }


@router.get("/status")
def selfopt_status():
    cfg = load_selfopt_config()
    return {
        "enabled": cfg.enabled,
        "schedule_enabled": cfg.schedule_enabled,
        "ab_enabled": cfg.ab_enabled,
        "reflect_model_service_id": cfg.reflect_model_service_id or "",
        "agent_ids": list(cfg.agent_ids or []),
    }


@router.get("/overview")
def selfopt_overview(agent_id: Optional[str] = None, db: Session = Depends(get_db)):
    """Closed-loop stage summary for hub dashboard."""
    from datetime import datetime, timedelta, timezone

    cfg = load_selfopt_config()
    allow = list(cfg.agent_ids or [])

    prop_q = db.query(SelfOptProposal)
    job_q = db.query(SelfOptJob)
    exp_q = db.query(SelfOptABExperiment)
    if agent_id:
        prop_q = prop_q.filter(SelfOptProposal.agent_id == agent_id)
        job_q = job_q.filter(SelfOptJob.agent_id == agent_id)
        exp_q = exp_q.filter(SelfOptABExperiment.agent_id == agent_id)

    pending_review = prop_q.filter(SelfOptProposal.status == "pending_review").count()
    evaluated = prop_q.filter(SelfOptProposal.status == "evaluated").count()
    ab_running_props = prop_q.filter(SelfOptProposal.status == "ab_running").count()
    promoted = prop_q.filter(SelfOptProposal.status == "promoted").count()
    rejected = prop_q.filter(SelfOptProposal.status.in_(["rejected", "aborted"])).count()

    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    jobs_week = job_q.filter(SelfOptJob.created_at >= week_ago).count()
    latest_job = job_q.order_by(SelfOptJob.created_at.desc()).first()
    running_exps = exp_q.filter(SelfOptABExperiment.status == "running").count()
    latest_exp = exp_q.order_by(SelfOptABExperiment.started_at.desc()).first()

    # Determine current stage for selected agent
    stage = "idle"
    if latest_exp and latest_exp.status == "running":
        stage = "ab"
    elif pending_review > 0:
        stage = "review"
    elif latest_job and latest_job.status == "running":
        stage = "reflect"
    elif latest_job and latest_job.status == "done":
        stats = latest_job.stats_json or {}
        if int(stats.get("trajectory_count") or 0) > 0 and pending_review == 0 and ab_running_props == 0:
            if promoted or rejected:
                stage = "decide"
            elif evaluated > 0:
                stage = "gate"
            else:
                stage = "collect"
        elif int(stats.get("trajectory_count") or 0) > 0:
            stage = "gate" if evaluated else "reflect"
    elif latest_job:
        stage = "collect"

    stages = [
        {"key": "collect", "label": "轨迹采集", "active": stage == "collect"},
        {"key": "reflect", "label": "反思提案", "active": stage == "reflect"},
        {"key": "gate", "label": "离线门禁", "active": stage == "gate"},
        {"key": "review", "label": "人工审阅", "active": stage == "review"},
        {"key": "ab", "label": "轮询 A/B", "active": stage == "ab"},
        {"key": "decide", "label": "正式上线 / 保持当前", "active": stage == "decide"},
    ]

    return {
        "enabled": cfg.enabled,
        "ab_enabled": cfg.ab_enabled,
        "agent_ids": allow,
        "allowlist_count": len(allow),
        "pending_review": pending_review,
        "evaluated": evaluated,
        "ab_running_proposals": ab_running_props,
        "promoted": promoted,
        "rejected": rejected,
        "jobs_week": jobs_week,
        "running_experiments": running_exps,
        "current_stage": stage,
        "stages": stages,
        "latest_job": _job_dict(latest_job) if latest_job else None,
        "latest_experiment": _exp_dict(latest_exp) if latest_exp else None,
    }


@router.post("/jobs")
async def create_job(data: JobCreate, user: CurrentUser, db: Session = Depends(get_db)):
    _require_global_enabled()
    try:
        job = await run_selfopt_job(
            db,
            agent_id=data.agent_id,
            window_days=data.window_days,
            dataset_id=data.dataset_id,
            reflect_model_service_id=data.reflect_model_service_id,
        )
    except RuntimeError as e:
        msg = str(e)
        if "disabled" in msg:
            raise HTTPException(status_code=403, detail=msg)
        if "not_found" in msg:
            raise HTTPException(status_code=404, detail="Agent 不存在")
        raise HTTPException(status_code=400, detail=msg)
    return _job_dict(job)


@router.get("/jobs")
def list_jobs(
    agent_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    q = db.query(SelfOptJob)
    if agent_id:
        q = q.filter(SelfOptJob.agent_id == agent_id)
    total = q.count()
    items = (
        q.order_by(SelfOptJob.created_at.desc())
        .offset(max(0, (page - 1) * page_size))
        .limit(page_size)
        .all()
    )
    return {"total": total, "page": page, "page_size": page_size, "items": [_job_dict(j) for j in items]}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(SelfOptJob).filter(SelfOptJob.job_id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job 不存在")
    return _job_dict(job)


@router.get("/jobs/{job_id}/detail")
def get_job_detail(job_id: str, db: Session = Depends(get_db)):
    """Single-job hub payload: stages, proposals, experiments, stage_payloads."""
    job = db.query(SelfOptJob).filter(SelfOptJob.job_id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job 不存在")

    proposals = (
        db.query(SelfOptProposal)
        .filter(SelfOptProposal.job_id == job_id)
        .order_by(SelfOptProposal.created_at.desc())
        .all()
    )
    proposal_ids = [p.proposal_id for p in proposals]
    experiments: List[SelfOptABExperiment] = []
    if proposal_ids:
        experiments = (
            db.query(SelfOptABExperiment)
            .filter(SelfOptABExperiment.proposal_id.in_(proposal_ids))
            .order_by(SelfOptABExperiment.started_at.desc())
            .all()
        )

    bundle = _job_stage_bundle(job, proposals, experiments)
    return {
        "job": _job_dict(job),
        "stages": bundle["stages"],
        "current_stage": bundle["current_stage"],
        "proposals": [_proposal_dict(p) for p in proposals],
        "experiments": [_exp_dict(e) for e in experiments],
        "stage_payloads": bundle["stage_payloads"],
    }


@router.get("/proposals")
def list_proposals(
    agent_id: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    q = db.query(SelfOptProposal)
    if agent_id:
        q = q.filter(SelfOptProposal.agent_id == agent_id)
    if status:
        q = q.filter(SelfOptProposal.status == status)
    total = q.count()
    items = (
        q.order_by(SelfOptProposal.created_at.desc())
        .offset(max(0, (page - 1) * page_size))
        .limit(page_size)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_proposal_dict(p) for p in items],
    }


@router.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: str, db: Session = Depends(get_db)):
    p = db.query(SelfOptProposal).filter(SelfOptProposal.proposal_id == proposal_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="提案不存在")
    return _proposal_dict(p)


@router.post("/proposals/{proposal_id}/reject")
def reject_proposal(
    proposal_id: str,
    data: DecisionRequest,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    """Ignore / abandon a proposal without starting A/B."""
    _require_global_enabled()
    p = db.query(SelfOptProposal).filter(SelfOptProposal.proposal_id == proposal_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="提案不存在")
    if p.status in ("promoted", "ab_running", "rejected", "aborted"):
        raise HTTPException(status_code=400, detail=f"当前状态不可忽略: {p.status}")
    from models import now_utc

    p.status = "rejected"
    report = dict(p.eval_report_json or {})
    report["ignored"] = True
    report["ignored_by"] = user.user_id
    report["ignored_at"] = str(now_utc())
    if data.note:
        report["ignore_note"] = data.note
    p.eval_report_json = report
    p.updated_at = now_utc()
    db.commit()
    db.refresh(p)
    return _proposal_dict(p)


@router.post("/proposals/{proposal_id}/start-ab")
def start_ab(
    proposal_id: str,
    data: StartAbRequest,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    _require_global_enabled()
    p = db.query(SelfOptProposal).filter(SelfOptProposal.proposal_id == proposal_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="提案不存在")
    if p.status not in ("pending_review", "evaluated", "approved"):
        raise HTTPException(status_code=400, detail=f"当前状态不可启动 A/B: {p.status}")
    exp = start_ab_from_proposal(
        db,
        proposal=p,
        user_id=user.user_id,
        target_sessions=data.target_sessions,
        min_sessions=data.min_sessions,
    )
    return _exp_dict(exp)


@router.get("/ab")
def list_ab(
    agent_id: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    q = db.query(SelfOptABExperiment)
    if agent_id:
        q = q.filter(SelfOptABExperiment.agent_id == agent_id)
    if status:
        q = q.filter(SelfOptABExperiment.status == status)
    total = q.count()
    items = (
        q.order_by(SelfOptABExperiment.started_at.desc())
        .offset(max(0, (page - 1) * page_size))
        .limit(page_size)
        .all()
    )
    return {"total": total, "page": page, "page_size": page_size, "items": [_exp_dict(e) for e in items]}


@router.get("/ab/{experiment_id}")
def get_ab(experiment_id: str, db: Session = Depends(get_db)):
    e = (
        db.query(SelfOptABExperiment)
        .filter(SelfOptABExperiment.experiment_id == experiment_id)
        .first()
    )
    if not e:
        raise HTTPException(status_code=404, detail="实验不存在")
    return _exp_dict(e)


@router.get("/ab/{experiment_id}/report")
def get_ab_report(experiment_id: str, db: Session = Depends(get_db)):
    report = build_ab_report(db, experiment_id=experiment_id)
    if not report:
        raise HTTPException(status_code=404, detail="实验不存在")
    return report


@router.post("/ab/{experiment_id}/promote")
def promote_ab(
    experiment_id: str,
    data: DecisionRequest,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    _require_global_enabled()
    exp = promote_experiment(
        db, experiment_id=experiment_id, user_id=user.user_id, note=data.note
    )
    return _exp_dict(exp)


@router.post("/ab/{experiment_id}/keep-control")
def keep_control_ab(
    experiment_id: str,
    data: DecisionRequest,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    _require_global_enabled()
    exp = keep_control(
        db, experiment_id=experiment_id, user_id=user.user_id, note=data.note
    )
    return _exp_dict(exp)


@router.post("/ab/{experiment_id}/abort")
def abort_ab(
    experiment_id: str,
    data: DecisionRequest,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    _require_global_enabled()
    exp = abort_experiment(
        db, experiment_id=experiment_id, user_id=user.user_id, note=data.note
    )
    return _exp_dict(exp)


@router.get("/agents/{agent_id}/policy")
def get_agent_policy(agent_id: str, db: Session = Depends(get_db)):
    from services.selfopt.config import is_enabled_for_agent

    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    cfg = load_selfopt_config()
    return {
        "agent_id": agent_id,
        "global_enabled": cfg.enabled,
        "ab_enabled": cfg.ab_enabled,
        "agent_ids": list(cfg.agent_ids or []),
        "in_allowlist": agent_id in (cfg.agent_ids or []),
        "selfopt_enabled": agent.selfopt_enabled,
        "effective_enabled": is_enabled_for_agent(agent, cfg),
        "reflect_model_service_id": cfg.reflect_model_service_id or "",
    }


@router.put("/agents/{agent_id}/policy")
def update_agent_policy(
    agent_id: str,
    data: AgentPolicyUpdate,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    _require_global_enabled()
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    agent.selfopt_enabled = data.selfopt_enabled
    db.commit()
    return {
        "agent_id": agent_id,
        "selfopt_enabled": agent.selfopt_enabled,
    }
