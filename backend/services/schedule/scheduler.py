from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from croniter import croniter

from database import SessionLocal
from models import AgentSchedule, AgentScheduleRun, ScheduleRunStatus, ScheduleTriggerType, gen_uuid
from services.schedule.config import (
    DEFAULT_SCHEDULE_TIMEZONE,
    SCHEDULE_MISS_TOLERANCE_SECONDS,
    SCHEDULE_POLL_INTERVAL_SECONDS,
)
from services.schedule.runner import execute_schedule_run, notify_schedule_run

logger = logging.getLogger(__name__)


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class AgentScheduleScheduler:
    def __init__(self, poll_interval_seconds: int = SCHEDULE_POLL_INTERVAL_SECONDS):
        self.poll_interval = poll_interval_seconds
        self._task: asyncio.Task | None = None
        self._running = False
        self._workers: set[asyncio.Task] = set()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._running = True
            self._task = asyncio.create_task(self._poll_loop())
            logger.info("Agent schedule scheduler started")

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        for worker in list(self._workers):
            worker.cancel()
        self._workers.clear()

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                await self.check_all()
            except Exception as e:
                logger.error("Schedule polling failed: %s", e, exc_info=True)
            await asyncio.sleep(self.poll_interval)

    async def check_all(self) -> None:
        db = SessionLocal()
        try:
            schedules = db.query(AgentSchedule).filter(AgentSchedule.enabled == True).all()  # noqa: E712
            now_utc = datetime.now(timezone.utc)
            for schedule in schedules:
                await self._check_one(db, schedule, now_utc)
        finally:
            db.close()

    async def _check_one(self, db, schedule: AgentSchedule, now_utc: datetime) -> None:
        tz_name = schedule.timezone or DEFAULT_SCHEDULE_TIMEZONE
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo(DEFAULT_SCHEDULE_TIMEZONE)
            tz_name = DEFAULT_SCHEDULE_TIMEZONE
        now_local = now_utc.astimezone(tz)

        try:
            prev_fire_local = croniter(schedule.cron_expression, now_local).get_prev(datetime)
        except Exception as e:
            logger.warning("Invalid cron expression for schedule %s: %s", schedule.schedule_id, e)
            return

        prev_fire_utc = prev_fire_local.astimezone(timezone.utc)
        last_fired = _as_utc(schedule.last_fired_at)
        if last_fired and last_fired >= prev_fire_utc:
            return

        age_seconds = (now_utc - prev_fire_utc).total_seconds()
        if age_seconds > self.poll_interval + SCHEDULE_MISS_TOLERANCE_SECONDS:
            return

        overlapping = (
            db.query(AgentScheduleRun)
            .filter(
                AgentScheduleRun.schedule_id == schedule.schedule_id,
                AgentScheduleRun.status == ScheduleRunStatus.RUNNING,
            )
            .count()
        )
        if schedule.skip_if_running and overlapping > 0:
            run = AgentScheduleRun(
                run_id=gen_uuid(),
                schedule_id=schedule.schedule_id,
                trigger_type=ScheduleTriggerType.CRON,
                status=ScheduleRunStatus.SKIPPED,
                scheduled_for=prev_fire_utc,
                started_at=now_utc,
                finished_at=now_utc,
                error_message="上一轮任务仍在运行，本轮跳过",
            )
            db.add(run)
            schedule.last_fired_at = prev_fire_utc
            schedule.last_status = run.status.value
            schedule.next_run_at = croniter(schedule.cron_expression, now_local).get_next(datetime).astimezone(timezone.utc)
            db.commit()
            db.refresh(run)
            notify_schedule_run(db, schedule, run)
            return

        schedule.last_fired_at = prev_fire_utc
        schedule.next_run_at = croniter(schedule.cron_expression, now_local).get_next(datetime).astimezone(timezone.utc)
        db.commit()
        self._spawn_run(schedule.schedule_id, prev_fire_utc)

    def _spawn_run(self, schedule_id: str, scheduled_for: datetime) -> None:
        task = asyncio.create_task(self._run_in_worker(schedule_id, scheduled_for))
        self._workers.add(task)
        task.add_done_callback(lambda t: self._workers.discard(t))

    async def _run_in_worker(self, schedule_id: str, scheduled_for: datetime) -> None:
        db = SessionLocal()
        try:
            schedule = (
                db.query(AgentSchedule)
                .filter(AgentSchedule.schedule_id == schedule_id)
                .first()
            )
            if not schedule:
                return
            await execute_schedule_run(
                db,
                schedule,
                trigger_type=ScheduleTriggerType.CRON,
                scheduled_for=scheduled_for,
            )
        except Exception as e:
            logger.error("schedule worker failed(%s): %s", schedule_id, e, exc_info=True)
        finally:
            db.close()


schedule_scheduler = AgentScheduleScheduler()
