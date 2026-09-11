"""Offline eval gate for SelfOpt proposals (lightweight when no dataset)."""
from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from models import EvalDataset, EvalJob, SelfOptProposal, now_utc


def run_offline_eval_gate(
    db: Session,
    *,
    proposal: SelfOptProposal,
    dataset_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Attach a minimal eval report. Full rerun jobs are optional if dataset exists."""
    report: Dict[str, Any] = {
        "passed": True,
        "mode": "smoke",
        "notes": "无绑定 Dataset 时使用冒烟门禁（diff/风险校验已通过）",
        "baseline": {},
        "candidate": {},
        "delta": {},
    }
    ds = None
    if dataset_id:
        ds = db.query(EvalDataset).filter(EvalDataset.dataset_id == dataset_id).first()
    if not ds:
        ds = (
            db.query(EvalDataset)
            .filter(EvalDataset.agent_id == proposal.agent_id)
            .order_by(EvalDataset.created_at.desc())
            .first()
        )
    if ds:
        report["mode"] = "dataset_linked"
        report["dataset_id"] = ds.dataset_id
        report["dataset_name"] = ds.name
        report["notes"] = "已关联回归 Dataset；建议在评测中心对 candidate 跑 rerun 对比"
        # Record latest job ids if any for UI linking
        jobs = (
            db.query(EvalJob)
            .filter(EvalJob.dataset_id == ds.dataset_id)
            .order_by(EvalJob.created_at.desc())
            .limit(2)
            .all()
        )
        if jobs:
            proposal.eval_before_job_id = jobs[0].job_id
            if len(jobs) > 1:
                proposal.eval_after_job_id = jobs[1].job_id
            report["linked_job_ids"] = [j.job_id for j in jobs]

    # Hard fail empty diffs
    if not (proposal.diff_json or {}):
        report["passed"] = False
        report["notes"] = "空 diff，不可进入审阅/A/B"

    proposal.eval_report_json = report
    proposal.status = "evaluated" if report["passed"] else "drafted"
    if report["passed"]:
        proposal.status = "pending_review"
    proposal.updated_at = now_utc()
    db.flush()
    return report
