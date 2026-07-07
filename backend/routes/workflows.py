"""
WF: 工作流编排路由
管理画布定义、校验、子图候选
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Agent, AgentType, AgentStatus
from schemas import WorkflowDefinitionUpdate, WorkflowResponse, WorkflowValidationResult
from services.workflow_compiler import WorkflowCompiler

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/agents", tags=["workflows"])


def _ensure_workflow(db: Session, agent_id: str) -> Agent:
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    if agent.agent_type != AgentType.WORKFLOW:
        raise HTTPException(status_code=400, detail="该 Agent 不是 WORKFLOW 类型")
    return agent


@router.get("/{agent_id}/workflow", response_model=WorkflowResponse)
def get_workflow(agent_id: str, db: Session = Depends(get_db)):
    """获取工作流画布定义"""
    agent = _ensure_workflow(db, agent_id)
    return WorkflowResponse(
        parent_agent_id=agent_id,
        workflow_definition=agent.workflow_definition or {},
    )


@router.put("/{agent_id}/workflow")
def update_workflow(
    agent_id: str, payload: WorkflowDefinitionUpdate, db: Session = Depends(get_db)
):
    """保存工作流画布定义"""
    agent = _ensure_workflow(db, agent_id)
    agent.workflow_definition = payload.model_dump()
    db.commit()
    return {"success": True, "message": "工作流定义已保存"}


@router.post("/{agent_id}/workflow/validate", response_model=WorkflowValidationResult)
def validate_workflow(agent_id: str, db: Session = Depends(get_db)):
    """WF-IMP-02~04: 编译校验工作流图"""
    agent = _ensure_workflow(db, agent_id)
    result = WorkflowCompiler.validate(db, agent.workflow_definition or {})
    return WorkflowValidationResult(
        errors=result.get("errors", []),
        warnings=result.get("warnings", []),
        passed=result.get("passed", False),
    )


@router.get("/{agent_id}/workflow/candidates")
def list_subgraph_candidates(agent_id: str, db: Session = Depends(get_db)):
    """WF-CFG-07: 子图节点可选的单体 Agent 列表"""
    _ensure_workflow(db, agent_id)

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
            }
            for a in candidates
        ]
    }
