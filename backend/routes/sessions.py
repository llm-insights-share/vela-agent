from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, UploadFile, File, Form, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from typing import Any, Dict, List, Optional
import asyncio
import os
import traceback
from database import get_db, SessionLocal
from models import Session as SessionModel, SessionStatus, gen_uuid, gen_trace_id, now_utc
from schemas import (
    SessionCreate,
    SessionChatRequest,
    SessionChatAsyncResponse,
    SessionAbortResponse,
    SessionResponse,
    SessionMessagesMutateRequest,
    LlmCallLogListResponse,
    LlmCallLogItem,
    PaginatedResponse,
    SessionAttachmentResponse,
    SessionAttachmentListResponse,
    SessionConnectorsUpdate,
)
from services.agent_service import agent_service, _ensure_files_for_session
from services.session_abort import request_abort, clear_abort
from services.attachment_service import attachment_service, MIME_TYPES as ATTACHMENT_MIME_TYPES
from services.session_title import ensure_session_title
from services.session_events import sse_event_stream, publish_status, session_event_bus
from deps import CurrentUser

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])


def _run_memory_process(session_id: str):
    from services.memory.processor import process_session_background
    try:
        asyncio.run(process_session_background(session_id))
    except Exception as e:
        print(f"[sessions.close] 记忆处理失败: {e}")


async def _run_session_chat_background(session_id: str, request_data: Dict[str, Any]):
    """Run agent chat on the uvicorn event loop (not asyncio.run).

    ScreenPilot Playwright is bound to the loop that started it. Using
    asyncio.run() in BackgroundTasks closes that loop when HITL pauses,
    so later approve gets WriteUnixTransport closed / 500.
    """
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
            attachment_ids=request_data.get("attachment_ids") or [],
            persist_user_message=False,
        )
        db.refresh(session)
        pending = dict(session.pending_context or {})
        job_key = str((pending.get("background_job") or {}).get("started_at") or "")
        agent_service.finalize_background_chat(db, session, result)
        db.refresh(session)
        from services.inbox import notify_async_session
        notify_async_session(
            db,
            session,
            job_key=job_key,
            aborted=bool(result.get("aborted")),
        )
    except Exception as e:
        traceback.print_exc()
        try:
            session = db.query(SessionModel).filter(
                SessionModel.session_id == session_id
            ).first()
            if session:
                err_text = (str(e) or "").strip() or type(e).__name__
                if isinstance(e, TimeoutError) or type(e).__name__ == "TimeoutError":
                    err_text = (
                        f"执行超时（{type(e).__name__}）。"
                        "多 Agent 编排可能超过会话 timeout，请提高 Agent 超时或缩短任务。"
                    )
                messages = list(session.messages or [])
                messages.append({
                    "role": "assistant",
                    "content": f"❌ 任务执行失败：{err_text}",
                })
                session.messages = messages
                flag_modified(session, "messages")
                session.status = SessionStatus.ERROR
                pending = dict(session.pending_context or {})
                job = dict(pending.get("background_job") or {})
                job_key = str(job.get("started_at") or "")
                job["error"] = err_text
                pending["background_job"] = job
                session.pending_context = pending
                session.last_active_at = now_utc()
                db.commit()
                from services.inbox import notify_async_session
                notify_async_session(db, session, job_key=job_key)
                try:
                    session_event_bus.publish(
                        session_id,
                        {"type": "error", "message": err_text},
                    )
                    publish_status(session_id, "ERROR")
                except Exception:
                    pass
        except Exception:
            traceback.print_exc()
    finally:
        db.close()


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
        ensure_session_title(s)
    db.commit()
    return PaginatedResponse(
        total=total, page=page, page_size=page_size,
        items=[SessionResponse.model_validate(s) for s in sessions]
    )


