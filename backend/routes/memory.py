"""记忆管理 REST API：Letta blocks / passages / episodes / status。"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from models import Agent, LettaMemoryAgent, MemoryEpisode
from schemas import (
    LettaStatusResponse,
    MemoryBlockResponse,
    MemoryBlockUpdate,
    MemoryEpisodeResponse,
    MemoryPassageCreate,
    MemoryPassageResponse,
    MemoryScopeResponse,
    PaginatedResponse,
)
from services.memory import letta_store

router = APIRouter(prefix="/api/v1/memory", tags=["memory"])


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


@router.get("/scopes", response_model=List[MemoryScopeResponse])
def list_scopes(db: Session = Depends(get_db)):
    return letta_store.list_scopes(db)


@router.get("/blocks", response_model=List[MemoryBlockResponse])
def list_blocks(
    agent_id: str = Query(...),
    user_id: str = Query(""),
    db: Session = Depends(get_db),
):
    blocks = letta_store.read_blocks(db, agent_id, user_id)
    return [MemoryBlockResponse(**b) for b in blocks]


@router.put("/blocks/{label}", response_model=MemoryBlockResponse)
def update_block(label: str, data: MemoryBlockUpdate, db: Session = Depends(get_db)):
    updated = letta_store.update_block(
        db,
        agent_id=data.agent_id,
        label=label,
        value=data.value,
        user_id=data.user_id or "",
    )
    if not updated:
        raise HTTPException(status_code=502, detail="更新记忆块失败（Letta 不可用或作用域无效）")
    return MemoryBlockResponse(**updated)


@router.get("/passages", response_model=PaginatedResponse)
def list_or_search_passages(
    agent_id: str = Query(...),
    user_id: str = Query(""),
    query: Optional[str] = Query(None),
    tags: Optional[str] = Query(None, description="逗号分隔 tags"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()] or None
    if query and query.strip():
        items = letta_store.search_passages(
            db,
            agent_id=agent_id,
            query=query.strip(),
            user_id=user_id,
            tags=tag_list,
            top_k=page_size,
        )
        return PaginatedResponse(
            total=len(items),
            page=1,
            page_size=page_size,
            items=items,
        )

    # 全量列表：拉取一页再切片（Letta list 用 cursor，此处简化为 limit 截断）
    fetch_limit = min(200, page * page_size)
    all_items = letta_store.list_passages(
        db, agent_id=agent_id, user_id=user_id, limit=fetch_limit
    )
    if tag_list:
        all_items = [
            p for p in all_items
            if set(tag_list).intersection(set(p.get("tags") or []))
        ]
    # Drop blank passages so clients never render empty memory rows
    all_items = [p for p in (all_items or []) if str(p.get("content") or p.get("text") or "").strip()]
    total = len(all_items)
    start = (page - 1) * page_size
    page_items = all_items[start: start + page_size]
    return PaginatedResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=page_items,
    )


@router.post("/passages", response_model=MemoryPassageResponse)
def create_passage(data: MemoryPassageCreate, db: Session = Depends(get_db)):
    created = letta_store.insert_passage(
        db,
        agent_id=data.agent_id,
        text=data.text,
        user_id=data.user_id or "",
        tags=data.tags or None,
    )
    if not created:
        health = letta_store.health()
        detail = "写入归档记忆失败"
        if not health.get("enabled"):
            detail = "写入归档记忆失败（记忆服务未启用）"
        elif not health.get("healthy"):
            detail = f"写入归档记忆失败（Letta 不可用: {health.get('error') or 'unknown'}）"
        else:
            detail = "写入归档记忆失败（创建记忆作用域超时或失败，请重试）"
        raise HTTPException(status_code=502, detail=detail)
    return MemoryPassageResponse(**created)


@router.delete("/passages/{passage_id}")
def delete_passage(
    passage_id: str,
    agent_id: str = Query(...),
    user_id: str = Query(""),
    db: Session = Depends(get_db),
):
    ok = letta_store.delete_passage(db, agent_id, passage_id, user_id=user_id)
    if not ok:
        raise HTTPException(status_code=502, detail="删除归档记忆失败")
    return {"message": "已删除", "passage_id": passage_id}


@router.get("/letta/status", response_model=LettaStatusResponse)
def letta_status(db: Session = Depends(get_db)):
    status = letta_store.health()
    status["mapping_count"] = db.query(LettaMemoryAgent).count()
    return LettaStatusResponse(**status)


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
