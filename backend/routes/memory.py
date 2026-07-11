"""记忆管理 REST API：查询 / 修改 / 情景查阅 / 手动触发处理。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from models import Agent, MemoryEpisode, MemoryRecord
from schemas import (
    MemoryEpisodeResponse,
    MemoryRecordResponse,
    MemoryRecordUpdate,
    PaginatedResponse,
)
from services.memory.gateway import MemoryGateway

router = APIRouter(prefix="/api/v1/memory", tags=["memory"])


def _record_to_response(r: MemoryRecord) -> dict:
    return {
        "record_id": r.record_id,
        "agent_id": r.agent_id,
        "user_id": r.user_id or "",
        "memory_type": r.memory_type,
        "content": r.content,
        "metadata": r.meta or {},
        "source_episode_ids": r.source_episode_ids or [],
        "status": r.status,
        "valid_from": r.valid_from,
        "valid_to": r.valid_to,
        "created_at": r.created_at,
        "updated_at": r.updated_at,
        "created_by": r.created_by or "system",
    }


def _episode_to_response(e: MemoryEpisode) -> dict:
    return {
        "episode_id": e.episode_id,
        "agent_id": e.agent_id,
        "session_id": e.session_id or "",
        "user_id": e.user_id or "",
        "event_type": e.event_type,
        "payload": e.payload or {},
        "created_at": e.created_at,
    }


@router.get("/records", response_model=PaginatedResponse)
def list_records(
    agent_id: Optional[str] = Query(None),
    memory_type: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    status: Optional[str] = Query("active"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    q = db.query(MemoryRecord)
    if agent_id:
        q = q.filter(MemoryRecord.agent_id == agent_id)
    if memory_type:
        q = q.filter(MemoryRecord.memory_type == memory_type)
    if status and status != "all":
        q = q.filter(MemoryRecord.status == status)
    if keyword:
        q = q.filter(MemoryRecord.content.like(f"%{keyword}%"))
    total = q.count()
    rows = (
        q.order_by(MemoryRecord.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PaginatedResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[_record_to_response(r) for r in rows],
    )


@router.get("/records/{record_id}", response_model=MemoryRecordResponse)
def get_record(record_id: str, db: Session = Depends(get_db)):
    r = db.query(MemoryRecord).filter(MemoryRecord.record_id == record_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="记忆记录不存在")
    return _record_to_response(r)


@router.put("/records/{record_id}", response_model=MemoryRecordResponse)
def update_record(record_id: str, data: MemoryRecordUpdate, db: Session = Depends(get_db)):
    gateway = MemoryGateway(db)
    try:
        new_rec = gateway.propose_edit(
            record_id=record_id,
            content=data.content,
            metadata=data.metadata,
            actor="human",
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _record_to_response(new_rec)


@router.delete("/records/{record_id}")
def delete_record(record_id: str, db: Session = Depends(get_db)):
    gateway = MemoryGateway(db)
    rec = gateway.supersede(record_id)
    if not rec:
        raise HTTPException(status_code=404, detail="记忆记录不存在")
    return {"message": "记忆已失效", "record_id": record_id}


@router.get("/episodes", response_model=PaginatedResponse)
def list_episodes(
    agent_id: Optional[str] = Query(None),
    session_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    q = db.query(MemoryEpisode)
    if agent_id:
        q = q.filter(MemoryEpisode.agent_id == agent_id)
    if session_id:
        q = q.filter(MemoryEpisode.session_id == session_id)
    if event_type:
        q = q.filter(MemoryEpisode.event_type == event_type)
    total = q.count()
    rows = (
        q.order_by(MemoryEpisode.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PaginatedResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[_episode_to_response(e) for e in rows],
    )


def _run_process(session_id: str):
    import asyncio
    from services.memory.processor import process_session_background
    try:
        asyncio.run(process_session_background(session_id))
    except Exception as e:
        print(f"[memory.process] failed: {e}")


@router.post("/process/{session_id}")
def process_session(
    session_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    from models import Session as SessionModel

    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    agent = db.query(Agent).filter(Agent.agent_id == session.agent_id).first()
    if not agent or not getattr(agent, "memory_enabled", False):
        raise HTTPException(status_code=400, detail="该 Agent 未挂载记忆模块")
    background_tasks.add_task(_run_process, session_id)
    return {"message": "已触发记忆处理", "session_id": session_id}
