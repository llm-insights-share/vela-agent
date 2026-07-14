from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from typing import Any, Dict, Optional
from database import get_db, SessionLocal
from models import Session as SessionModel, SessionStatus, gen_uuid, now_utc
from schemas import (
    SessionCreate,
    SessionChatRequest,
    SessionChatAsyncResponse,
    SessionAbortResponse,
    SessionResponse,
    PaginatedResponse,
)
from services.agent_service import agent_service, _ensure_files_for_session
from services.session_abort import request_abort, clear_abort

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])


def _run_memory_process(session_id: str):
    import asyncio
    from services.memory.processor import process_session_background
    try:
        asyncio.run(process_session_background(session_id))
    except Exception as e:
        print(f"[sessions.close] 记忆处理失败: {e}")


def _run_session_chat_background(session_id: str, request_data: Dict[str, Any]):
    import asyncio
    import traceback

    async def _execute():
        db = SessionLocal()
        try:
            session = db.query(SessionModel).filter(
                SessionModel.session_id == session_id
            ).first()
            if not session:
                return

            result = await agent_service.chat_with_agent(
                db=db,
                agent_id=session.agent_id,
                session_id=session_id,
                message=request_data["message"],
                skill_pack_id=request_data.get("skill_pack_id"),
                timeout_seconds=request_data.get("timeout_seconds"),
                execution_mode=request_data.get("execution_mode", "auto"),
                skip_history=request_data.get("skip_history", False),
                persist_user_message=False,
            )
            db.refresh(session)
            agent_service.finalize_background_chat(db, session, result)
        except Exception as e:
            traceback.print_exc()
            try:
                session = db.query(SessionModel).filter(
                    SessionModel.session_id == session_id
                ).first()
                if session:
                    messages = list(session.messages or [])
                    messages.append({
                        "role": "assistant",
                        "content": f"❌ 任务执行失败：{e}",
                    })
                    session.messages = messages
                    flag_modified(session, "messages")
                    session.status = SessionStatus.ERROR
                    pending = dict(session.pending_context or {})
                    job = pending.get("background_job", {})
                    job["error"] = str(e)
                    pending["background_job"] = job
                    session.pending_context = pending
                    session.last_active_at = now_utc()
                    db.commit()
            except Exception:
                traceback.print_exc()
        finally:
            db.close()

    try:
        asyncio.run(_execute())
    except Exception as e:
        print(f"[sessions.chat_async] 后台任务失败: {e}")


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


