from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from models import (
    Agent,
    AgentSchedule,
    AgentScheduleRun,
    AgentStatus,
    ScheduleRunStatus,
    ScheduleTriggerType,
    SessionStatus,
    Session as SessionModel,
    gen_uuid,
    now_utc,
)
from services.agent_service import agent_service
from services.inbox import notify_user
from services.schedule.template import render_schedule_prompt

_STATUS_NOTIFY = {
    ScheduleRunStatus.SUCCESS: ("定时任务已完成", "success"),
    ScheduleRunStatus.ERROR: ("定时任务失败", "warning"),
    ScheduleRunStatus.SKIPPED: ("定时任务已跳过", "info"),
    ScheduleRunStatus.HITL_WAIT: ("定时任务待审批", "info"),
}


def notify_schedule_run(db: Session, schedule: AgentSchedule, run: AgentScheduleRun, agent: Optional[Agent] = None) -> None:
    status = run.status if isinstance(run.status, ScheduleRunStatus) else ScheduleRunStatus(run.status)
    meta = _STATUS_NOTIFY.get(status)
    if not meta:
        return
    user_id = (schedule.created_by or "").strip()
    if not user_id:
        return
    if agent is None:
        agent = db.query(Agent).filter(Agent.agent_id == schedule.agent_id).first()
    agent_name = agent.name if agent else "Agent"
    body = f"{agent_name} · {run.summary or run.error_message or status.value}"
    if run.session_id and schedule.agent_id:
        link_path = f"/agents/{schedule.agent_id}/chat?session_id={run.session_id}"
    else:
        link_path = f"/schedules/{schedule.schedule_id}"
    notify_user(
        db,
        user_id=user_id,
        title=meta[0],
        body=body,
        level=meta[1],
        link_path=link_path,
        related_type="schedule_run",
        related_id=f"{run.run_id}:{status.value}",
    )


def recover_stale_schedule_runs(db: Session, *, reason: str = "服务重启导致任务中断") -> int:
    """Mark in-flight schedule runs as ERROR after worker loss (process restart)."""
    runs = (
        db.query(AgentScheduleRun)
        .filter(AgentScheduleRun.status.in_([ScheduleRunStatus.RUNNING, ScheduleRunStatus.PENDING]))
        .all()
    )
    if not runs:
        return 0
    finished = now_utc()
    for run in runs:
        run.status = ScheduleRunStatus.ERROR
        run.finished_at = finished
        run.error_message = reason
        if run.session_id:
            session = db.query(SessionModel).filter(SessionModel.session_id == run.session_id).first()
            if session and session.status in (
                SessionStatus.ACTIVE,
                SessionStatus.RUNNING,
                SessionStatus.IDLE,
            ):
                session.status = SessionStatus.ERROR
        schedule = db.query(AgentSchedule).filter(AgentSchedule.schedule_id == run.schedule_id).first()
        if schedule:
            schedule.last_status = ScheduleRunStatus.ERROR.value
    db.commit()
    for run in runs:
        schedule = db.query(AgentSchedule).filter(AgentSchedule.schedule_id == run.schedule_id).first()
        if schedule:
            notify_schedule_run(db, schedule, run)
    return len(runs)


def _extract_summary(messages: list[dict]) -> str:
    for msg in reversed(messages or []):
        if msg.get("role") == "assistant" and msg.get("content"):
            return str(msg.get("content"))[:1000]
    return ""


def sync_schedule_run_from_session(db: Session, session_id: str) -> None:
    run = (
        db.query(AgentScheduleRun)
        .filter(AgentScheduleRun.session_id == session_id)
        .order_by(AgentScheduleRun.created_at.desc())
        .first()
    )
    if not run:
        return
    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if not session:
        return
    run.token_used = session.token_used or 0
    run.summary = _extract_summary(session.messages or [])
    if session.status == SessionStatus.HITL_WAIT:
        run.status = ScheduleRunStatus.HITL_WAIT
        run.finished_at = None
    elif session.status == SessionStatus.ERROR:
        run.status = ScheduleRunStatus.ERROR
        if not run.finished_at:
            run.finished_at = now_utc()
    elif session.status in (SessionStatus.ACTIVE, SessionStatus.IDLE, SessionStatus.CLOSED):
        run.status = ScheduleRunStatus.SUCCESS
        if not run.finished_at:
            run.finished_at = now_utc()
    schedule = (
        db.query(AgentSchedule)
        .filter(AgentSchedule.schedule_id == run.schedule_id)
        .first()
    )
    if schedule:
        schedule.last_status = run.status.value
    db.commit()
    if schedule:
        notify_schedule_run(db, schedule, run)


