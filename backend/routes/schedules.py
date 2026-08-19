from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from croniter import croniter
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from deps import CurrentUser
from models import (
    Agent,
    AgentSchedule,
    AgentScheduleRun,
    AgentStatus,
    ScheduleTriggerType,
)
from schemas import (
    PaginatedResponse,
    ScheduleCreate,
    ScheduleCronPreviewRequest,
    ScheduleCronPreviewResponse,
    ScheduleResponse,
    ScheduleRunResponse,
    ScheduleUpdate,
)
from services.schedule.config import DEFAULT_SCHEDULE_TIMEZONE
from services.schedule.runner import execute_schedule_run

router = APIRouter(prefix="/api/v1/schedules", tags=["schedules"])


def _validate_cron(cron_expression: str, timezone_name: str) -> None:
    try:
        now = datetime.now(ZoneInfo(timezone_name))
        croniter(cron_expression, now).get_next(datetime)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"无效 cron 表达式: {e}") from e


def _safe_timezone(timezone_name: str) -> str:
    try:
        ZoneInfo(timezone_name)
        return timezone_name
    except Exception:
        raise HTTPException(status_code=400, detail=f"无效时区: {timezone_name}")


def _aware_utc(value):
    if not isinstance(value, datetime):
        return value
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _localize_datetimes(data: dict, keys: tuple[str, ...]) -> dict:
    for key in keys:
        data[key] = _aware_utc(data.get(key))
    return data


def _build_schedule_response(db: Session, schedule: AgentSchedule) -> ScheduleResponse:
    agent = db.query(Agent).filter(Agent.agent_id == schedule.agent_id).first()
    data = ScheduleResponse.model_validate(schedule).model_dump()
    data["agent_name"] = agent.name if agent else ""
    _localize_datetimes(data, ("last_fired_at", "next_run_at", "created_at", "updated_at"))
    return ScheduleResponse(**data)


def _build_run_response(db: Session, run: AgentScheduleRun) -> ScheduleRunResponse:
    schedule = db.query(AgentSchedule).filter(AgentSchedule.schedule_id == run.schedule_id).first()
    agent = db.query(Agent).filter(Agent.agent_id == schedule.agent_id).first() if schedule else None
    data = ScheduleRunResponse.model_validate(run).model_dump()
    data["agent_id"] = schedule.agent_id if schedule else ""
    data["agent_name"] = agent.name if agent else ""
    _localize_datetimes(data, ("scheduled_for", "started_at", "finished_at", "created_at"))
    return ScheduleRunResponse(**data)


