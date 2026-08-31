"""Runtime deferred tool loading tests."""
from unittest.mock import MagicMock, patch

import pytest

from services.agent_service import AgentLoop
from services.tool_search.config import ToolSearchConfig
from services.tool_search.registry import SessionToolRegistry
from services.builtin_tools import BuiltinTool


@pytest.mark.asyncio
async def test_execute_tool_search_activates_tools():
    loop = object.__new__(AgentLoop)
    loop.tool_loading_cfg = ToolSearchConfig(
        enabled=True,
        mode="deferred",
        always_loaded=["tool_search"],
        max_results=3,
        max_loaded_per_session=5,
        search_backend="keyword",
    )
    loop.core_tool_names = {"tool_search"}
    session = MagicMock()
    session.pending_context = {}
    loop.session = session
    loop.db = MagicMock()
    loop.db.commit = MagicMock()
    loop._run_metrics = {}
    loop.tool_registry = SessionToolRegistry.from_session(session, max_loaded=5)
    loop.tool_catalog = MagicMock()
    from services.tool_search.catalog import ToolCatalogEntry

    loop.tool_catalog.all_names = MagicMock(return_value={"nl2sql_query", "bash"})
    loop.tool_catalog.get = MagicMock(
        side_effect=lambda n: ToolCatalogEntry(
            name=n,
            display_name=n,
            description=f"desc {n}",
            tool_type="mcp",
        )
    )

    with patch("services.agent_service.search_tools") as mock_search:
        mock_search.return_value = [
            ToolCatalogEntry(name="nl2sql_query", display_name="nl2sql", description="sql", tool_type="mcp"),
        ]
        result = await loop._execute_tool_search({"query": "sql", "activate": True})

    assert result["success"] is True
    assert "nl2sql_query" in result.get("activated", [])
    assert "nl2sql_query" in loop.tool_registry.loaded


@pytest.mark.asyncio
async def test_execute_tool_blocked_when_not_loaded():
    loop = object.__new__(AgentLoop)
    loop.tool_loading_cfg = ToolSearchConfig(enabled=True, mode="deferred")
    loop.core_tool_names = {"tool_search"}
    loop.tool_registry = SessionToolRegistry(MagicMock(pending_context={}), max_loaded=5)
    tool = BuiltinTool(name="nl2sql_query", description="", parameters={})
    result = await loop._execute_tool_with_retry(tool, {})
    assert result["success"] is False
    assert "尚未激活" in result["error"]
