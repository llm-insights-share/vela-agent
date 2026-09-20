"""Agent context-block CRUD: system defaults + per-agent×mode overrides."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from models import Agent, AgentStatus
from schemas import (
    ContextBlockItem,
    ContextBlockListResponse,
    ContextBlockPreviewRequest,
    ContextBlockPreviewResponse,
    ContextBlockReplaceRequest,
)
from services import context_block_service as cbs
from services.context_block_defaults import EXECUTION_MODES, validate_execution_mode

router = APIRouter(prefix="/api/v1", tags=["agent-context-blocks"])


def _get_agent(db: Session, agent_id: str) -> Agent:
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if not agent or agent.status == AgentStatus.DELETED:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    return agent


def _parse_mode(mode: str) -> str:
    try:
        return validate_execution_mode(mode)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"execution_mode 必须是 {', '.join(EXECUTION_MODES)}",
        )


@router.get("/context-blocks/defaults", response_model=ContextBlockListResponse)
def get_system_defaults(
    execution_mode: str = Query("auto"),
):
    mode = _parse_mode(execution_mode)
    items = cbs.list_system_defaults(mode)
    return ContextBlockListResponse(
        execution_mode=mode,
        items=[ContextBlockItem(**x) for x in items],
    )


@router.get("/agents/{agent_id}/context-blocks", response_model=ContextBlockListResponse)
def get_agent_context_blocks(
    agent_id: str,
    execution_mode: str = Query("auto"),
    db: Session = Depends(get_db),
):
    agent = _get_agent(db, agent_id)
    mode = _parse_mode(execution_mode)
    items = cbs.ensure_materialized(db, agent, mode)
    return ContextBlockListResponse(
        execution_mode=mode,
        items=[ContextBlockItem(**x) for x in items],
    )


@router.put("/agents/{agent_id}/context-blocks", response_model=ContextBlockListResponse)
def put_agent_context_blocks(
    agent_id: str,
    body: ContextBlockReplaceRequest,
    execution_mode: str = Query("auto"),
    db: Session = Depends(get_db),
):
    agent = _get_agent(db, agent_id)
    mode = _parse_mode(execution_mode)
    payload = [item.model_dump() for item in (body.items or [])]
    items = cbs.replace_blocks(db, agent, mode, payload)
    return ContextBlockListResponse(
        execution_mode=mode,
        items=[ContextBlockItem(**x) for x in items],
    )


@router.post(
    "/agents/{agent_id}/context-blocks/restore-defaults",
    response_model=ContextBlockListResponse,
)
def restore_agent_context_defaults(
    agent_id: str,
    execution_mode: str = Query("auto"),
    db: Session = Depends(get_db),
):
    agent = _get_agent(db, agent_id)
    mode = _parse_mode(execution_mode)
    items = cbs.restore_defaults(db, agent, mode)
    return ContextBlockListResponse(
        execution_mode=mode,
        items=[ContextBlockItem(**x) for x in items],
    )


@router.post(
    "/agents/{agent_id}/context-blocks/preview",
    response_model=ContextBlockPreviewResponse,
)
def preview_agent_context_blocks(
    agent_id: str,
    body: ContextBlockPreviewRequest,
    db: Session = Depends(get_db),
):
    agent = _get_agent(db, agent_id)
    mode = _parse_mode(body.execution_mode)
    blocks = cbs.get_effective_blocks_for_runtime(
        db, agent.agent_id, mode, system_prompt=agent.system_prompt or ""
    )
    from datetime import datetime

    today = datetime.now().strftime("%Y-%m-%d")
    weekday_map = ["一", "二", "三", "四", "五", "六", "日"]
    weekday = weekday_map[datetime.now().weekday()]
    preview = cbs.preview_assembled(
        blocks,
        connector_context=body.connector_context or "",
        knowledge_context=body.knowledge_context or "",
        project_context=body.project_context or "",
        today=today,
        weekday=weekday,
    )
    return ContextBlockPreviewResponse(
        execution_mode=mode,
        system=preview["system"],
        user_suffix=preview["user_suffix"],
        mode_inject=preview["mode_inject"],
        blocks=[ContextBlockItem(**x) for x in preview["blocks"]],
    )
