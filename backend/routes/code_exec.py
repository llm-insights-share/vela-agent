"""Code execution API routes."""

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from models import CodeExecution, Session as SessionModel
from schemas import (
    CodeExecutionListResponse,
    CodeExecutionResponse,
    CodeExecutionRunRequest,
)
from services.code_exec.runner import run_code
from services.code_exec.workspace import SessionWorkspace

router = APIRouter(prefix="/api/v1/code-exec", tags=["code-exec"])


def _output_dir(session_id: str) -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "data", "outputs", session_id,
    )


def _get_session(db: Session, session_id: str) -> SessionModel:
    session = db.query(SessionModel).filter(
        SessionModel.session_id == session_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


@router.get("/sessions/{session_id}/executions", response_model=CodeExecutionListResponse)
def list_executions(
    session_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    _get_session(db, session_id)
    query = db.query(CodeExecution).filter(CodeExecution.session_id == session_id)
    total = query.count()
    rows = (
        query.order_by(CodeExecution.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return CodeExecutionListResponse(
        items=[CodeExecutionResponse.model_validate(r) for r in rows],
        total=total,
    )


@router.get("/executions/{execution_id}", response_model=CodeExecutionResponse)
def get_execution(execution_id: str, db: Session = Depends(get_db)):
    row = db.query(CodeExecution).filter(
        CodeExecution.execution_id == execution_id
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    return CodeExecutionResponse.model_validate(row)


@router.post("/sessions/{session_id}/run")
async def run_code_manual(
    session_id: str,
    data: CodeExecutionRunRequest,
    db: Session = Depends(get_db),
):
    session = _get_session(db, session_id)
    output_dir = _output_dir(session_id)
    os.makedirs(output_dir, exist_ok=True)

    result = await run_code(
        data.code,
        output_dir,
        language=data.language,
        timeout=data.timeout,
        reset_state=data.reset_state,
    )

    from services.code_exec.recorder import persist_execution
    exec_id = persist_execution(
        db,
        session_id=session_id,
        agent_id=session.agent_id,
        result=result,
    )
    result["execution_id"] = exec_id
    return result


@router.delete("/sessions/{session_id}/state")
def reset_session_state(session_id: str, db: Session = Depends(get_db)):
    _get_session(db, session_id)
    ws = SessionWorkspace(session_id)
    ws.reset_state()
    return {"message": "会话变量状态已重置"}
