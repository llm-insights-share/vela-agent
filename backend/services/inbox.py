from __future__ import annotations

from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models import Agent, InboxMessage, Session as SessionModel, SessionStatus, now_utc

_ASYNC_STATUS_NOTIFY = {
    SessionStatus.HITL_WAIT: ("会话任务待审批", "info"),
    SessionStatus.ERROR: ("会话任务失败", "warning"),
    SessionStatus.ACTIVE: ("会话任务已完成", "success"),
    SessionStatus.IDLE: ("会话任务已完成", "success"),
    SessionStatus.CLOSED: ("会话任务已完成", "success"),
}


def notify_user(
    db: Session,
    *,
    user_id: str,
    title: str,
    body: str = "",
    level: str = "info",
    link_path: str = "",
    related_type: str = "",
    related_id: str = "",
) -> Optional[InboxMessage]:
    uid = (user_id or "").strip()
    if not uid:
        return None
    if related_type and related_id:
        existing = (
            db.query(InboxMessage)
            .filter(
                InboxMessage.user_id == uid,
                InboxMessage.related_type == related_type,
                InboxMessage.related_id == related_id,
            )
            .first()
        )
        if existing:
            return existing
    msg = InboxMessage(
        user_id=uid,
        title=title,
        body=body,
        level=level,
        link_path=link_path or "",
        related_type=related_type or "",
        related_id=related_id or "",
        is_read=False,
    )
    db.add(msg)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return (
            db.query(InboxMessage)
            .filter(
                InboxMessage.user_id == uid,
                InboxMessage.related_type == related_type,
                InboxMessage.related_id == related_id,
            )
            .first()
        )
    db.refresh(msg)
    return msg


def list_messages(
    db: Session,
    *,
    user_id: str,
    unread_only: bool = False,
    limit: int = 50,
) -> tuple[int, list[InboxMessage]]:
    query = db.query(InboxMessage).filter(InboxMessage.user_id == user_id)
    if unread_only:
        query = query.filter(InboxMessage.is_read == False)  # noqa: E712
    total = query.count()
    items = query.order_by(InboxMessage.created_at.desc()).limit(limit).all()
    return total, items


def unread_count(db: Session, *, user_id: str) -> int:
    return (
        db.query(InboxMessage)
        .filter(InboxMessage.user_id == user_id, InboxMessage.is_read == False)  # noqa: E712
        .count()
    )


def mark_read(db: Session, *, user_id: str, message_id: str) -> Optional[InboxMessage]:
    msg = (
        db.query(InboxMessage)
        .filter(InboxMessage.message_id == message_id, InboxMessage.user_id == user_id)
        .first()
    )
    if not msg:
        return None
    if not msg.is_read:
        msg.is_read = True
        msg.read_at = now_utc()
        db.commit()
        db.refresh(msg)
    return msg


def notify_async_session(
    db: Session,
    session: SessionModel,
    *,
    job_key: str = "",
    aborted: bool = False,
) -> Optional[InboxMessage]:
    if aborted:
        return None
    if (session.caller_type or "").upper() == "SCHEDULE":
        return None
    user_id = (session.caller_id or "").strip()
    if not user_id:
        return None
    status = session.status if isinstance(session.status, SessionStatus) else SessionStatus(session.status)
    meta = _ASYNC_STATUS_NOTIFY.get(status)
    if not meta:
        return None
    agent = db.query(Agent).filter(Agent.agent_id == session.agent_id).first()
    agent_name = agent.name if agent else "Agent"
    preview = ""
    for msg in reversed(session.messages or []):
        if msg.get("role") == "user" and msg.get("content"):
            preview = str(msg.get("content"))[:120]
            break
    body = f"{agent_name} · {preview}" if preview else agent_name
    job_key = (job_key or "").strip()
    related_id = f"{session.session_id}:{job_key}" if job_key else session.session_id
    link_path = f"/agents/{session.agent_id}/chat?session_id={session.session_id}"
    return notify_user(
        db,
        user_id=user_id,
        title=meta[0],
        body=body,
        level=meta[1],
        link_path=link_path,
        related_type="async_session",
        related_id=related_id,
    )


def mark_read_by_session(db: Session, *, user_id: str, session_id: str) -> int:
    uid = (user_id or "").strip()
    sid = (session_id or "").strip()
    if not uid or not sid:
        return 0
    prefix = f"{sid}:"
    msgs = (
        db.query(InboxMessage)
        .filter(
            InboxMessage.user_id == uid,
            InboxMessage.related_type == "async_session",
            InboxMessage.is_read == False,  # noqa: E712
            InboxMessage.related_id.startswith(prefix) | (InboxMessage.related_id == sid),
        )
        .all()
    )
    if not msgs:
        return 0
    stamped = now_utc()
    for msg in msgs:
        msg.is_read = True
        msg.read_at = stamped
    db.commit()
    return len(msgs)