@router.post("/{session_id}/chat/async", response_model=SessionChatAsyncResponse, status_code=202)
def chat_async(
    session_id: str,
    data: SessionChatRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    session = db.query(SessionModel).filter(
        SessionModel.session_id == session_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    if session.status == SessionStatus.CLOSED:
        raise HTTPException(status_code=400, detail="会话已关闭")

    if session.status == SessionStatus.RUNNING:
        raise HTTPException(status_code=409, detail="会话正在运行中，请等待当前任务完成")

    messages = list(session.messages or [])
    messages.append({"role": "user", "content": data.message})
    session.messages = messages
    flag_modified(session, "messages")

    pending = dict(session.pending_context or {})
    pending["background_job"] = {
        "started_at": now_utc().isoformat(),
        "message_preview": data.message[:120],
        "agent_id": session.agent_id,
    }
    session.pending_context = pending
    session.status = SessionStatus.RUNNING
    session.last_active_at = now_utc()
    db.commit()

    request_data = {
        "message": data.message,
        "skill_pack_id": data.skill_pack_id,
        "timeout_seconds": data.timeout_seconds,
        "execution_mode": data.execution_mode,
        "skip_history": data.skip_history,
    }
    background_tasks.add_task(_run_session_chat_background, session_id, request_data)

    return SessionChatAsyncResponse(
        accepted=True,
        session_id=session_id,
        status="RUNNING",
    )


async def _close_linked_screenpilot_sessions(db: Session, vela_session_id: str) -> int:
    """Best-effort close Playwright live sessions tied to this Vela chat session."""
    try:
        from models import ScreenSession
        from services.screenpilot.session_manager import close_live_session

        rows = (
            db.query(ScreenSession)
            .filter(ScreenSession.vela_session_id == vela_session_id)
            .all()
        )
        closed = 0
        for row in rows:
            try:
                await close_live_session(row.screen_session_id)
                closed += 1
                if getattr(row, "status", None):
                    row.status = "CLOSED"
            except Exception as e:
                print(f"[sessions.abort] close live {row.screen_session_id}: {e}")
        if closed:
            db.commit()
        return closed
    except Exception as e:
        print(f"[sessions.abort] screenpilot cleanup skipped: {e}")
        return 0


@router.post("/{session_id}/abort", response_model=SessionAbortResponse)
async def abort_session(session_id: str, db: Session = Depends(get_db)):
    """Cooperatively abort a RUNNING (or HITL_WAIT) session for any Agent."""
    session = db.query(SessionModel).filter(
        SessionModel.session_id == session_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    if session.status not in (SessionStatus.RUNNING, SessionStatus.HITL_WAIT):
        raise HTTPException(
            status_code=409,
            detail=f"仅 RUNNING / HITL_WAIT 可中止，当前状态: {session.status.value if hasattr(session.status, 'value') else session.status}",
        )

    request_abort(session_id)

    pending = dict(session.pending_context or {})
    job = dict(pending.get("background_job") or {})
    job["aborted"] = True
    job["aborted_at"] = now_utc().isoformat()
    pending["background_job"] = job
    session.pending_context = pending
    flag_modified(session, "pending_context")

    # Reject pending HITL approvals
    try:
        from models import HITLApproval

        approvals = (
            db.query(HITLApproval)
            .filter(
                HITLApproval.session_id == session_id,
                HITLApproval.status == "PENDING",
            )
            .all()
        )
        for ap in approvals:
            ap.status = "REJECTED"
            ap.reviewer = "system"
            ap.review_comment = "用户中止任务"
            ap.reviewed_at = now_utc()
    except Exception as e:
        print(f"[sessions.abort] HITL reject: {e}")

    await _close_linked_screenpilot_sessions(db, session_id)

    status_out = session.status.value if hasattr(session.status, "value") else str(session.status)
    message = "已请求中止，等待当前循环退出"

    if session.status == SessionStatus.HITL_WAIT:
        messages = list(session.messages or [])
        messages.append({"role": "assistant", "content": "任务已由用户中止。"})
        session.messages = messages
        flag_modified(session, "messages")
        session.status = SessionStatus.ACTIVE
        pending.pop("background_job", None)
        # Clear common HITL pending keys so UI unlocks
        for key in (
            "pending_tool_call",
            "pending_delivery",
            "pending_workflow",
            "hitl_pending",
        ):
            pending.pop(key, None)
        session.pending_context = pending
        flag_modified(session, "pending_context")
        status_out = "ACTIVE"
        message = "任务已中止"
        clear_abort(session_id)

    session.last_active_at = now_utc()
    db.commit()

    return SessionAbortResponse(
        accepted=True,
        session_id=session_id,
        status=status_out,
        message=message,
    )


@router.post("/{session_id}/close")
def close_session(
    session_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    session = db.query(SessionModel).filter(
        SessionModel.session_id == session_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    session.status = SessionStatus.CLOSED
    db.commit()

    # 记忆闭环：归档 + 后台自我处理
    try:
        from models import Agent
        agent = db.query(Agent).filter(Agent.agent_id == session.agent_id).first()
        if agent and getattr(agent, "memory_enabled", False):
            from services.memory.recorder import MemoryRecorder
            MemoryRecorder(db).archive_session(
                agent_id=session.agent_id,
                session_id=session_id,
                user_id=session.caller_id or "",
                messages=session.messages or [],
            )
            background_tasks.add_task(_run_memory_process, session_id)
    except Exception as e:
        print(f"[sessions.close] 记忆处理调度失败: {e}")

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
