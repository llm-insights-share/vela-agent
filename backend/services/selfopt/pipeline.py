"""SelfOpt batch pipeline: collect → reflect → propose → eval gate."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from models import Agent, ModelService, SelfOptJob, gen_uuid, now_utc
from services.selfopt.collector import collect_trajectories
from services.selfopt.config import (
    is_enabled_for_agent,
    is_globally_enabled,
    load_selfopt_config,
    resolve_reflect_model_service_id,
)
from services.selfopt.eval_gate import run_offline_eval_gate
from services.selfopt.proposal import findings_to_proposals
from services.selfopt.reflect import reflect


def _make_job_label(db: Session, agent: Agent, when: Optional[datetime] = None) -> str:
    """Generate human-readable job label: {agent.name}-{YYYYMMDD}-{seq}."""
    now = when or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    date_str = now.strftime("%Y%m%d")
    name_part = (agent.name or "").strip() or (agent.agent_id[:8] if agent.agent_id else "agent")

    # Prefer label-prefix count so seq stays stable across naive/aware timestamps
    prefix = f"{name_part}-{date_str}-"
    existing = (
        db.query(SelfOptJob)
        .filter(
            SelfOptJob.agent_id == agent.agent_id,
            SelfOptJob.job_label.like(f"{prefix}%"),
        )
        .count()
    )
    seq = existing + 1
    return f"{name_part}-{date_str}-{seq:02d}"


async def run_selfopt_job(
    db: Session,
    *,
    agent_id: str,
    window_days: int = 7,
    dataset_id: Optional[str] = None,
    reflect_model_service_id: Optional[str] = None,
) -> SelfOptJob:
    cfg = load_selfopt_config()
    if not is_globally_enabled(cfg):
        raise RuntimeError("selfopt_disabled")

    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if not agent:
        raise RuntimeError("agent_not_found")
    if not is_enabled_for_agent(agent, cfg):
        raise RuntimeError("selfopt_disabled_for_agent")

    resolved_msid = resolve_reflect_model_service_id(
        agent, override=reflect_model_service_id, cfg=cfg
    )
    reflect_svc = (
        db.query(ModelService)
        .filter(ModelService.model_service_id == resolved_msid)
        .first()
    )

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=max(1, window_days))
    job_label = _make_job_label(db, agent, when=end)
    job = SelfOptJob(
        job_id=gen_uuid(),
        agent_id=agent_id,
        job_label=job_label,
        window_start=start,
        window_end=end,
        status="running",
        stats_json={
            "reflect_model_service_id": resolved_msid,
            "reflect_model_name": getattr(reflect_svc, "model_name", "") or "",
        },
        created_at=now_utc(),
        updated_at=now_utc(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    try:
        trajectories = collect_trajectories(
            db, agent_id=agent_id, window_start=start, window_end=end
        )
        findings = await reflect(
            db,
            agent=agent,
            trajectories=trajectories,
            model_service_id=resolved_msid,
        )
        proposals = findings_to_proposals(
            db, job_id=job.job_id, agent=agent, findings=findings
        )
        for p in proposals:
            run_offline_eval_gate(db, proposal=p, dataset_id=dataset_id)

        job.status = "done"
        job.stats_json = {
            **(job.stats_json or {}),
            "trajectory_count": len(trajectories),
            "finding_count": len(findings),
            "proposal_count": len(proposals),
            "proposal_ids": [p.proposal_id for p in proposals],
            "reflect_model_service_id": resolved_msid,
            "reflect_model_name": getattr(reflect_svc, "model_name", "") or "",
        }
        job.updated_at = now_utc()
        db.commit()
        db.refresh(job)
        return job
    except Exception as e:
        job.status = "failed"
        job.stats_json = {**(job.stats_json or {}), "error": str(e)}
        job.updated_at = now_utc()
        db.commit()
        raise
