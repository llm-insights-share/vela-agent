"""
MA: 多 Agent 编排路由
管理子 Agent 关系、Coordinator 配置
"""
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Agent, AgentComposition, AgentType, AgentStatus
from schemas import (
    SubAgentAdd, SubAgentRemove, CoordinatorConfigUpdate,
    CompositionResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/agents", tags=["compositions"])


def _ensure_composite(db: Session, agent_id: str) -> Agent:
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    if agent.agent_type != AgentType.COMPOSITE:
        raise HTTPException(status_code=400, detail="该 Agent 不是 COMPOSITE 类型")
    return agent


@router.get("/{agent_id}/composition", response_model=CompositionResponse)
def get_composition(agent_id: str, db: Session = Depends(get_db)):
    """获取多 Agent 编排配置"""
    agent = _ensure_composite(db, agent_id)

    compositions = db.query(AgentComposition).filter(
        AgentComposition.parent_agent_id == agent_id
    ).all()

    sub_agents = []
    for comp in compositions:
        child = db.query(Agent).filter(Agent.agent_id == comp.child_agent_id).first()
        sub_agents.append({
            "composition_id": comp.id,
            "child_agent_id": comp.child_agent_id,
            "child_agent_name": child.name if child else "unknown",
            "child_agent_status": child.status.value if child else "DELETED",
            "role_name": comp.role_name,
            "role_description": comp.role_description,
            "task_keywords": comp.task_keywords or [],
        })

    return CompositionResponse(
        parent_agent_id=agent_id,
        sub_agents=sub_agents,
        coordinator_config=agent.composition_config or {},
    )


@router.post("/{agent_id}/composition/sub-agents")
def add_sub_agent(agent_id: str, payload: SubAgentAdd, db: Session = Depends(get_db)):
    """MA-CFG-01: 添加子 Agent"""
    _ensure_composite(db, agent_id)

    # 检查子 Agent 存在且为单体类型
    child = db.query(Agent).filter(Agent.agent_id == payload.child_agent_id).first()
    if not child:
        raise HTTPException(status_code=404, detail="子 Agent 不存在")
    if child.agent_type == AgentType.COMPOSITE:
        raise HTTPException(status_code=400, detail="子 Agent 不能是 COMPOSITE 类型（不支持嵌套编排）")
    if child.status != AgentStatus.PUBLISHED:
        raise HTTPException(status_code=400, detail="子 Agent 必须为 PUBLISHED 状态")

    # 检查是否已存在
    existing = db.query(AgentComposition).filter(
        AgentComposition.parent_agent_id == agent_id,
        AgentComposition.child_agent_id == payload.child_agent_id,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="该子 Agent 已添加")

    comp = AgentComposition(
        parent_agent_id=agent_id,
        child_agent_id=payload.child_agent_id,
        role_name=payload.role_name,
        role_description=payload.role_description,
        task_keywords=payload.task_keywords,
    )
    db.add(comp)
    db.commit()

    return {"success": True, "composition_id": comp.id, "message": "子 Agent 添加成功"}


@router.delete("/{agent_id}/composition/sub-agents/{child_agent_id}")
def remove_sub_agent(agent_id: str, child_agent_id: str, db: Session = Depends(get_db)):
    """移除子 Agent"""
    _ensure_composite(db, agent_id)

    comp = db.query(AgentComposition).filter(
        AgentComposition.parent_agent_id == agent_id,
        AgentComposition.child_agent_id == child_agent_id,
    ).first()
    if not comp:
        raise HTTPException(status_code=404, detail="子 Agent 关系不存在")

    db.delete(comp)
    db.commit()

    return {"success": True, "message": "子 Agent 已移除"}


@router.put("/{agent_id}/composition/coordinator")
def update_coordinator_config(
    agent_id: str, payload: CoordinatorConfigUpdate, db: Session = Depends(get_db)
):
    """MA-CFG-04~12: 更新 Coordinator 配置"""
    agent = _ensure_composite(db, agent_id)

    config = agent.composition_config or {}
    config.update(payload.model_dump())
    agent.composition_config = config
    db.commit()

    return {"success": True, "message": "Coordinator 配置已更新"}


@router.get("/{agent_id}/composition/candidates")
def list_candidate_sub_agents(agent_id: str, db: Session = Depends(get_db)):
    """获取可作为子 Agent 的候选列表（已发布的单体 Agent）"""
    _ensure_composite(db, agent_id)

    # 已添加的子 Agent ID
    existing_ids = [
        r.child_agent_id for r in
        db.query(AgentComposition).filter(
            AgentComposition.parent_agent_id == agent_id
        ).all()
    ]

    candidates = db.query(Agent).filter(
        Agent.agent_type == AgentType.SINGLE,
        Agent.status == AgentStatus.PUBLISHED,
        Agent.agent_id != agent_id,
    ).all()

    return {
        "candidates": [
            {
                "agent_id": a.agent_id,
                "name": a.name,
                "description": a.description or "",
                "already_added": a.agent_id in existing_ids,
            }
            for a in candidates
        ]
    }
