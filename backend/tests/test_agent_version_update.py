from __future__ import annotations

from datetime import datetime

from database import SessionLocal, init_db
from models import (
    Agent,
    AgentStatus,
    AgentType,
    AgentVersion,
    ModelProvider,
    ModelService,
    ProviderStatus,
    VersionStatus,
)
from schemas import AgentUpdate
from services.agent_service import AgentService


def _create_agent(db, *, status: AgentStatus):
    provider = ModelProvider(
        provider_code=f"provider_{datetime.now().timestamp()}",
        display_name="provider",
        base_url="https://example.com/v1",
        api_key="x",
        status=ProviderStatus.ACTIVE,
    )
    db.add(provider)
    db.flush()

    model = ModelService(
        provider_id=provider.provider_id,
        model_name="test-model",
        display_name="test-model",
    )
    db.add(model)
    db.flush()

    agent = Agent(
        name=f"agent_{datetime.now().timestamp()}",
        model_service_id=model.model_service_id,
        agent_type=AgentType.SINGLE,
        status=status,
        description="before",
    )
    db.add(agent)
    db.flush()

    version = AgentVersion(
        agent_id=agent.agent_id,
        version="1.0.0" if status == AgentStatus.PUBLISHED else "1.0.0-draft",
        version_seq=1,
        change_summary="初始",
        snapshot={},
        status=VersionStatus.PUBLISHED if status == AgentStatus.PUBLISHED else VersionStatus.DRAFT,
    )
    db.add(version)
    db.flush()
    agent.current_version_id = version.version_id
    db.commit()
    db.refresh(agent)
    return agent, version


def test_update_published_agent_auto_publishes_new_version():
    init_db()
    db = SessionLocal()
    try:
        agent, prev = _create_agent(db, status=AgentStatus.PUBLISHED)
        updated = AgentService.update_agent(
            db,
            agent.agent_id,
            AgentUpdate(description="after-publish-edit", change_summary="配置修改"),
        )
        assert updated is not None
        assert updated.status == AgentStatus.PUBLISHED
        assert updated.current_version_id != prev.version_id

        db.refresh(prev)
        assert prev.status == VersionStatus.DEPRECATED

        current = db.query(AgentVersion).filter(
            AgentVersion.version_id == updated.current_version_id
        ).first()
        assert current is not None
        assert current.status == VersionStatus.PUBLISHED
        assert "-draft" not in current.version
        assert current.created_at is not None
    finally:
        db.close()


def test_update_draft_agent_keeps_draft_version():
    init_db()
    db = SessionLocal()
    try:
        agent, prev = _create_agent(db, status=AgentStatus.DRAFT)
        updated = AgentService.update_agent(
            db,
            agent.agent_id,
            AgentUpdate(description="after-draft-edit", change_summary="配置修改"),
        )
        assert updated is not None
        assert updated.status == AgentStatus.DRAFT
        assert updated.current_version_id != prev.version_id

        db.refresh(prev)
        assert prev.status == VersionStatus.DRAFT

        current = db.query(AgentVersion).filter(
            AgentVersion.version_id == updated.current_version_id
        ).first()
        assert current is not None
        assert current.status == VersionStatus.DRAFT
        assert current.version.endswith("-draft")
    finally:
        db.close()