async def execute_schedule_run(
    db: Session,
    schedule: AgentSchedule,
    *,
    trigger_type: ScheduleTriggerType,
    scheduled_for: datetime,
) -> AgentScheduleRun:
    agent = db.query(Agent).filter(Agent.agent_id == schedule.agent_id).first()
    run = AgentScheduleRun(
        run_id=gen_uuid(),
        schedule_id=schedule.schedule_id,
        trigger_type=trigger_type,
        status=ScheduleRunStatus.PENDING,
        scheduled_for=scheduled_for.astimezone(timezone.utc),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    if not agent or agent.status != AgentStatus.PUBLISHED:
        run.status = ScheduleRunStatus.SKIPPED
        run.error_message = "关联 Agent 不存在或未发布"
        run.finished_at = now_utc()
        schedule.last_status = run.status.value
        db.commit()
        notify_schedule_run(db, schedule, run, agent)
        return run

    prompt = render_schedule_prompt(
        schedule.prompt_template,
        schedule_name=schedule.name,
        agent_name=agent.name,
        timezone_name=schedule.timezone,
    )
    timeout_seconds: Optional[int] = schedule.timeout_seconds

    session = SessionModel(
        session_id=gen_uuid(),
        agent_id=agent.agent_id,
        caller_type="SCHEDULE",
        caller_id=schedule.schedule_id,
        token_budget=agent.token_budget,
        trace_id=gen_uuid(),
        messages=[],
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    run.session_id = session.session_id
    run.status = ScheduleRunStatus.RUNNING
    run.started_at = now_utc()
    run.prompt_rendered = prompt
    db.commit()

    try:
        result = await agent_service.chat_with_agent(
            db=db,
            agent_id=agent.agent_id,
            session_id=session.session_id,
            message=prompt,
            timeout_seconds=timeout_seconds,
            execution_mode="auto",
            skip_history=True,
            persist_user_message=True,
            attachment_ids=[],
        )
        agent_service.finalize_background_chat(db, session, result)
        db.refresh(session)
        run.finished_at = now_utc()
        run.token_used = session.token_used or 0
        run.summary = _extract_summary(session.messages or [])
        if session.status.value == "HITL_WAIT":
            run.status = ScheduleRunStatus.HITL_WAIT
        elif session.status.value == "ERROR":
            run.status = ScheduleRunStatus.ERROR
            run.error_message = result.get("content", "")[:2000]
        else:
            run.status = ScheduleRunStatus.SUCCESS
        schedule.last_status = run.status.value
        db.commit()
        notify_schedule_run(db, schedule, run, agent)
        return run
    except asyncio.CancelledError:
        run.status = ScheduleRunStatus.ERROR
        run.error_message = "任务被取消或服务中断"
        run.finished_at = now_utc()
        schedule.last_status = run.status.value
        session.status = SessionStatus.ERROR
        db.commit()
        notify_schedule_run(db, schedule, run, agent)
        raise
    except Exception as e:
        run.status = ScheduleRunStatus.ERROR
        run.error_message = str(e)[:2000]
        run.finished_at = now_utc()
        schedule.last_status = run.status.value
        session.status = SessionStatus.ERROR
        db.commit()
        notify_schedule_run(db, schedule, run, agent)
        return run
    finally:
        if run.status == ScheduleRunStatus.RUNNING:
            run.status = ScheduleRunStatus.ERROR
            run.error_message = run.error_message or "任务异常中断"
            run.finished_at = now_utc()
            schedule.last_status = run.status.value
            db.commit()
            notify_schedule_run(db, schedule, run, agent)
