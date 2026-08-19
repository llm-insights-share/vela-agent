from __future__ import annotations

from datetime import datetime, timezone

import pytest

from database import SessionLocal
from models import (
    Agent,
    AgentSchedule,
    AgentScheduleRun,
    AgentStatus,
    AgentType,
    InboxMessage,
    ModelProvider,
    ModelService,
    ProviderStatus,
    ScheduleRunStatus,
    Session as SessionModel,
    SessionStatus,
)
from services.inbox import mark_read_by_session, notify_async_session, notify_user
from services.schedule.runner import notify_schedule_run
from services.schedule.scheduler import AgentScheduleScheduler
from services.schedule.template import render_schedule_prompt


def _create_agent_bundle(db):
    provider = ModelProvider(
        provider_code=f"provider_{datetime.now().timestamp()}",
        display_name="provider",
        base_url="https://example.com/v1",
        api_key="x",
        status=ProviderStatus.ACTIVE,
    )
    db.add(provider)
    db.commit()
    db.refresh(provider)

    model = ModelService(
        provider_id=provider.provider_id,
        model_name="test-model",
        display_name="test-model",
    )
    db.add(model)
    db.commit()
    db.refresh(model)

    agent = Agent(
        name=f"agent_{datetime.now().timestamp()}",
        model_service_id=model.model_service_id,
        agent_type=AgentType.SINGLE,
        status=AgentStatus.PUBLISHED,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return provider, model, agent


def test_render_schedule_prompt_timezone():
    dt = datetime(2026, 8, 18, 8, 30, 0, tzinfo=timezone.utc)
    rendered = render_schedule_prompt(
        "任务={{schedule_name}} 时间={{time}} 日期={{date}} 智能体={{agent_name}}",
        schedule_name="晨报",
        agent_name="日报助手",
        now=dt,
        timezone_name="Asia/Shanghai",
    )
    assert "任务=晨报" in rendered
    assert "智能体=日报助手" in rendered
    assert "日期=2026-08-18" in rendered
    assert "时间=16:30:00" in rendered


@pytest.mark.asyncio
async def test_scheduler_skip_if_running_creates_skipped_run():
    from database import init_db

    init_db()
    db = SessionLocal()
    schedule = None
    try:
        _, _, agent = _create_agent_bundle(db)
        schedule = AgentSchedule(
            name=f"schedule_{datetime.now().timestamp()}",
            agent_id=agent.agent_id,
            enabled=True,
            cron_expression="* * * * *",
            timezone="Asia/Shanghai",
            prompt_template="hello",
            skip_if_running=True,
            created_by="user_inbox_test",
        )
        db.add(schedule)
        db.commit()
        db.refresh(schedule)

        running = AgentScheduleRun(
            schedule_id=schedule.schedule_id,
            status=ScheduleRunStatus.RUNNING,
            scheduled_for=datetime.now(timezone.utc),
        )
        db.add(running)
        db.commit()

        scheduler = AgentScheduleScheduler(poll_interval_seconds=60)
        now_utc = datetime.now(timezone.utc)
        await scheduler._check_one(db, schedule, now_utc)

        skipped = (
            db.query(AgentScheduleRun)
            .filter(
                AgentScheduleRun.schedule_id == schedule.schedule_id,
                AgentScheduleRun.status == ScheduleRunStatus.SKIPPED,
            )
            .count()
        )
        assert skipped >= 1
        skipped_run = (
            db.query(AgentScheduleRun)
            .filter(
                AgentScheduleRun.schedule_id == schedule.schedule_id,
                AgentScheduleRun.status == ScheduleRunStatus.SKIPPED,
            )
            .first()
        )
        msgs = (
            db.query(InboxMessage)
            .filter(
                InboxMessage.user_id == "user_inbox_test",
                InboxMessage.related_type == "schedule_run",
                InboxMessage.related_id == f"{skipped_run.run_id}:SKIPPED",
            )
            .all()
        )
        assert len(msgs) == 1
        assert msgs[0].is_read is False
        assert msgs[0].title == "定时任务已跳过"
        notify_schedule_run(db, schedule, skipped_run)
        again = (
            db.query(InboxMessage)
            .filter(
                InboxMessage.user_id == "user_inbox_test",
                InboxMessage.related_id == f"{skipped_run.run_id}:SKIPPED",
            )
            .count()
        )
        assert again == 1
    finally:
        if schedule:
            run_ids = [
                r.run_id
                for r in db.query(AgentScheduleRun).filter(AgentScheduleRun.schedule_id == schedule.schedule_id).all()
            ]
            if run_ids:
                from sqlalchemy import or_
                conds = [InboxMessage.related_id.in_(run_ids)]
                conds.extend(InboxMessage.related_id.startswith(f"{rid}:") for rid in run_ids)
                db.query(InboxMessage).filter(or_(*conds)).delete(synchronize_session=False)
            db.query(AgentScheduleRun).filter(AgentScheduleRun.schedule_id == schedule.schedule_id).delete()
            db.query(AgentSchedule).filter(AgentSchedule.schedule_id == schedule.schedule_id).delete()
            db.commit()
        db.close()


@pytest.mark.asyncio
async def test_scheduler_no_backfill_for_missed_window():
    db = SessionLocal()
    schedule = None
    try:
        _, _, agent = _create_agent_bundle(db)
        schedule = AgentSchedule(
            name=f"schedule_missed_{datetime.now().timestamp()}",
            agent_id=agent.agent_id,
            enabled=True,
            cron_expression="0 * * * *",
            timezone="Asia/Shanghai",
            prompt_template="hello",
            skip_if_running=True,
        )
        db.add(schedule)
        db.commit()
        db.refresh(schedule)

        scheduler = AgentScheduleScheduler(poll_interval_seconds=60)
        now_utc = datetime.now(timezone.utc).replace(minute=30, second=0, microsecond=0)
        await scheduler._check_one(db, schedule, now_utc)
        db.refresh(schedule)
        assert schedule.last_fired_at is None
    finally:
        if schedule:
            db.query(AgentScheduleRun).filter(AgentScheduleRun.schedule_id == schedule.schedule_id).delete()
            db.query(AgentSchedule).filter(AgentSchedule.schedule_id == schedule.schedule_id).delete()
            db.commit()
        db.close()


def test_notify_user_dedup_by_related_id():
    from database import init_db

    init_db()
    db = SessionLocal()
    related_id = f"run_{datetime.now().timestamp()}"
    try:
        first = notify_user(
            db,
            user_id="user_inbox_dedup",
            title="定时任务已跳过",
            body="demo · skip",
            related_type="schedule_run",
            related_id=related_id,
        )
        second = notify_user(
            db,
            user_id="user_inbox_dedup",
            title="定时任务已跳过",
            body="demo · skip again",
            related_type="schedule_run",
            related_id=related_id,
        )
        assert first is not None
        assert second is not None
        assert first.message_id == second.message_id
        count = (
            db.query(InboxMessage)
            .filter(InboxMessage.user_id == "user_inbox_dedup", InboxMessage.related_id == related_id)
            .count()
        )
        assert count == 1
    finally:
        db.query(InboxMessage).filter(InboxMessage.user_id == "user_inbox_dedup").delete()
        db.commit()
        db.close()


def _cleanup_schedule_inbox(db, schedule):
    if not schedule:
        return
    run_ids = [
        r.run_id
        for r in db.query(AgentScheduleRun).filter(AgentScheduleRun.schedule_id == schedule.schedule_id).all()
    ]
    if run_ids:
        from sqlalchemy import or_
        conds = [InboxMessage.related_id.in_(run_ids)]
        conds.extend(InboxMessage.related_id.startswith(f"{rid}:") for rid in run_ids)
        db.query(InboxMessage).filter(or_(*conds)).delete(synchronize_session=False)
    db.query(AgentScheduleRun).filter(AgentScheduleRun.schedule_id == schedule.schedule_id).delete()
    db.query(AgentSchedule).filter(AgentSchedule.schedule_id == schedule.schedule_id).delete()
    db.commit()


def test_notify_schedule_run_success_and_error():
    from database import init_db

    init_db()
    db = SessionLocal()
    schedule = None
    try:
        _, _, agent = _create_agent_bundle(db)
        schedule = AgentSchedule(
            name=f"schedule_term_{datetime.now().timestamp()}",
            agent_id=agent.agent_id,
            enabled=True,
            cron_expression="0 8 * * *",
            created_by="user_inbox_terminal",
        )
        db.add(schedule)
        db.commit()
        db.refresh(schedule)

        ok_run = AgentScheduleRun(
            schedule_id=schedule.schedule_id,
            status=ScheduleRunStatus.SUCCESS,
            scheduled_for=datetime.now(timezone.utc),
            summary="done",
        )
        err_run = AgentScheduleRun(
            schedule_id=schedule.schedule_id,
            status=ScheduleRunStatus.ERROR,
            scheduled_for=datetime.now(timezone.utc),
            error_message="boom",
        )
        db.add_all([ok_run, err_run])
        db.commit()
        db.refresh(ok_run)
        db.refresh(err_run)

        notify_schedule_run(db, schedule, ok_run, agent)
        notify_schedule_run(db, schedule, err_run, agent)

        titles = {
            m.title
            for m in db.query(InboxMessage).filter(InboxMessage.user_id == "user_inbox_terminal").all()
        }
        assert "定时任务已完成" in titles
        assert "定时任务失败" in titles
        ok_msg = (
            db.query(InboxMessage)
            .filter(InboxMessage.related_id == f"{ok_run.run_id}:SUCCESS")
            .first()
        )
        err_msg = (
            db.query(InboxMessage)
            .filter(InboxMessage.related_id == f"{err_run.run_id}:ERROR")
            .first()
        )
        assert ok_msg is not None and ok_msg.level == "success"
        assert err_msg is not None and err_msg.level == "warning"
    finally:
        db.query(InboxMessage).filter(InboxMessage.user_id == "user_inbox_terminal").delete()
        _cleanup_schedule_inbox(db, schedule)
        db.close()


def test_notify_schedule_run_hitl_then_success_creates_two_messages():
    from database import init_db

    init_db()
    db = SessionLocal()
    schedule = None
    try:
        _, _, agent = _create_agent_bundle(db)
        schedule = AgentSchedule(
            name=f"schedule_hitl_{datetime.now().timestamp()}",
            agent_id=agent.agent_id,
            enabled=True,
            cron_expression="0 8 * * *",
            created_by="user_inbox_hitl",
        )
        db.add(schedule)
        db.commit()
        db.refresh(schedule)
        run = AgentScheduleRun(
            schedule_id=schedule.schedule_id,
            status=ScheduleRunStatus.HITL_WAIT,
            scheduled_for=datetime.now(timezone.utc),
            summary="waiting",
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        notify_schedule_run(db, schedule, run, agent)
        run.status = ScheduleRunStatus.SUCCESS
        run.summary = "approved"
        db.commit()
        notify_schedule_run(db, schedule, run, agent)

        msgs = (
            db.query(InboxMessage)
            .filter(InboxMessage.user_id == "user_inbox_hitl")
            .order_by(InboxMessage.created_at.asc())
            .all()
        )
        assert len(msgs) == 2
        assert msgs[0].title == "定时任务待审批"
        assert msgs[0].related_id == f"{run.run_id}:HITL_WAIT"
        assert msgs[1].title == "定时任务已完成"
        assert msgs[1].related_id == f"{run.run_id}:SUCCESS"
    finally:
        db.query(InboxMessage).filter(InboxMessage.user_id == "user_inbox_hitl").delete()
        _cleanup_schedule_inbox(db, schedule)
        db.close()


def test_notify_async_session_success_and_skip_schedule_caller():
    from database import init_db

    init_db()
    db = SessionLocal()
    user_id = "user_async_inbox"
    sessions = []
    try:
        _, _, agent = _create_agent_bundle(db)
        user_session = SessionModel(
            agent_id=agent.agent_id,
            caller_type="USER",
            caller_id=user_id,
            status=SessionStatus.ACTIVE,
            messages=[{"role": "user", "content": "写一份日报"}],
        )
        sched_session = SessionModel(
            agent_id=agent.agent_id,
            caller_type="SCHEDULE",
            caller_id=user_id,
            status=SessionStatus.ACTIVE,
            messages=[{"role": "user", "content": "定时任务"}],
        )
        db.add_all([user_session, sched_session])
        db.commit()
        db.refresh(user_session)
        db.refresh(sched_session)
        sessions = [user_session, sched_session]

        job_key = "2026-08-19T02:00:00+00:00"
        msg = notify_async_session(db, user_session, job_key=job_key)
        again = notify_async_session(db, user_session, job_key=job_key)
        skipped = notify_async_session(db, sched_session, job_key=job_key)
        aborted = notify_async_session(db, user_session, job_key="other", aborted=True)

        assert msg is not None
        assert again is not None and again.message_id == msg.message_id
        assert skipped is None
        assert aborted is None
        assert msg.title == "会话任务已完成"
        assert msg.related_type == "async_session"
        assert msg.related_id == f"{user_session.session_id}:{job_key}"
        assert msg.link_path == f"/agents/{agent.agent_id}/chat?session_id={user_session.session_id}"
        assert "日报" in msg.body

        user_session.status = SessionStatus.HITL_WAIT
        db.commit()
        hitl = notify_async_session(db, user_session, job_key="2026-08-19T02:30:00+00:00")
        assert hitl is not None
        assert hitl.title == "会话任务待审批"

        user_session.status = SessionStatus.ERROR
        db.commit()
        err = notify_async_session(db, user_session, job_key="2026-08-19T03:00:00+00:00")
        assert err is not None
        assert err.title == "会话任务失败"
        assert err.message_id != msg.message_id

        marked = mark_read_by_session(db, user_id=user_id, session_id=user_session.session_id)
        assert marked == 3
        unread = (
            db.query(InboxMessage)
            .filter(
                InboxMessage.user_id == user_id,
                InboxMessage.is_read == False,  # noqa: E712
            )
            .count()
        )
        assert unread == 0
    finally:
        db.query(InboxMessage).filter(InboxMessage.user_id == user_id).delete()
        for s in sessions:
            db.query(SessionModel).filter(SessionModel.session_id == s.session_id).delete()
        db.commit()
        db.close()
