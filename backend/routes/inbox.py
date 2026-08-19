from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from deps import CurrentUser
from schemas import InboxMessageResponse, InboxUnreadCountResponse, PaginatedResponse
from services import inbox as inbox_service

router = APIRouter(prefix="/api/v1/inbox", tags=["inbox"])


def _aware_utc(value):
    if not isinstance(value, datetime):
        return value
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _to_response(msg) -> InboxMessageResponse:
    data = InboxMessageResponse.model_validate(msg).model_dump()
    data["created_at"] = _aware_utc(data.get("created_at"))
    data["read_at"] = _aware_utc(data.get("read_at"))
    return InboxMessageResponse(**data)


@router.get("/messages", response_model=PaginatedResponse)
def list_inbox_messages(
    user: CurrentUser,
    unread_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    total, items = inbox_service.list_messages(
        db, user_id=user.user_id, unread_only=unread_only, limit=limit
    )
    return PaginatedResponse(
        total=total,
        page=1,
        page_size=limit,
        items=[_to_response(x) for x in items],
    )


@router.get("/unread-count", response_model=InboxUnreadCountResponse)
def get_unread_count(user: CurrentUser, db: Session = Depends(get_db)):
    return InboxUnreadCountResponse(unread_count=inbox_service.unread_count(db, user_id=user.user_id))


@router.post("/messages/{message_id}/read", response_model=InboxMessageResponse)
def read_inbox_message(message_id: str, user: CurrentUser, db: Session = Depends(get_db)):
    msg = inbox_service.mark_read(db, user_id=user.user_id, message_id=message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="消息不存在")
    return _to_response(msg)


@router.post("/sessions/{session_id}/read")
def read_inbox_for_session(session_id: str, user: CurrentUser, db: Session = Depends(get_db)):
    marked = inbox_service.mark_read_by_session(
        db, user_id=user.user_id, session_id=session_id
    )
    return {"marked": marked}
