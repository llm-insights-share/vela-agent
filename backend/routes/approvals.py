"""统一审批中心：聚合通用 HITL 与驭屏审批（均存于 hitl_approvals）。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from deps import CurrentUser
from models import Agent, HITLApproval, Session as AgentSession, User
from schemas import ApprovalCenterItem, PaginatedResponse

router = APIRouter(prefix="/api/v1/approvals", tags=["approvals"])


def _is_screenpilot(tool_name: str) -> bool:
    return (tool_name or "").startswith(("cu_", "ui_"))


def _category(tool_name: str) -> str:
    name = tool_name or ""
    if _is_screenpilot(name):
        return "screenpilot"
    if name == "__delivery__":
        return "delivery"
    if name == "__workflow_hitl__":
        return "workflow"
    return "tool"


def _summary(row: HITLApproval, category: str) -> str:
    args = row.tool_args or {}
    preview = args.get("preview_payload") or {}
    if category == "screenpilot":
        action = preview.get("action") or args.get("action") or row.tool_name
        target = preview.get("target_label") or ""
        return f"{action} {target}".strip() or row.tool_name
    if category == "delivery":
        user_msg = (args.get("user_message") or "").strip()
        if user_msg:
            return user_msg[:120]
        final = (args.get("final_result") or "").strip()
        return (final[:120] + ("…" if len(final) > 120 else "")) if final else "多 Agent 交付审批"
    if category == "workflow":
        return f"工作流节点 {args.get('node_id') or ''}".strip() or "工作流 HITL"
    return f"工具审批：{row.tool_name}"


def _risk_tier(row: HITLApproval) -> Optional[str]:
    if not _is_screenpilot(row.tool_name or ""):
        return None
    args = row.tool_args or {}
    preview = args.get("preview_payload") or {}
    return args.get("risk_tier") or preview.get("risk_tier") or "T1"


def _session_ids_approvable_by_user(db: Session, user: User) -> Set[str]:
    """会话归属：用户自己发起的会话，以及同 trace 下由 Agent 拉起的子会话。"""
    owned = (
        db.query(AgentSession.session_id, AgentSession.trace_id)
        .filter(AgentSession.caller_id == user.user_id)
        .all()
    )
    session_ids = {row.session_id for row in owned}
    trace_ids = {row.trace_id for row in owned if row.trace_id}
    if trace_ids:
        child_ids = (
            db.query(AgentSession.session_id)
            .filter(
                AgentSession.trace_id.in_(trace_ids),
                AgentSession.caller_type.in_(["AGENT", "agent"]),
            )
            .all()
        )
        session_ids.update(row.session_id for row in child_ids)
    return session_ids


def _visible_query(db: Session, user: CurrentUser):
    """仅返回当前登录用户可审批的工单（不再因 admin 放开全库）。"""
    session_ids = _session_ids_approvable_by_user(db, user)
    q = (
        db.query(HITLApproval, AgentSession, Agent)
        .outerjoin(AgentSession, AgentSession.session_id == HITLApproval.session_id)
        .outerjoin(Agent, Agent.agent_id == HITLApproval.agent_id)
    )
    if not session_ids:
        return q.filter(False)
    return q.filter(HITLApproval.session_id.in_(session_ids))


def _to_item(
    row: HITLApproval,
    session: Optional[AgentSession],
    agent: Optional[Agent],
    *,
    include_payload: bool = False,
) -> ApprovalCenterItem:
    category = _category(row.tool_name or "")
    args = row.tool_args or {}
    preview = args.get("preview_payload") or {}
    item = ApprovalCenterItem(
        approval_id=row.approval_id,
        session_id=row.session_id,
        agent_id=row.agent_id,
        agent_name=(agent.name if agent else "") or "",
        session_title=(session.title if session else "") or "",
        tool_name=row.tool_name or "",
        category=category,
        status=row.status or "",
        summary=_summary(row, category),
        risk_tier=_risk_tier(row),
        action=(preview.get("action") or args.get("action") or None) if category == "screenpilot" else None,
        target_label=(preview.get("target_label") or None) if category == "screenpilot" else None,
        url=(preview.get("url") or None) if category == "screenpilot" else None,
        flow_kind=(args.get("flow_kind") or None) if category == "screenpilot" else None,
        reviewer=row.reviewer or "",
        review_comment=row.review_comment or "",
        created_at=row.created_at,
        reviewed_at=row.reviewed_at,
    )
    if include_payload:
        item.tool_args = args
        item.preview_payload = preview if category == "screenpilot" else None
    return item


def _user_can_access(db: Session, user: CurrentUser, session_id: str) -> bool:
    return session_id in _session_ids_approvable_by_user(db, user)


@router.get("", response_model=PaginatedResponse)
def list_approvals(
    user: CurrentUser,
    db: Session = Depends(get_db),
    status: str = Query("PENDING", description="PENDING|APPROVED|REJECTED|ALL"),
    category: str = Query("all", description="all|hitl|screenpilot|delivery|workflow|tool"),
    risk_tier: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    q = _visible_query(db, user)
    status_u = (status or "PENDING").upper()
    if status_u != "ALL":
        q = q.filter(HITLApproval.status == status_u)

    rows = q.order_by(HITLApproval.created_at.desc()).all()

    cat = (category or "all").lower()
    items: List[ApprovalCenterItem] = []
    for row, session, agent in rows:
        item = _to_item(row, session, agent)
        if cat == "screenpilot" and item.category != "screenpilot":
            continue
        if cat == "hitl" and item.category == "screenpilot":
            continue
        if cat in ("delivery", "workflow", "tool") and item.category != cat:
            continue
        if risk_tier and item.category == "screenpilot" and item.risk_tier != risk_tier:
            continue
        if risk_tier and item.category != "screenpilot":
            continue
        items.append(item)

    total = len(items)
    start = (page - 1) * page_size
    page_items = items[start : start + page_size]
    return PaginatedResponse(total=total, page=page, page_size=page_size, items=page_items)


@router.get("/{approval_id}", response_model=ApprovalCenterItem)
def get_approval(
    approval_id: str,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    row = (
        db.query(HITLApproval, AgentSession, Agent)
        .outerjoin(AgentSession, AgentSession.session_id == HITLApproval.session_id)
        .outerjoin(Agent, Agent.agent_id == HITLApproval.agent_id)
        .filter(HITLApproval.approval_id == approval_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="审批工单不存在")
    approval, session, agent = row
    if not _user_can_access(db, user, approval.session_id):
        raise HTTPException(status_code=403, detail="无权查看该审批")
    return _to_item(approval, session, agent, include_payload=True)
