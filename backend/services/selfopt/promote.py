"""Start A/B, promote treatment, keep control, abort."""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session
from fastapi import HTTPException

from models import (
    Agent,
    AgentVersion,
    SelfOptABExperiment,
    SelfOptProposal,
    VersionStatus,
    gen_uuid,
    now_utc,
)
from services.selfopt.config import is_ab_enabled, is_enabled_for_agent, load_selfopt_config
from services.selfopt.risk import classify_risk_tier


def _require_enabled(agent: Agent) -> None:
    cfg = load_selfopt_config()
    if not is_ab_enabled(cfg) or not is_enabled_for_agent(agent, cfg):
        raise HTTPException(status_code=403, detail="selfopt_disabled")


def start_ab_from_proposal(
    db: Session,
    *,
    proposal: SelfOptProposal,
    user_id: str = "",
    target_sessions: int = 40,
    min_sessions: int = 10,
) -> SelfOptABExperiment:
    agent = db.query(Agent).filter(Agent.agent_id == proposal.agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    _require_enabled(agent)

    if classify_risk_tier(proposal.change_kind) == "FORBIDDEN":
        raise HTTPException(status_code=400, detail="FORBIDDEN 变更不可进入 A/B")

    if proposal.risk_tier == "T2" and proposal.status not in ("pending_review", "evaluated", "approved"):
        # Allow pending_review with explicit start (acts as approval for starting AB)
        pass

    running = (
        db.query(SelfOptABExperiment)
        .filter(
            SelfOptABExperiment.agent_id == agent.agent_id,
            SelfOptABExperiment.status == "running",
        )
        .first()
    )
    if running:
        raise HTTPException(status_code=409, detail="该 Agent 已有运行中的 A/B 实验")

    control_vid = agent.current_version_id
    if not control_vid:
        raise HTTPException(status_code=400, detail="Agent 缺少 current_version_id")

    treatment_vid = proposal.candidate_version_id
    if not treatment_vid:
        raise HTTPException(status_code=400, detail="提案缺少候选版本")

    treatment = (
        db.query(AgentVersion)
        .filter(AgentVersion.version_id == treatment_vid)
        .first()
    )
    if not treatment:
        raise HTTPException(status_code=400, detail="候选版本不存在")

    exp = SelfOptABExperiment(
        experiment_id=gen_uuid(),
        agent_id=agent.agent_id,
        proposal_id=proposal.proposal_id,
        control_version_id=control_vid,
        treatment_version_id=treatment_vid,
        strategy="round_robin",
        rr_counter=0,
        status="running",
        started_at=now_utc(),
        min_sessions=min_sessions,
        target_sessions=target_sessions,
        decision="pending",
        decided_by="",
        decision_note="",
    )
    db.add(exp)
    proposal.status = "ab_running"
    proposal.updated_at = now_utc()
    db.commit()
    db.refresh(exp)
    return exp


def promote_experiment(
    db: Session,
    *,
    experiment_id: str,
    user_id: str = "",
    note: str = "",
) -> SelfOptABExperiment:
    exp = (
        db.query(SelfOptABExperiment)
        .filter(SelfOptABExperiment.experiment_id == experiment_id)
        .first()
    )
    if not exp:
        raise HTTPException(status_code=404, detail="实验不存在")
    if exp.status != "running":
        raise HTTPException(status_code=400, detail="仅 running 实验可正式上线")

    agent = db.query(Agent).filter(Agent.agent_id == exp.agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    _require_enabled(agent)

    treatment = (
        db.query(AgentVersion)
        .filter(AgentVersion.version_id == exp.treatment_version_id)
        .first()
    )
    if not treatment:
        raise HTTPException(status_code=400, detail="候选版本不存在")

    # Apply snapshot fields onto Agent row, then point current_version_id
    snap = treatment.snapshot or {}
    for field in (
        "system_prompt",
        "model_service_id",
        "max_iterations",
        "step_timeout_seconds",
        "timeout_seconds",
        "tool_retry_count",
        "tool_retry_backoff",
        "allow_repeat_tool_calls",
        "max_repeat_threshold",
        "single_call_token_limit",
        "composition_config",
        "workflow_definition",
        "tool_permissions",
        "token_budget",
        "autonomy_level",
        "description",
        "tags",
    ):
        if field in snap and snap[field] is not None:
            setattr(agent, field, snap[field])

    if agent.current_version_id and agent.current_version_id != treatment.version_id:
        prev = (
            db.query(AgentVersion)
            .filter(AgentVersion.version_id == agent.current_version_id)
            .first()
        )
        if prev and prev.status == VersionStatus.PUBLISHED:
            prev.status = VersionStatus.DEPRECATED

    treatment.status = VersionStatus.PUBLISHED
    agent.current_version_id = treatment.version_id
    agent.updated_at = now_utc()

    exp.status = "completed"
    exp.decision = "promote"
    exp.decided_by = user_id or ""
    exp.decided_at = now_utc()
    exp.decision_note = note or ""
    exp.ended_at = now_utc()

    if exp.proposal_id:
        prop = (
            db.query(SelfOptProposal)
            .filter(SelfOptProposal.proposal_id == exp.proposal_id)
            .first()
        )
        if prop:
            prop.status = "promoted"
            prop.updated_at = now_utc()

    db.commit()
    db.refresh(exp)
    return exp


def keep_control(
    db: Session,
    *,
    experiment_id: str,
    user_id: str = "",
    note: str = "",
) -> SelfOptABExperiment:
    exp = (
        db.query(SelfOptABExperiment)
        .filter(SelfOptABExperiment.experiment_id == experiment_id)
        .first()
    )
    if not exp:
        raise HTTPException(status_code=404, detail="实验不存在")
    if exp.status != "running":
        raise HTTPException(status_code=400, detail="仅 running 实验可结束")

    exp.status = "completed"
    exp.decision = "keep_control"
    exp.decided_by = user_id or ""
    exp.decided_at = now_utc()
    exp.decision_note = note or ""
    exp.ended_at = now_utc()

    if exp.proposal_id:
        prop = (
            db.query(SelfOptProposal)
            .filter(SelfOptProposal.proposal_id == exp.proposal_id)
            .first()
        )
        if prop:
            prop.status = "rejected"
            prop.updated_at = now_utc()

    db.commit()
    db.refresh(exp)
    return exp


def abort_experiment(
    db: Session,
    *,
    experiment_id: str,
    user_id: str = "",
    note: str = "",
) -> SelfOptABExperiment:
    exp = (
        db.query(SelfOptABExperiment)
        .filter(SelfOptABExperiment.experiment_id == experiment_id)
        .first()
    )
    if not exp:
        raise HTTPException(status_code=404, detail="实验不存在")
    if exp.status != "running":
        raise HTTPException(status_code=400, detail="仅 running 实验可终止")

    exp.status = "aborted"
    exp.decision = "keep_control"
    exp.decided_by = user_id or ""
    exp.decided_at = now_utc()
    exp.decision_note = note or "aborted"
    exp.ended_at = now_utc()

    if exp.proposal_id:
        prop = (
            db.query(SelfOptProposal)
            .filter(SelfOptProposal.proposal_id == exp.proposal_id)
            .first()
        )
        if prop:
            prop.status = "aborted"
            prop.updated_at = now_utc()

    db.commit()
    db.refresh(exp)
    return exp


def abort_all_running_for_disable(db: Session) -> int:
    """When feature flag turns off, abort all running experiments."""
    rows = (
        db.query(SelfOptABExperiment)
        .filter(SelfOptABExperiment.status == "running")
        .all()
    )
    n = 0
    for exp in rows:
        exp.status = "aborted"
        exp.decision = "keep_control"
        exp.decided_at = now_utc()
        exp.decision_note = "selfopt_disabled"
        exp.ended_at = now_utc()
        n += 1
        if exp.proposal_id:
            prop = (
                db.query(SelfOptProposal)
                .filter(SelfOptProposal.proposal_id == exp.proposal_id)
                .first()
            )
            if prop and prop.status == "ab_running":
                prop.status = "aborted"
                prop.updated_at = now_utc()
    if n:
        db.commit()
    return n
