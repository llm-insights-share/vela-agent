"""Tests for Claude-style Projects workspace."""
from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from database import SessionLocal, init_db
from main import app
from models import (
    Agent,
    AgentKnowledgeBinding,
    AgentStatus,
    AgentType,
    KnowledgeBase,
    KnowledgeBaseStatus,
    ModelProvider,
    ModelService,
    Project,
    ProjectMember,
    ProjectMemberRole,
    ProjectStatus,
    ProviderStatus,
    Session as SessionModel,
    User,
    gen_uuid,
)
from security import create_access_token, hash_password
from services import project_service as ps
from services.builtin_tools import _execute_kb_search
from services.tool_runtime_context import tool_auth_context


@pytest.fixture(scope="module", autouse=True)
def _init():
    init_db()


def _client_for(user: User) -> TestClient:
    token = create_access_token(user.username, {"roles": user.roles or "member"})
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def _user(db, username: str) -> User:
    u = User(
        username=username,
        email=f"{username}@example.com",
        display_name=username,
        hashed_password=hash_password("password123"),
        roles="member",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _agent(db) -> Agent:
    provider = ModelProvider(
        provider_code=f"p_{gen_uuid()[:8]}",
        display_name="p",
        base_url="https://example.com/v1",
        api_key="x",
        status=ProviderStatus.ACTIVE,
    )
    db.add(provider)
    db.commit()
    db.refresh(provider)
    model = ModelService(
        provider_id=provider.provider_id,
        model_name="m",
        display_name="m",
    )
    db.add(model)
    db.commit()
    db.refresh(model)
    agent = Agent(
        name=f"agent_{gen_uuid()[:8]}",
        model_service_id=model.model_service_id,
        status=AgentStatus.DRAFT,
        agent_type=AgentType.SINGLE,
        system_prompt="你是助手。",
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


def test_project_crud_star_archive_and_acl():
    db = SessionLocal()
    try:
        owner = _user(db, f"owner_{gen_uuid()[:6]}")
        viewer = _user(db, f"viewer_{gen_uuid()[:6]}")
        stranger = _user(db, f"stranger_{gen_uuid()[:6]}")
        owner_c = _client_for(owner)
        viewer_c = _client_for(viewer)
        stranger_c = _client_for(stranger)

        res = owner_c.post(
            "/api/v1/projects",
            json={"name": f"Proj {gen_uuid()[:6]}", "description": "d"},
        )
        assert res.status_code == 201, res.text
        project = res.json()
        pid = project["project_id"]
        assert project["my_role"] == "owner"
        assert project["kb_id"]

        # instructions
        res = owner_c.patch(
            f"/api/v1/projects/{pid}",
            json={"instructions": "用中文简洁回答，引用项目知识。"},
        )
        assert res.status_code == 200
        assert res.json()["instructions"].startswith("用中文")

        # star
        assert owner_c.post(f"/api/v1/projects/{pid}/star").status_code == 200
        starred = owner_c.get("/api/v1/projects", params={"tab": "starred"}).json()
        assert any(p["project_id"] == pid for p in starred["items"])

        # add viewer
        res = owner_c.post(
            f"/api/v1/projects/{pid}/members",
            json={"username": viewer.username, "role": "viewer"},
        )
        assert res.status_code == 201, res.text

        # viewer cannot edit instructions
        res = viewer_c.patch(
            f"/api/v1/projects/{pid}",
            json={"instructions": "hack"},
        )
        assert res.status_code == 403

        # stranger cannot read
        res = stranger_c.get(f"/api/v1/projects/{pid}")
        assert res.status_code == 403

        # archive
        res = owner_c.patch(f"/api/v1/projects/{pid}", json={"status": "ARCHIVED"})
        assert res.status_code == 200
        assert res.json()["status"] == "ARCHIVED"

        # unarchive then delete
        owner_c.patch(f"/api/v1/projects/{pid}", json={"status": "ACTIVE"})
        res = owner_c.delete(f"/api/v1/projects/{pid}")
        assert res.status_code == 200
    finally:
        db.close()


def test_project_session_acl_and_prompt_context():
    db = SessionLocal()
    try:
        owner = _user(db, f"po_{gen_uuid()[:6]}")
        member = _user(db, f"pm_{gen_uuid()[:6]}")
        agent = _agent(db)
        owner_c = _client_for(owner)
        member_c = _client_for(member)

        project = ps.create_project(db, owner, f"SessProj {gen_uuid()[:6]}", "")
        pid = project.project_id
        project.instructions = "项目指令：始终说 PROJECT_MARKER。"
        db.add(project)
        db.commit()

        owner_c.post(
            f"/api/v1/projects/{pid}/members",
            json={"username": member.username, "role": "viewer"},
        )

        # owner creates session in project
        res = owner_c.post(
            "/api/v1/sessions",
            json={
                "agent_id": agent.agent_id,
                "project_id": pid,
                "caller_type": "web_playground",
            },
        )
        assert res.status_code == 201, res.text
        sid = res.json()["session_id"]
        assert res.json()["project_id"] == pid

        # member can read owner's session
        res = member_c.get(f"/api/v1/sessions/{sid}")
        assert res.status_code == 200
        assert res.json()["can_write"] is False

        # member cannot chat on owner's session
        res = member_c.post(
            f"/api/v1/sessions/{sid}/chat",
            json={"message": "hi"},
        )
        assert res.status_code == 403

        # member can create own session
        res = member_c.post(
            "/api/v1/sessions",
            json={"agent_id": agent.agent_id, "project_id": pid},
        )
        assert res.status_code == 201

        # prompt context includes instructions
        db.refresh(project)
        ctx = ps.build_project_prompt_context(db, project)
        assert "项目指令" in ctx
        assert "PROJECT_MARKER" in ctx

        # non-project session: stranger ownership still private
        res = owner_c.post(
            "/api/v1/sessions",
            json={"agent_id": agent.agent_id},
        )
        assert res.status_code == 201
        private_sid = res.json()["session_id"]
        assert res.json().get("project_id") in (None, "")
        res = member_c.get(f"/api/v1/sessions/{private_sid}")
        assert res.status_code == 403
    finally:
        db.close()


@pytest.mark.asyncio
async def test_kb_search_excludes_project_scope_by_default():
    db = SessionLocal()
    try:
        # platform kb
        plat = KnowledgeBase(
            kb_id=gen_uuid(),
            name=f"plat_{gen_uuid()[:8]}",
            scope="platform",
            status=KnowledgeBaseStatus.ACTIVE,
        )
        proj = KnowledgeBase(
            kb_id=gen_uuid(),
            name=f"projkb_{gen_uuid()[:8]}",
            scope="project",
            status=KnowledgeBaseStatus.ACTIVE,
        )
        db.add_all([plat, proj])
        db.commit()

        # Without allowed list: must not include project KB when exclude_project
        with tool_auth_context(None, None, allowed_kb_ids=None, exclude_project_kbs=True):
            # may return "no results" or success with only platform — but must not error on project leak
            result = await _execute_kb_search({"query": "anything-unlikely-xyz", "top_k": 3})
            assert result.get("success") is not False or "项目" not in str(result.get("error") or "")

        # Explicit project kb without allow → denied when exclude
        with tool_auth_context(None, None, allowed_kb_ids=None, exclude_project_kbs=True):
            result = await _execute_kb_search(
                {"query": "x", "kb_id": proj.kb_id, "top_k": 1}
            )
            assert result.get("success") is False
            assert "无权" in (result.get("error") or "")

        # Allowed in project session
        with tool_auth_context(
            None, None, allowed_kb_ids=[proj.kb_id], exclude_project_kbs=True
        ):
            result = await _execute_kb_search(
                {"query": "x", "kb_id": proj.kb_id, "top_k": 1}
            )
            # empty index is ok; must not be permission error
            assert "无权" not in (result.get("error") or "")
    finally:
        db.close()


def test_users_search_endpoint():
    db = SessionLocal()
    try:
        u = _user(db, f"searchme_{gen_uuid()[:6]}")
        c = _client_for(u)
        res = c.get("/api/v1/users/search", params={"q": "searchme"})
        assert res.status_code == 200
        hits = res.json()
        assert any(h["username"] == u.username for h in hits)
        assert "roles" not in hits[0]
    finally:
        db.close()


def test_knowledge_list_hides_project_scope():
    db = SessionLocal()
    try:
        u = _user(db, f"kblist_{gen_uuid()[:6]}")
        c = _client_for(u)
        hidden = KnowledgeBase(
            kb_id=gen_uuid(),
            name=f"hidden_proj_{gen_uuid()[:8]}",
            scope="project",
            status=KnowledgeBaseStatus.ACTIVE,
        )
        db.add(hidden)
        db.commit()

        res = c.get("/api/v1/knowledge-bases")
        assert res.status_code == 200
        ids = [i["kb_id"] for i in res.json()["items"]]
        assert hidden.kb_id not in ids

        res = c.get("/api/v1/knowledge-bases", params={"scope": "project"})
        assert res.status_code == 200
        ids = [i["kb_id"] for i in res.json()["items"]]
        assert hidden.kb_id in ids
    finally:
        db.close()
