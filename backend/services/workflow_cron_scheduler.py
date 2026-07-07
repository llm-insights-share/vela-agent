"""
WF: Cron 触发器调度
WF-IMP-09 / WF-CFG-06/12
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Optional, Set

from croniter import croniter
from sqlalchemy.orm import Session

from database import SessionLocal
from models import Agent, AgentStatus, AgentType, Session as SessionModel, gen_uuid
from services.workflow_compiler import WorkflowCompiler
from services.workflow_engine import WorkflowEngine

logger = logging.getLogger(__name__)

# 记录每个 cron 节点上次触发时间，避免同一分钟内重复触发
_last_fired: Dict[str, datetime] = {}


class WorkflowCronScheduler:
    """后台 Cron 轮询调度器"""

    def __init__(self, poll_interval_seconds: int = 60):
        self.poll_interval = poll_interval_seconds
        self._task: Optional[asyncio.Task] = None
        self._running = False

    def start(self):
        if self._task is None or self._task.done():
            self._running = True
            self._task = asyncio.create_task(self._poll_loop())
            logger.info("Workflow Cron Scheduler 已启动")

    def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    async def _poll_loop(self):
        while self._running:
            try:
                await self._check_all_cron_nodes()
            except Exception as e:
                logger.error(f"Cron 调度异常: {e}", exc_info=True)
            await asyncio.sleep(self.poll_interval)

    async def _check_all_cron_nodes(self):
        db = SessionLocal()
        try:
            agents = db.query(Agent).filter(
                Agent.agent_type == AgentType.WORKFLOW,
                Agent.status == AgentStatus.PUBLISHED,
            ).all()

            now = datetime.now(timezone.utc)
            for agent in agents:
                definition = agent.workflow_definition or {}
                compiled = WorkflowCompiler.compile(definition)
                for cron_id in compiled.cron_node_ids:
                    node = compiled.nodes.get(cron_id, {})
                    data = node.get("data") or {}
                    cron_expr = data.get("cron_expression", "")
                    if not cron_expr:
                        continue

                    fire_key = f"{agent.agent_id}:{cron_id}"
                    try:
                        itr = croniter(cron_expr, now)
                        prev_fire = itr.get_prev(datetime)
                    except Exception as e:
                        logger.warning(f"无效 cron 表达式 {cron_expr}: {e}")
                        continue

                    last = _last_fired.get(fire_key)
                    if last and last >= prev_fire:
                        continue

                    # 仅在当前分钟匹配时触发
                    if (now - prev_fire).total_seconds() > self.poll_interval + 5:
                        continue

                    _last_fired[fire_key] = now
                    await self.trigger_cron_workflow(db, agent.agent_id, cron_id)
        finally:
            db.close()

    async def trigger_cron_workflow(
        self, db: Session, agent_id: str, cron_node_id: str
    ) -> Dict:
        """手动或 Cron 触发工作流执行"""
        from models import ModelProvider, ModelService

        agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
        if not agent or agent.agent_type != AgentType.WORKFLOW:
            return {"success": False, "error": "Agent 不存在或不是 WORKFLOW 类型"}

        validation = WorkflowCompiler.validate(db, agent.workflow_definition or {})
        if not validation.get("passed"):
            return {
                "success": False,
                "error": "工作流校验未通过",
                "errors": validation.get("errors"),
            }

        model_svc = db.query(ModelService).filter(
            ModelService.model_service_id == agent.model_service_id
        ).first()
        if not model_svc:
            return {"success": False, "error": "模型服务不存在"}

        provider = db.query(ModelProvider).filter(
            ModelProvider.provider_id == model_svc.provider_id
        ).first()
        if not provider:
            return {"success": False, "error": "模型供应商不存在"}

        session = SessionModel(
            session_id=gen_uuid(),
            agent_id=agent_id,
            caller_type="CRON",
            caller_id=cron_node_id,
            token_budget=agent.token_budget,
            trace_id=gen_uuid(),
        )
        db.add(session)
        db.commit()
        db.refresh(session)

        engine = WorkflowEngine(
            db=db, agent=agent, session=session,
            provider=provider, model_svc=model_svc,
        )
        trigger_msg = f"[Cron 触发] 节点 {cron_node_id} @ {datetime.now(timezone.utc).isoformat()}"
        result = await engine.run(trigger_msg, entry_node_id=cron_node_id)

        from services.agent_service import AgentService
        response = await AgentService._finalize_workflow_chat(
            db, session, trigger_msg, result
        )
        return {"success": True, "session_id": session.session_id, **response}


cron_scheduler = WorkflowCronScheduler()
