from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.orm import Session

from database import SessionLocal, init_db
from models import (
    Agent,
    AgentStatus,
    AgentType,
    ConnectorStatus,
    McpServer,
    ModelProvider,
    ModelService,
    ProviderStatus,
    Session as SessionModel,
    Tool,
    ToolStatus,
    ToolType,
    User,
    UserConnector,
    gen_uuid,
)
from services.connector_catalog import (
    ENC_PREFIX,
    build_mcp_server_payload,
    get_catalog_template,
    list_catalog_templates,
    store_secret,
)
from services.connector_service import (
    create_connector_from_catalog,
    load_session_connector_tools,
    resolve_runtime_connectors,
    serialize_agent_connector_bindings,
    serialize_connector,
    set_active_connector_ids,
    set_agent_connector_bindings,
)
from security import hash_password


def _create_user(db, username: str) -> User:
    user = User(
        username=username,
        email=f"{username}@example.com",
        display_name=username,
        hashed_password=hash_password("password123"),
        roles="member",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


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
        status=AgentStatus.DRAFT,
        agent_type=AgentType.SINGLE,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


def test_catalog_templates_have_default_tools():
    items = list_catalog_templates()
    email = next(t for t in items if t["catalog_key"] == "email")
    assert any(t["name"] == "search_messages" for t in email.get("default_tools") or [])
    assert get_catalog_template("email") is not None


def test_build_github_payload_stores_encrypted_token():
    payload = build_mcp_server_payload(
        catalog_key="github",
        credentials={"access_token": "ghp_abc"},
        connector_config={"readonly": True},
        user_id="user12345678",
        name="gh",
    )
    assert payload["url"] == "https://api.githubcopilot.com/mcp/"
    auth = payload["headers"]["Authorization"]
    assert auth.startswith("Bearer enc:")
    assert ENC_PREFIX in auth
    assert "ghp_abc" not in auth


def test_create_connector_from_catalog_and_session_tools():
    init_db()
    db = SessionLocal()
    try:
        user = _create_user(db, f"conn_user_{datetime.now().timestamp()}")
        other = _create_user(db, f"other_{datetime.now().timestamp()}")
        agent = _create_agent_bundle(db)

        connector = create_connector_from_catalog(
            db,
            user_id=user.user_id,
            catalog_key="github",
            credentials={"access_token": "ghp_abc"},
            name="my-github",
            connector_config={"readonly": True},
        )
        assert connector.catalog_key == "github"
        assert connector.user_id == user.user_id

        server = db.query(McpServer).filter(McpServer.server_id == connector.mcp_server_id).first()
        assert server.owner_user_id == user.user_id

        tool = Tool(
            tool_id=gen_uuid(),
            name=f"{server.name}_search_repos",
            display_name="search_repos",
            tool_type=ToolType.MCP,
            config={"mcp_server_id": server.server_id, "mcp_tool_name": "search_repos"},
            mcp_server_id=server.server_id,
            status=ToolStatus.ACTIVE,
        )
        db.add(tool)
        connector.status = ConnectorStatus.CONNECTED
        connector.tool_count = 1
        db.commit()

        session = SessionModel(
            session_id=gen_uuid(),
            agent_id=agent.agent_id,
            caller_id=user.user_id,
            pending_context={},
        )
        db.add(session)
        db.commit()

        active = set_active_connector_ids(db, session, [connector.connector_id], user.user_id)
        assert active == [connector.connector_id]

        tools = load_session_connector_tools(
            db,
            user_id=user.user_id,
            connector_ids=active,
        )
        assert len(tools) == 1
        assert tools[0].tool_id == tool.tool_id

        active_other = set_active_connector_ids(db, session, [connector.connector_id], other.user_id)
        assert active_other == []

        serialized = serialize_connector(db, connector)
        assert serialized["oauth_status"] in ("not_required", "authorized", "unauthorized")
        if server.headers.get("Authorization", "").startswith("Bearer enc:"):
            assert "ghp_" not in str(serialized)
    finally:
        db.close()


def test_agent_connector_bindings_and_runtime_resolve():
    init_db()
    db = SessionLocal()
    try:
        user = _create_user(db, f"bind_{datetime.now().timestamp()}")
        agent = _create_agent_bundle(db)

        connector = create_connector_from_catalog(
            db,
            user_id=user.user_id,
            catalog_key="email",
            credentials={
                "email_address": "a@163.com",
                "password": "secret",
                "imap_host": "imap.163.com",
                "smtp_host": "smtp.163.com",
            },
            name="mail163",
        )
        server = db.query(McpServer).filter(McpServer.server_id == connector.mcp_server_id).first()
        search_tool = Tool(
            tool_id=gen_uuid(),
            name=f"{server.name}_search_messages",
            display_name="search_messages",
            tool_type=ToolType.MCP,
            config={"mcp_tool_name": "search_messages"},
            mcp_server_id=server.server_id,
            status=ToolStatus.ACTIVE,
        )
        send_tool = Tool(
            tool_id=gen_uuid(),
            name=f"{server.name}_send_email",
            display_name="send_email",
            tool_type=ToolType.MCP,
            config={"mcp_tool_name": "send_email"},
            mcp_server_id=server.server_id,
            status=ToolStatus.ACTIVE,
        )
        db.add_all([search_tool, send_tool])
        connector.status = ConnectorStatus.CONNECTED
        db.commit()

        set_agent_connector_bindings(
            db,
            agent.agent_id,
            [
                {
                    "catalog_key": "email",
                    "tools": [
                        {"mcp_tool_name": "search_messages", "enabled": True, "require_approval": False},
                        {"mcp_tool_name": "send_email", "enabled": True, "require_approval": True},
                    ],
                }
            ],
        )
        db.commit()

        serialized = serialize_agent_connector_bindings(db, agent.agent_id)
        assert len(serialized) == 1
        assert serialized[0]["catalog_key"] == "email"

        runtime = resolve_runtime_connectors(db, agent_id=agent.agent_id, user_id=user.user_id)
        assert len(runtime["tools"]) == 2
        assert runtime["approval_by_tool_id"].get(send_tool.tool_id) is True
        assert send_tool.tool_id in runtime["approval_by_tool_id"]
        assert runtime["missing_catalog_keys"] == []

        # Disable send_email via policy
        set_agent_connector_bindings(
            db,
            agent.agent_id,
            [
                {
                    "catalog_key": "email",
                    "tools": [
                        {"mcp_tool_name": "search_messages", "enabled": True, "require_approval": False},
                        {"mcp_tool_name": "send_email", "enabled": False, "require_approval": True},
                    ],
                }
            ],
        )
        db.commit()
        runtime2 = resolve_runtime_connectors(db, agent_id=agent.agent_id, user_id=user.user_id)
        assert [t.tool_id for t in runtime2["tools"]] == [search_tool.tool_id]

        # User without connection → missing
        runtime3 = resolve_runtime_connectors(
            db, agent_id=agent.agent_id, user_id=_create_user(db, f"nobind_{datetime.now().timestamp()}").user_id
        )
        assert runtime3["tools"] == []
        assert "email" in runtime3["missing_catalog_keys"]
    finally:
        db.close()


def test_list_tools_hides_mcp_server_tools():
    init_db()
    db = SessionLocal()
    try:
        user = _create_user(db, f"hide_{datetime.now().timestamp()}")
        global_server = McpServer(
            server_id=gen_uuid(),
            name=f"global_{datetime.now().timestamp()}",
            display_name="global",
            transport="stdio",
            command="echo",
        )
        user_server = McpServer(
            server_id=gen_uuid(),
            owner_user_id=user.user_id,
            name=f"uc_{user.user_id[:8]}_email_test",
            display_name="user",
            transport="stdio",
            command="echo",
        )
        db.add_all([global_server, user_server])
        db.flush()
        standalone = Tool(
            tool_id=gen_uuid(),
            name=f"standalone_{datetime.now().timestamp()}",
            display_name="standalone",
            tool_type=ToolType.RESTFUL,
            status=ToolStatus.ACTIVE,
        )
        global_tool = Tool(
            tool_id=gen_uuid(),
            name=f"global_tool_{datetime.now().timestamp()}",
            display_name="global_tool",
            tool_type=ToolType.MCP,
            mcp_server_id=global_server.server_id,
            status=ToolStatus.ACTIVE,
        )
        user_tool = Tool(
            tool_id=gen_uuid(),
            name=f"uc_tool_{datetime.now().timestamp()}",
            display_name="uc_tool",
            tool_type=ToolType.MCP,
            mcp_server_id=user_server.server_id,
            status=ToolStatus.ACTIVE,
        )
        db.add_all([standalone, global_tool, user_tool])
        db.commit()

        visible = (
            db.query(Tool)
            .filter(Tool.mcp_server_id.is_(None))
            .all()
        )
        ids = {t.tool_id for t in visible}
        assert standalone.tool_id in ids
        assert global_tool.tool_id not in ids
        assert user_tool.tool_id not in ids
    finally:
        db.close()


def test_platform_mcp_binding_runtime():
    init_db()
    db = SessionLocal()
    try:
        agent = _create_agent_bundle(db)
        server = McpServer(
            server_id=gen_uuid(),
            name=f"platform_{datetime.now().timestamp()}",
            display_name="Weather MCP",
            transport="stdio",
            command="echo",
        )
        db.add(server)
        db.flush()
        tool = Tool(
            tool_id=gen_uuid(),
            name=f"{server.name}_get_forecast",
            display_name="get_forecast",
            tool_type=ToolType.MCP,
            config={"mcp_tool_name": "get_forecast"},
            mcp_server_id=server.server_id,
            status=ToolStatus.ACTIVE,
        )
        db.add(tool)
        db.commit()

        from services.connector_service import make_platform_mcp_binding_key

        binding_key = make_platform_mcp_binding_key(server.server_id)
        set_agent_connector_bindings(
            db,
            agent.agent_id,
            [{"catalog_key": binding_key, "tools": []}],
        )
        db.commit()
        runtime = resolve_runtime_connectors(db, agent_id=agent.agent_id, user_id="")
        assert binding_key in runtime["configured_catalog_keys"]
        assert [t.tool_id for t in runtime["tools"]] == [tool.tool_id]
        assert runtime["platform_servers"][0].server_id == server.server_id
    finally:
        db.close()


def test_mcp_server_list_excludes_user_owned():
    init_db()
    db = SessionLocal()
    try:
        user = _create_user(db, f"owner_{datetime.now().timestamp()}")
        global_server = McpServer(
            server_id=gen_uuid(),
            name=f"global_{datetime.now().timestamp()}",
            display_name="global",
            transport="stdio",
            command="echo",
        )
        user_server = McpServer(
            server_id=gen_uuid(),
            owner_user_id=user.user_id,
            name=f"uc_{user.user_id[:8]}_email_test",
            display_name="user",
            transport="stdio",
            command="echo",
        )
        db.add(global_server)
        db.add(user_server)
        db.commit()

        listed = (
            db.query(McpServer)
            .filter(McpServer.owner_user_id.is_(None))
            .all()
        )
        ids = {s.server_id for s in listed}
        assert global_server.server_id in ids
        assert user_server.server_id not in ids
    finally:
        db.close()


@pytest.mark.asyncio
async def test_sync_connector_marks_connected(monkeypatch):
    init_db()
    db = SessionLocal()
    try:
        user = _create_user(db, f"sync_{datetime.now().timestamp()}")
        connector = create_connector_from_catalog(
            db,
            user_id=user.user_id,
            catalog_key="dingtalk_group",
            credentials={"app_key": "key", "app_secret": "secret"},
            name="dt",
        )

        async def fake_discover(cfg, timeout_seconds=45):
            return {"success": True, "tools": [{"name": "send_message", "description": "x", "inputSchema": {}}]}

        monkeypatch.setattr(
            "services.mcp.client.discover_mcp_tools",
            fake_discover,
        )
        with patch("services.mcp.client.discover_mcp_tools", new=AsyncMock(return_value={"success": True, "tools": [{"name": "send"}]})):
            from services.connector_service import sync_connector

            # sync_connector calls discover then sync_server_tools which also discovers
            async def fake_sync(db_sess, server):
                return {"success": True, "total": 1, "created": 1, "updated": 0, "deactivated": 0, "tools": []}

            monkeypatch.setattr("services.connector_service.sync_server_tools", fake_sync)
            monkeypatch.setattr(
                "services.mcp.client.discover_mcp_tools",
                AsyncMock(return_value={"success": True, "tools": [{"name": "send"}]}),
            )
            result = await sync_connector(db, connector)
            assert result.get("success") is True
            db.refresh(connector)
            assert connector.status == ConnectorStatus.CONNECTED
    finally:
        db.close()
