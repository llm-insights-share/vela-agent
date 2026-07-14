"""Vela 内置 ScreenPilot 审批流（T3 动作）。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from models import HITLApproval


def _is_screenpilot_approval(row: HITLApproval) -> bool:
    return (row.tool_name or "").startswith(("cu_", "ui_"))


def _risk_tier(row: HITLApproval) -> str:
    args = row.tool_args or {}
    preview = args.get("preview_payload") or {}
    return args.get("risk_tier") or preview.get("risk_tier") or "T1"


def list_pending_approvals(
    db: Session,
    *,
    risk_tier: Optional[str] = None,
    status: str = "PENDING",
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """平台级审批收件箱：聚合 ScreenPilot HITL 工单。"""
    rows = (
        db.query(HITLApproval)
        .filter(HITLApproval.status == status)
        .order_by(HITLApproval.created_at.desc())
        .limit(min(limit, 200))
        .all()
    )
    out: List[Dict[str, Any]] = []
    for row in rows:
        if not _is_screenpilot_approval(row):
            continue
        tier = _risk_tier(row)
        if risk_tier and tier != risk_tier:
            continue
        args = row.tool_args or {}
        preview = args.get("preview_payload") or {}
        out.append(
            {
                "approval_id": row.approval_id,
                "session_id": row.session_id,
                "agent_id": row.agent_id,
                "tool_name": row.tool_name,
                "risk_tier": tier,
                "status": row.status,
                "flow_kind": args.get("flow_kind", "vela_internal"),
                "action": preview.get("action") or args.get("action", ""),
                "target_label": preview.get("target_label") or "",
                "url": preview.get("url", ""),
                "preview_payload": preview,
                "reviewer": row.reviewer or "",
                "review_comment": row.review_comment or "",
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
            }
        )
    return out


def get_approval_detail(db: Session, approval_id: str) -> Optional[Dict[str, Any]]:
    row = db.query(HITLApproval).filter(HITLApproval.approval_id == approval_id).first()
    if not row or not _is_screenpilot_approval(row):
        return None
    items = list_pending_approvals(db, status=row.status, limit=200)
    for item in items:
        if item["approval_id"] == approval_id:
            return item
    # fallback build
    args = row.tool_args or {}
    preview = args.get("preview_payload") or {}
    return {
        "approval_id": row.approval_id,
        "session_id": row.session_id,
        "agent_id": row.agent_id,
        "tool_name": row.tool_name,
        "risk_tier": _risk_tier(row),
        "status": row.status,
        "preview_payload": preview,
        "tool_args": args,
        "reviewer": row.reviewer or "",
        "review_comment": row.review_comment or "",
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
    }


def mark_t3_internal_flow(tool_args: Dict[str, Any]) -> Dict[str, Any]:
    """T3 工单标记为 Vela 内置审批流。"""
    args = dict(tool_args)
    args["flow_kind"] = "vela_internal"
    args["requires_inbox"] = True
    return args
