"""Tests for system context-block defaults and Agent × mode overrides."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from database import SessionLocal, init_db
from main import app
from models import (
    Agent,
    AgentContextBlock,
    AgentStatus,
    AgentType,
    ModelProvider,
    ModelService,
    ProviderStatus,
    User,
    gen_uuid,
)
from security import create_access_token, hash_password
from services import context_block_service as cbs
from services.agent_service import AgentLoop
from services.builtin_tools import BuiltinTool
from services.context_block_defaults import get_system_default_specs
from services.tool_search.config import ToolSearchConfig


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


def _agent(db, system_prompt: str = "你是测试助手。") -> Agent:
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
        name=f"ctx_agent_{gen_uuid()[:8]}",
        description="",
        model_service_id=model.model_service_id,
        system_prompt=system_prompt,
        status=AgentStatus.PUBLISHED,
        agent_type=AgentType.SINGLE,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


def test_system_defaults_stable_and_mode_specific():
    auto = get_system_default_specs("auto", system_prompt="人设A")
    plan = get_system_default_specs("plan_and_execute", system_prompt="人设A")
    keys_auto = [b["block_key"] for b in auto]
    keys_plan = [b["block_key"] for b in plan]
    assert "system_base" in keys_auto
    assert "date" in keys_auto
    assert "plan_prompt" not in keys_auto
    assert "plan_prompt" in keys_plan
    assert auto[0]["content"] == "人设A"
    # Mutating returned list must not pollute catalog
    auto[0]["content"] = "HACKED"
    again = get_system_default_specs("auto", system_prompt="人设A")
    assert again[0]["content"] == "人设A"


def test_api_defaults_restore_and_put(tmp_path=None):
    db = SessionLocal()
    try:
        user = _user(db, f"ctx_u_{gen_uuid()[:6]}")
        agent = _agent(db, system_prompt="原始人设")
        client = _client_for(user)

        r = client.get("/api/v1/context-blocks/defaults", params={"execution_mode": "react"})
        assert r.status_code == 200
        defaults = r.json()["items"]
        assert any(i["block_key"] == "system_base" for i in defaults)
        assert all(not i.get("deletable") for i in defaults)

        r2 = client.get(
            f"/api/v1/agents/{agent.agent_id}/context-blocks",
            params={"execution_mode": "react"},
        )
        assert r2.status_code == 200
        items = r2.json()["items"]
        assert len(items) >= 8
        base = next(i for i in items if i["block_key"] == "system_base")
        assert base["content"] == "原始人设"

        # Customize
        for i in items:
            if i["block_key"] == "system_base":
                i["content"] = "改写人设"
            if i["block_key"] == "date":
                i["enabled"] = False
        items.append({
            "block_key": "custom_test1",
            "title": "自定义",
            "placement": "system",
            "source": "static",
            "content": "CUSTOM_BLOCK_TEXT",
            "enabled": True,
            "sort_order": 999,
            "deletable": True,
        })
        r3 = client.put(
            f"/api/v1/agents/{agent.agent_id}/context-blocks",
            params={"execution_mode": "react"},
            json={"items": items},
        )
        assert r3.status_code == 200
        saved = r3.json()["items"]
        assert any(i["block_key"] == "custom_test1" for i in saved)
        db.refresh(agent)
        assert agent.system_prompt == "改写人设"

        # Defaults catalog unchanged (uses empty system_prompt → 缺省人设文案)
        r4 = client.get("/api/v1/context-blocks/defaults", params={"execution_mode": "react"})
        dbase = next(i for i in r4.json()["items"] if i["block_key"] == "system_base")
        assert dbase["content"] == "你是一个智能助手。"

        # Restore defaults for this mode
        r5 = client.post(
            f"/api/v1/agents/{agent.agent_id}/context-blocks/restore-defaults",
            params={"execution_mode": "react"},
        )
        assert r5.status_code == 200
        restored = r5.json()["items"]
        assert not any(i["block_key"].startswith("custom_") for i in restored)
        assert next(i for i in restored if i["block_key"] == "date")["enabled"] is True
        # system_base uses current agent.system_prompt (still 改写人设 until agent edit)
        assert next(i for i in restored if i["block_key"] == "system_base")["content"] == "改写人设"
    finally:
        db.close()


def test_enabled_false_excluded_from_system_prompt():
    loop = object.__new__(AgentLoop)
    loop.db = MagicMock()
    loop.db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
    loop.agent = SimpleNamespace(system_prompt="人设", agent_id="a1")
    loop.session = SimpleNamespace(session_id="sess-1")
    loop.available_tools = []
    loop.connector_context = ""
    loop.knowledge_context = "\n\n## 知识库\n- kb"
    loop.project_context = ""
    loop.tool_loading_cfg = ToolSearchConfig(enabled=False, mode="all")
    loop._context_blocks = [
        {
            "block_key": "system_base",
            "title": "基础人设",
            "placement": "system",
            "source": "static",
            "content": "人设",
            "enabled": True,
            "sort_order": 10,
            "deletable": False,
        },
        {
            "block_key": "knowledge",
            "title": "知识库",
            "placement": "system",
            "source": "dynamic",
            "content": "{body}",
            "enabled": False,
            "sort_order": 60,
            "deletable": False,
        },
        {
            "block_key": "date",
            "title": "日期",
            "placement": "system",
            "source": "dynamic",
            "content": "当前日期：{today}（星期{weekday}）。",
            "enabled": True,
            "sort_order": 80,
            "deletable": False,
        },
        {
            "block_key": "custom_x",
            "title": "自定义",
            "placement": "system",
            "source": "static",
            "content": "HELLO_CUSTOM",
            "enabled": True,
            "sort_order": 90,
            "deletable": True,
        },
    ]
    # stub deferred check
    loop._deferred_tool_names = lambda: set()

    prompt = loop._build_system_prompt()
    assert "人设" in prompt
    assert "知识库" not in prompt
    assert "HELLO_CUSTOM" in prompt
    assert "当前日期：" in prompt


def test_runtime_merge_uses_overrides(db_session=None):
    db = SessionLocal()
    try:
        agent = _agent(db, system_prompt="SP")
        specs = get_system_default_specs("direct", system_prompt="SP")
        # materialize then tweak
        cbs.restore_defaults(db, agent, "direct")
        row = (
            db.query(AgentContextBlock)
            .filter(
                AgentContextBlock.agent_id == agent.agent_id,
                AgentContextBlock.execution_mode == "direct",
                AgentContextBlock.block_key == "system_base",
            )
            .first()
        )
        row.content = "OVERRIDE_SP"
        db.commit()

        effective = cbs.get_effective_blocks_for_runtime(
            db, agent.agent_id, "direct", system_prompt="SP"
        )
        base = next(b for b in effective if b["block_key"] == "system_base")
        assert base["content"] == "OVERRIDE_SP"

        # Put agent override must not change system defaults function output
        defaults = get_system_default_specs("direct", system_prompt="SP")
        assert defaults[0]["content"] == "SP"
    finally:
        db.close()


def test_plan_prompt_from_block():
    loop = object.__new__(AgentLoop)
    loop._context_blocks = [
        {
            "block_key": "plan_prompt",
            "title": "计划",
            "placement": "mode_inject",
            "source": "static",
            "content": "CUSTOM_PLAN_PROMPT",
            "enabled": True,
            "sort_order": 110,
            "deletable": False,
        }
    ]
    assert loop._ctx_block("plan_prompt")["content"] == "CUSTOM_PLAN_PROMPT"
    assert loop._ctx_enabled("plan_prompt") is True
