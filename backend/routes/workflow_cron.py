"""
WF: Cron 手动触发 / 调试路由
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Agent, AgentType
from services.workflow_cron_scheduler import cron_scheduler

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/agents", tags=["workflow-cron"])


@router.post("/{agent_id}/workflow/cron/trigger")
async def trigger_cron(agent_id: str, db: Session = Depends(get_db)):
    """手动触发工作流 Cron 执行（调试用）"""
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    if agent.agent_type != AgentType.WORKFLOW:
        raise HTTPException(status_code=400, detail="该 Agent 不是 WORKFLOW 类型")

    from services.workflow_compiler import WorkflowCompiler
    compiled = WorkflowCompiler.compile(agent.workflow_definition or {})
    if not compiled.cron_node_ids:
        raise HTTPException(status_code=400, detail="工作流未配置 Cron 节点")

    cron_id = compiled.cron_node_ids[0]
    result = await cron_scheduler.trigger_cron_workflow(db, agent_id, cron_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "触发失败"))
    return result