@router.get("", response_model=PaginatedResponse)
def list_schedules(
    agent_id: Optional[str] = Query(None),
    enabled: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(AgentSchedule)
    if agent_id:
        query = query.filter(AgentSchedule.agent_id == agent_id)
    if enabled is not None:
        query = query.filter(AgentSchedule.enabled == enabled)
    total = query.count()
    items = (
        query.order_by(AgentSchedule.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PaginatedResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[_build_schedule_response(db, x) for x in items],
    )


@router.post("", response_model=ScheduleResponse, status_code=201)
def create_schedule(payload: ScheduleCreate, user: CurrentUser, db: Session = Depends(get_db)):
    timezone_name = _safe_timezone(payload.timezone)
    _validate_cron(payload.cron_expression, timezone_name)
    agent = db.query(Agent).filter(Agent.agent_id == payload.agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    if payload.enabled and agent.status != AgentStatus.PUBLISHED:
        raise HTTPException(status_code=400, detail="启用任务时 Agent 必须是已发布状态")

    now_local = datetime.now(ZoneInfo(timezone_name))
    schedule = AgentSchedule(
        name=payload.name.strip(),
        description=payload.description,
        agent_id=payload.agent_id,
        enabled=payload.enabled,
        cron_expression=payload.cron_expression.strip(),
        timezone=timezone_name,
        prompt_template=payload.prompt_template,
        skip_if_running=payload.skip_if_running,
        timeout_seconds=payload.timeout_seconds,
        created_by=user.user_id,
        next_run_at=croniter(payload.cron_expression, now_local).get_next(datetime).astimezone(timezone.utc),
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return _build_schedule_response(db, schedule)


@router.get("/runs/recent", response_model=PaginatedResponse)
def list_recent_runs(
    since: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(AgentScheduleRun)
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"since 参数无效: {e}") from e
        if since_dt.tzinfo is not None:
            since_dt = since_dt.astimezone(timezone.utc).replace(tzinfo=None)
        query = query.filter(AgentScheduleRun.created_at > since_dt)
    items = query.order_by(AgentScheduleRun.created_at.desc()).limit(limit).all()
    return PaginatedResponse(
        total=len(items),
        page=1,
        page_size=limit,
        items=[_build_run_response(db, x) for x in items],
    )


@router.post("/preview-cron", response_model=ScheduleCronPreviewResponse)
def preview_cron(payload: ScheduleCronPreviewRequest):
    timezone_name = _safe_timezone(payload.timezone)
    _validate_cron(payload.cron_expression, timezone_name)
    now_local = datetime.now(ZoneInfo(timezone_name))
    itr = croniter(payload.cron_expression, now_local)
    next_runs = [itr.get_next(datetime).isoformat() for _ in range(payload.count)]
    return ScheduleCronPreviewResponse(next_runs=next_runs)


@router.get("/{schedule_id}", response_model=ScheduleResponse)
def get_schedule(schedule_id: str, db: Session = Depends(get_db)):
    schedule = db.query(AgentSchedule).filter(AgentSchedule.schedule_id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    return _build_schedule_response(db, schedule)


@router.put("/{schedule_id}", response_model=ScheduleResponse)
def update_schedule(
    schedule_id: str,
    payload: ScheduleUpdate,
    db: Session = Depends(get_db),
):
    schedule = db.query(AgentSchedule).filter(AgentSchedule.schedule_id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="定时任务不存在")

    data = payload.model_dump(exclude_unset=True)
    next_timezone = _safe_timezone(data.get("timezone", schedule.timezone or DEFAULT_SCHEDULE_TIMEZONE))
    next_cron = data.get("cron_expression", schedule.cron_expression)
    _validate_cron(next_cron, next_timezone)

    if "agent_id" in data:
        agent = db.query(Agent).filter(Agent.agent_id == data["agent_id"]).first()
        if not agent:
            raise HTTPException(status_code=404, detail="Agent 不存在")
        if data.get("enabled", schedule.enabled) and agent.status != AgentStatus.PUBLISHED:
            raise HTTPException(status_code=400, detail="启用任务时 Agent 必须是已发布状态")

    if data.get("enabled", schedule.enabled):
        target_agent_id = data.get("agent_id", schedule.agent_id)
        target_agent = db.query(Agent).filter(Agent.agent_id == target_agent_id).first()
        if not target_agent or target_agent.status != AgentStatus.PUBLISHED:
            raise HTTPException(status_code=400, detail="启用任务时 Agent 必须是已发布状态")

    for key, value in data.items():
        setattr(schedule, key, value)

    now_local = datetime.now(ZoneInfo(next_timezone))
    schedule.next_run_at = croniter(next_cron, now_local).get_next(datetime).astimezone(timezone.utc)
    db.commit()
    db.refresh(schedule)
    return _build_schedule_response(db, schedule)


@router.delete("/{schedule_id}")
def delete_schedule(schedule_id: str, db: Session = Depends(get_db)):
    schedule = db.query(AgentSchedule).filter(AgentSchedule.schedule_id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    db.query(AgentScheduleRun).filter(AgentScheduleRun.schedule_id == schedule_id).delete()
    db.delete(schedule)
    db.commit()
    return {"message": "已删除"}


@router.post("/{schedule_id}/enable")
def enable_schedule(schedule_id: str, db: Session = Depends(get_db)):
    schedule = db.query(AgentSchedule).filter(AgentSchedule.schedule_id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    agent = db.query(Agent).filter(Agent.agent_id == schedule.agent_id).first()
    if not agent or agent.status != AgentStatus.PUBLISHED:
        raise HTTPException(status_code=400, detail="启用任务时 Agent 必须是已发布状态")
    schedule.enabled = True
    db.commit()
    return {"success": True}


@router.post("/{schedule_id}/disable")
def disable_schedule(schedule_id: str, db: Session = Depends(get_db)):
    schedule = db.query(AgentSchedule).filter(AgentSchedule.schedule_id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    schedule.enabled = False
    db.commit()
    return {"success": True}


@router.post("/{schedule_id}/trigger", response_model=ScheduleRunResponse)
async def trigger_schedule(schedule_id: str, db: Session = Depends(get_db)):
    schedule = db.query(AgentSchedule).filter(AgentSchedule.schedule_id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    run = await execute_schedule_run(
        db,
        schedule,
        trigger_type=ScheduleTriggerType.MANUAL,
        scheduled_for=datetime.now(timezone.utc),
    )
    db.refresh(run)
    return _build_run_response(db, run)


@router.get("/{schedule_id}/runs", response_model=PaginatedResponse)
def list_schedule_runs(
    schedule_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    schedule = db.query(AgentSchedule).filter(AgentSchedule.schedule_id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    query = db.query(AgentScheduleRun).filter(AgentScheduleRun.schedule_id == schedule_id)
    total = query.count()
    items = (
        query.order_by(AgentScheduleRun.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PaginatedResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[_build_run_response(db, x) for x in items],
    )