@router.post("", response_model=SessionResponse, status_code=201)
def create_session(
    data: SessionCreate,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    from models import Agent
    from services.selfopt.ab_router import assign_for_new_session

    caller_id = (data.caller_id or "").strip() or user.user_id
    version_id = data.version_id
    ab_experiment_id = None
    ab_arm = None

    # Only auto-assign when client did not pin a version
    if not version_id:
        agent = db.query(Agent).filter(Agent.agent_id == data.agent_id).first()
        if agent:
            assignment = assign_for_new_session(db, agent=agent)
            version_id = assignment.version_id
            ab_experiment_id = assignment.ab_experiment_id
            ab_arm = assignment.ab_arm

    session = SessionModel(
        session_id=gen_uuid(),
        agent_id=data.agent_id,
        version_id=version_id,
        caller_type=data.caller_type,
        caller_id=caller_id,
        token_budget=data.token_budget,
        ttl_seconds=data.ttl_seconds,
        title="",
        messages=[],
        pending_context={},
        trace_id=gen_trace_id(),
        ab_experiment_id=ab_experiment_id,
        ab_arm=ab_arm,
    )
    db.add(session)
    db.commit()
    db.refresh(session)


    # Connector enablement is resolved at chat time from Agent connector_bindings
    # ∩ user CONNECTED connectors (catalog_key). Session toggles are no longer used.

    return SessionResponse.model_validate(session)


def _build_user_message_payload(data: SessionChatRequest, session, db: Session) -> Dict[str, Any]:
    msg = {"role": "user", "content": data.message or "请分析附件"}
    if data.skill_pack_id:
        from models import SkillPack
        skill = db.query(SkillPack).filter(
            SkillPack.skill_pack_id == data.skill_pack_id
        ).first()
        if skill:
            msg["activeSkill"] = skill.name
    if data.attachment_ids:
        attachments = attachment_service.get_attachment_metadata_for_message(
            session, data.attachment_ids
        )
        if attachments:
            msg["attachments"] = attachments
    return msg


@router.post("/{session_id}/attachments", response_model=SessionAttachmentResponse, status_code=201)
async def upload_session_attachment(
    session_id: str,
    file: UploadFile = File(...),
    filename: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    session = db.query(SessionModel).filter(
        SessionModel.session_id == session_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session.status == SessionStatus.CLOSED:
        raise HTTPException(status_code=400, detail="会话已关闭")

    file_bytes = await file.read()
    name = filename or file.filename or "unknown"

    try:
        result = attachment_service.save_attachment(session, file_bytes, name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    flag_modified(session, "pending_context")
    db.commit()
    return SessionAttachmentResponse.model_validate(result)


@router.get("/{session_id}/attachments", response_model=SessionAttachmentListResponse)
def list_session_attachments(session_id: str, db: Session = Depends(get_db)):
    session = db.query(SessionModel).filter(
        SessionModel.session_id == session_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    items = attachment_service.list_attachments(session)
    attachments = [SessionAttachmentResponse.model_validate(i) for i in items]
    return SessionAttachmentListResponse(attachments=attachments, total=len(attachments))


@router.delete("/{session_id}/attachments/{attachment_id}")
def delete_session_attachment(
    session_id: str,
    attachment_id: str,
    db: Session = Depends(get_db),
):
    session = db.query(SessionModel).filter(
        SessionModel.session_id == session_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    if not attachment_service.delete_attachment(session, attachment_id):
        raise HTTPException(status_code=404, detail="附件不存在")

    flag_modified(session, "pending_context")
    db.commit()
    return {"message": "附件已删除"}


@router.get("/{session_id}/attachments/{attachment_id}/download")
def download_session_attachment(
    session_id: str,
    attachment_id: str,
    db: Session = Depends(get_db),
):
    session = db.query(SessionModel).filter(
        SessionModel.session_id == session_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    meta = attachment_service.get_attachment(session, attachment_id)
    if not meta:
        raise HTTPException(status_code=404, detail="附件不存在")

    from services.attachment_service import _resolve_stored_path
    file_path = _resolve_stored_path(meta.get("stored_path", ""))
    if not file_path or not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="附件文件不存在")

    filename = meta.get("filename", "attachment")
    ext = os.path.splitext(filename)[1].lower()
    media_type = ATTACHMENT_MIME_TYPES.get(ext, "application/octet-stream")
    return FileResponse(file_path, filename=filename, media_type=media_type)


@router.get("/{session_id}/llm-calls", response_model=LlmCallLogListResponse)
def list_session_llm_calls(session_id: str, db: Session = Depends(get_db)):
    session = db.query(SessionModel).filter(
        SessionModel.session_id == session_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    calls = list(session.llm_calls or [])
    calls.sort(key=lambda c: c.get("seq", 0), reverse=True)
    return LlmCallLogListResponse(
        items=[LlmCallLogItem.model_validate(c) for c in calls]
    )


@router.get("/{session_id}", response_model=SessionResponse)
def get_session(session_id: str, db: Session = Depends(get_db)):
    session = db.query(SessionModel).filter(
        SessionModel.session_id == session_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    _ensure_files_for_session(session, db)
    ensure_session_title(session)
    session.last_active_at = now_utc()
    db.commit()
    return SessionResponse.model_validate(session)


@router.get("/{session_id}/events")
async def session_events(session_id: str, request: Request, db: Session = Depends(get_db)):
    """SSE stream of thinking deltas / status for a running session."""
    session = db.query(SessionModel).filter(
        SessionModel.session_id == session_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    async def _gen():
        async for chunk in sse_event_stream(session_id):
            if await request.is_disconnected():
                break
            yield chunk

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{session_id}/messages/mutate", response_model=SessionResponse)
def mutate_session_messages(
    session_id: str,
    data: SessionMessagesMutateRequest,
    db: Session = Depends(get_db),
):
    """Truncate/rewrite session messages for edit / redo / delete of a user turn."""
    session = db.query(SessionModel).filter(
        SessionModel.session_id == session_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session.status == SessionStatus.CLOSED:
        raise HTTPException(status_code=400, detail="会话已关闭")
    if session.status in (SessionStatus.RUNNING, SessionStatus.HITL_WAIT):
        raise HTTPException(
            status_code=409,
            detail="会话正在执行或等待审批，无法修改消息",
        )

    messages = list(session.messages or [])
    idx = data.message_index
    if idx < 0 or idx >= len(messages):
        raise HTTPException(status_code=400, detail="message_index 越界")
    target = messages[idx] or {}
    if (target.get("role") or "") != "user":
        raise HTTPException(status_code=400, detail="只能对用户消息执行编辑/重做/删除")

    action = data.action
    if action == "delete":
        messages = messages[:idx]
    elif action == "redo":
        messages = messages[: idx + 1]
    elif action == "edit":
        content = (data.content or "").strip()
        if not content:
            raise HTTPException(status_code=400, detail="编辑内容不能为空")
        new_user = {k: v for k, v in target.items() if k != "content"}
        new_user["role"] = "user"
        new_user["content"] = content
        messages = messages[:idx] + [new_user]
    else:
        raise HTTPException(status_code=400, detail="不支持的 action")

    session.messages = messages
    flag_modified(session, "messages")
    # Truncation invalidates in-flight HITL / mid-run preview context
    session.pending_context = {}
    flag_modified(session, "pending_context")
    session.status = SessionStatus.ACTIVE
    session.last_active_at = now_utc()
    db.commit()
    db.refresh(session)
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
            attachment_ids=data.attachment_ids,
        )
        return result
    except Exception as e:
        session.status = SessionStatus.ERROR
        db.commit()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{session_id}/chat/async", response_model=SessionChatAsyncResponse, status_code=202)
async def chat_async(
    session_id: str,
    data: SessionChatRequest,
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
    if data.append_user_message:
        messages.append(_build_user_message_payload(data, session, db))
        session.messages = messages
        flag_modified(session, "messages")
        ensure_session_title(session)
    else:
        # edit/redo path: user message already persisted by messages/mutate
        if not messages or (messages[-1] or {}).get("role") != "user":
            raise HTTPException(
                status_code=400,
                detail="会话末尾没有用户消息，无法在不追加的情况下继续对话",
            )

    pending = dict(session.pending_context or {})
    pending["background_job"] = {
        "started_at": now_utc().isoformat(),
        "message_preview": (data.message or "请分析附件")[:120],
        "agent_id": session.agent_id,
    }
    session.pending_context = pending
    session.status = SessionStatus.RUNNING
    session.last_active_at = now_utc()
    db.commit()

    request_data = {
        "message": data.message,
        "attachment_ids": data.attachment_ids,
        "skill_pack_id": data.skill_pack_id,
        "timeout_seconds": data.timeout_seconds,
        "execution_mode": data.execution_mode,
        "skip_history": data.skip_history,
    }
    # Keep Playwright / ScreenPilot on the same loop as HITL approve.
    asyncio.create_task(
        _run_session_chat_background(session_id, request_data),
        name=f"session-chat-{session_id}",
    )

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

    try:
        if status_out == "ACTIVE":
            session_event_bus.publish(
                session_id,
                {"type": "done", "status": "ACTIVE", "aborted": True},
            )
            publish_status(session_id, "ACTIVE")
        else:
            session_event_bus.publish(
                session_id,
                {"type": "status", "status": "ABORTING", "message": message},
            )
    except Exception:
        pass

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

    attachment_service.cleanup_session(session_id)

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


def _get_owned_session(db: Session, user_id: str, session_id: str) -> SessionModel:
    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    if (session.caller_id or "") != user_id:
        raise HTTPException(status_code=403, detail="无权访问该会话")
    return session


@router.get("/{session_id}/connectors")
def get_session_connectors(
    session_id: str,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    from services.connector_service import list_session_connectors

    session = _get_owned_session(db, user.user_id, session_id)
    return list_session_connectors(db, session, user.user_id)


@router.put("/{session_id}/connectors")
def update_session_connectors(
    session_id: str,
    data: SessionConnectorsUpdate,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    from services.connector_service import list_session_connectors, set_active_connector_ids

    session = _get_owned_session(db, user.user_id, session_id)
    active = set_active_connector_ids(db, session, data.connector_ids, user.user_id)
    payload = list_session_connectors(db, session, user.user_id)
    payload["active_connector_ids"] = active
    return payload


@router.delete("/{session_id}")
def delete_session(session_id: str, db: Session = Depends(get_db)):
    session = db.query(SessionModel).filter(
        SessionModel.session_id == session_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    attachment_service.cleanup_session(session_id)
    db.delete(session)
    db.commit()
    return {"message": "会话已删除"}
