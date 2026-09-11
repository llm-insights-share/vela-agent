"""Periodic SelfOpt job runner (only when selfopt.schedule_enabled)."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from database import SessionLocal
from models import Agent, AgentStatus, SelfOptJob
from services.selfopt.config import is_schedule_enabled, load_selfopt_config
from services.selfopt.pipeline import run_selfopt_job

logger = logging.getLogger(__name__)

# Avoid re-running same agent within 20h
_MIN_INTERVAL_SECONDS = 20 * 3600


class SelfOptScheduler:
    def __init__(self, poll_interval_seconds: int = 3600):
        self.poll_interval = poll_interval_seconds
        self._task: Optional[asyncio.Task] = None
        self._running = False

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._running = True
            self._task = asyncio.create_task(self._poll_loop())
            logger.info("SelfOpt scheduler started")

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                if is_schedule_enabled():
                    await self._run_due_agents()
            except Exception as e:
                logger.error("SelfOpt schedule poll failed: %s", e, exc_info=True)
            await asyncio.sleep(self.poll_interval)

    async def _run_due_agents(self) -> None:
        db = SessionLocal()
        try:
            agents = (
                db.query(Agent)
                .filter(Agent.status == AgentStatus.PUBLISHED)
                .all()
            )
            cfg = load_selfopt_config()
            now = datetime.now(timezone.utc)
            allow = set(cfg.agent_ids or [])
            for agent in agents:
                if agent.agent_id not in allow:
                    continue
                if agent.selfopt_enabled is False:
                    continue
                last = (
                    db.query(SelfOptJob)
                    .filter(SelfOptJob.agent_id == agent.agent_id)
                    .order_by(SelfOptJob.created_at.desc())
                    .first()
                )
                if last and last.created_at:
                    created = last.created_at
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                    if (now - created).total_seconds() < _MIN_INTERVAL_SECONDS:
                        continue
                try:
                    await run_selfopt_job(db, agent_id=agent.agent_id, window_days=7)
                    logger.info("SelfOpt scheduled job done for agent %s", agent.agent_id)
                except Exception as e:
                    logger.warning(
                        "SelfOpt scheduled job failed for %s: %s", agent.agent_id, e
                    )
        finally:
            db.close()


selfopt_scheduler = SelfOptScheduler()
