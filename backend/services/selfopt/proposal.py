"""Build and persist SelfOpt proposals from findings."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from models import (
    Agent,
    AgentVersion,
    SelfOptProposal,
    VersionStatus,
    ChangeType,
    gen_uuid,
    now_utc,
)
from services.selfopt.risk import classify_risk_tier, is_forbidden_change_kind, validate_diff_json


def apply_diff_to_snapshot(base_snapshot: Dict[str, Any], diff: Dict[str, Any]) -> Dict[str, Any]:
    snap = dict(base_snapshot or {})
    append = diff.get("system_prompt_append")
    if isinstance(append, str) and append.strip():
        snap["system_prompt"] = (snap.get("system_prompt") or "") + append
    retrieval = diff.get("retrieval") if isinstance(diff.get("retrieval"), dict) else {}
    comp = dict(snap.get("composition_config") or {})
    knowledge = dict(comp.get("knowledge") or {})
    if "top_k" in retrieval:
        knowledge["top_k"] = int(retrieval["top_k"])
    if "similarity_threshold" in retrieval:
        knowledge["similarity_threshold"] = float(retrieval["similarity_threshold"])
    if knowledge:
        comp["knowledge"] = knowledge
        snap["composition_config"] = comp
    for key in ("max_iterations", "timeout_seconds", "step_timeout_seconds"):
        if key in diff and isinstance(diff[key], int):
            snap[key] = diff[key]
    return snap


def create_candidate_version(
    db: Session,
    *,
    agent: Agent,
    base_version: Optional[AgentVersion],
    diff: Dict[str, Any],
    summary: str,
) -> AgentVersion:
    base_snap = dict((base_version.snapshot if base_version else None) or {})
    if not base_snap:
        base_snap = {
            "name": agent.name,
            "description": agent.description,
            "model_service_id": agent.model_service_id,
            "system_prompt": agent.system_prompt,
            "dept_id": agent.dept_id,
            "autonomy_level": agent.autonomy_level,
            "max_concurrent_sessions": agent.max_concurrent_sessions,
            "token_budget": agent.token_budget,
            "tool_permissions": agent.tool_permissions,
            "tags": agent.tags,
            "max_iterations": agent.max_iterations,
            "step_timeout_seconds": agent.step_timeout_seconds,
            "timeout_seconds": agent.timeout_seconds,
            "tool_retry_count": agent.tool_retry_count,
            "tool_retry_backoff": agent.tool_retry_backoff,
            "allow_repeat_tool_calls": agent.allow_repeat_tool_calls,
            "max_repeat_threshold": agent.max_repeat_threshold,
            "single_call_token_limit": agent.single_call_token_limit,
            "agent_type": agent.agent_type.value if agent.agent_type else "SINGLE",
            "composition_config": agent.composition_config or {},
            "workflow_definition": agent.workflow_definition or {},
        }
    new_snap = apply_diff_to_snapshot(base_snap, diff)
    last = (
        db.query(AgentVersion)
        .filter(AgentVersion.agent_id == agent.agent_id)
        .order_by(AgentVersion.version_seq.desc())
        .first()
    )
    seq = (last.version_seq if last else 0) + 1
    version = AgentVersion(
        version_id=gen_uuid(),
        agent_id=agent.agent_id,
        version=f"selfopt-{seq}",
        version_seq=seq,
        change_type=ChangeType.PATCH,
        change_summary=summary[:500] or "SelfOpt candidate",
        snapshot=new_snap,
        status=VersionStatus.TESTING,
    )
    db.add(version)
    db.flush()
    return version


def findings_to_proposals(
    db: Session,
    *,
    job_id: str,
    agent: Agent,
    findings: List[Dict[str, Any]],
) -> List[SelfOptProposal]:
    base = None
    if agent.current_version_id:
        base = (
            db.query(AgentVersion)
            .filter(AgentVersion.version_id == agent.current_version_id)
            .first()
        )
    created: List[SelfOptProposal] = []
    for f in findings:
        kind = str(f.get("suggested_change_kind") or "prompt_fewshot")
        if is_forbidden_change_kind(kind):
            continue
        diff = f.get("diff") if isinstance(f.get("diff"), dict) else {}
        try:
            validate_diff_json(diff)
        except ValueError:
            continue
        tier = classify_risk_tier(kind)
        evidence = list(f.get("cited_run_ids") or [])
        p = SelfOptProposal(
            proposal_id=gen_uuid(),
            job_id=job_id,
            agent_id=agent.agent_id,
            base_version_id=agent.current_version_id,
            change_kind=kind,
            risk_tier=tier,
            diff_json=diff,
            rationale=str(f.get("rationale") or "")[:2000],
            evidence_run_ids=evidence,
            eval_report_json={},
            status="pending_review",
            candidate_version_id=None,
            created_at=now_utc(),
            updated_at=now_utc(),
        )
        try:
            cand = create_candidate_version(
                db,
                agent=agent,
                base_version=base,
                diff=diff,
                summary=p.rationale or kind,
            )
            p.candidate_version_id = cand.version_id
        except Exception:
            pass
        db.add(p)
        created.append(p)
    db.flush()
    return created
