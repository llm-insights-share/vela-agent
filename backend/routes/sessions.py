from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from database import get_db
from models import Session as SessionModel, SessionStatus, gen_uuid, now_utc
from schemas import SessionCreate, SessionChatRequest, SessionResponse, PaginatedResponse
from services.agent_service import agent_service, _ensure_files_for_session

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])


@router.get("", response_model=PaginatedResponse)
def list_sessions(
    agent_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(SessionModel)
    if agent_id:
        query = query.filter(SessionModel.agent_id == agent_id)
    if status:
        query = query.filter(SessionModel.status == status)
    total = query.count()
    sessions = query.order_by(SessionModel.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()
    for s in sessions:
        _ensure_files_for_session(s, db)
    return PaginatedResponse(
        total=total, page=page, page_size=page_size,
        items=[SessionResponse.model_validate(s) for s in sessions]
    )


@router.post("", response_model=SessionResponse, status_code=201)
def create_session(data: SessionCreate, db: Session = Depends(get_db)):
    session = SessionModel(
        session_id=gen_uuid(),
        agent_id=data.agent_id,
        version_id=data.version_id,
        caller_type=data.caller_type,
        caller_id=data.caller_id,
        token_budget=data.token_budget,
        ttl_seconds=data.ttl_seconds,
        messages=[],
        trace_id=gen_uuid(),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return SessionResponse.model_validate(session)


@router.get("/{session_id}", response_model=SessionResponse)
def get_session(session_id: str, db: Session = Depends(get_db)):
    session = db.query(SessionModel).filter(
        SessionModel.session_id == session_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    _ensure_files_for_session(session, db)
    session.last_active_at = now_utc()
    db.commit()
    return SessionResponse.model_validate(session)


@router.post("/{session_id}/chat")
async def chat(session_id: str, data: SessionChatRequest, db: Session = Depends(get_db)):
    session = db.query(SessionModel).filter(
        SessionModel.session_id == session_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    if session.status == SessionStatus.CLOSED:
        raise HTTPException(status_code=400, detail="会话已关闭")

    session.status = SessionStatus.ACTIVE
    session.last_active_at = now_utc()
    db.commit()

    try:
        result = await agent_service.chat_with_agent(
            db=db,
            agent_id=session.agent_id,
            session_id=session_id,
            message=data.message,
            skill_pack_id=data.skill_pack_id,
            timeout_seconds=data.timeout_seconds,
            execution_mode=data.execution_mode,
            skip_history=data.skip_history,
        )
        return result
    except Exception as e:
        session.status = SessionStatus.ERROR
        db.commit()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{session_id}/close")
def close_session(session_id: str, db: Session = Depends(get_db)):
    session = db.query(SessionModel).filter(
        SessionModel.session_id == session_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    session.status = SessionStatus.CLOSED
    db.commit()
    return {"message": "会话已关闭"}


@router.delete("/{session_id}")
def delete_session(session_id: str, db: Session = Depends(get_db)):
    session = db.query(SessionModel).filter(
        SessionModel.session_id == session_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    db.delete(session)
    db.commit()
    return {"message": "会话已删除"}