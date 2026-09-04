"""Tool search service tests."""
from unittest.mock import MagicMock

from services.tool_search.catalog import ToolCatalog, ToolCatalogEntry, build_catalog_from_tools
from services.tool_search.config import (
    ToolSearchConfig,
    resolve_core_tool_names,
    resolve_tool_loading_for_agent,
)
from services.tool_search.registry import SessionToolRegistry
from services.tool_search.search import search_tools
from services.builtin_tools import BuiltinTool


def _entry(name: str, desc: str = "", tool_type: str = "mcp", is_builtin: bool = False) -> ToolCatalogEntry:
    return ToolCatalogEntry(
        name=name,
        display_name=name,
        description=desc,
        tool_type=tool_type,
        is_builtin=is_builtin,
    )


def test_search_tools_bm25_ranks_relevant():
    catalog = ToolCatalog([
        _entry("nl2sql_query", "自然语言转 SQL 查询数据库"),
        _entry("cu_act", "ScreenPilot 页面点击"),
        _entry("weather_api", "查询城市天气"),
    ])
    hits = search_tools(catalog, "SQL 数据库查询", max_results=2, backend="bm25")
    assert hits
    assert hits[0].name == "nl2sql_query"


def test_search_tools_keyword_backend():
    catalog = ToolCatalog([_entry("send_email", "发送邮件通知")])
    hits = search_tools(catalog, "邮件", max_results=3, backend="keyword")
    assert len(hits) == 1
    assert hits[0].name == "send_email"


def test_search_respects_searchable_names():
    catalog = ToolCatalog([
        _entry("allowed_tool", "可见工具"),
        _entry("hidden_tool", "隐藏工具"),
    ])
    hits = search_tools(
        catalog,
        "隐藏",
        searchable_names={"allowed_tool"},
        backend="keyword",
    )
    assert hits == []


def test_resolve_core_includes_all_builtins():
    cfg = ToolSearchConfig(enabled=True, mode="deferred", always_loaded=[])
    core = resolve_core_tool_names(
        cfg,
        memory_enabled=True,
        has_kb=True,
        available_tool_names={
            "memory",
            "kb_search",
            "execute_code",
            "tool_search",
            "read_file",
            "bash",
            "nl2sql_query",
            "cu_search_skills",
        },
        builtin_tool_names={
            "memory",
            "kb_search",
            "execute_code",
            "tool_search",
            "read_file",
            "bash",
        },
    )
    assert "tool_search" in core
    assert "execute_code" in core
    assert "read_file" in core
    assert "bash" in core
    assert "memory" in core
    assert "kb_search" in core
    assert "cu_search_skills" in core
    assert "nl2sql_query" not in core


def test_resolve_core_always_loaded_adds_user_tool():
    cfg = ToolSearchConfig(enabled=True, mode="deferred", always_loaded=["nl2sql_query"])
    core = resolve_core_tool_names(
        cfg,
        available_tool_names={"execute_code", "tool_search", "nl2sql_query"},
        builtin_tool_names={"execute_code", "tool_search"},
    )
    assert "nl2sql_query" in core
    assert "execute_code" in core


def test_resolve_tool_loading_for_agent_override():
    agent = MagicMock()
    agent.composition_config = {
        "tool_loading": {"mode": "deferred", "enabled": True},
    }
    cfg = resolve_tool_loading_for_agent(agent, ToolSearchConfig(enabled=False, mode="eager"))
    assert cfg.enabled is True
    assert cfg.mode == "deferred"


def test_session_registry_activate_respects_max():
    session = MagicMock()
    session.pending_context = {}
    reg = SessionToolRegistry(session, max_loaded=2)
    added = reg.activate(["a", "b", "c"], core_names=set())
    assert len(added) == 2
    assert reg.loaded_list() == ["a", "b"]


def test_build_catalog_from_builtin():
    bt = BuiltinTool(name="demo", description="demo tool", parameters={"type": "object", "properties": {}})
    cat = build_catalog_from_tools([bt])
    assert cat.get("demo") is not None
    assert cat.get("demo").is_builtin is True


def test_catalog_deferred_entries_excludes_builtins():
    catalog = ToolCatalog([
        _entry("read_file", "读文件", tool_type="builtin", is_builtin=True),
        _entry("nl2sql_query", "SQL", tool_type="mcp", is_builtin=False),
        _entry("tool_search", "搜索", tool_type="builtin", is_builtin=True),
    ])
    deferred = catalog.deferred_entries({"tool_search", "read_file"})
    assert [e.name for e in deferred] == ["nl2sql_query"]


def test_agent_loop_tools_active_for_llm_deferred_builtins():
    from services.agent_service import AgentLoop

    loop = object.__new__(AgentLoop)
    loop.tool_loading_cfg = ToolSearchConfig(enabled=True, mode="deferred", always_loaded=[])
    loop.core_tool_names = {"tool_search", "execute_code", "read_file", "bash"}
    loop.tool_registry = SessionToolRegistry(MagicMock(pending_context={}), max_loaded=5)
    loop.tool_registry.loaded.add("nl2sql_query")
    loop.available_tools = [
        BuiltinTool(name="tool_search", description="", parameters={}),
        BuiltinTool(name="execute_code", description="", parameters={}),
        BuiltinTool(name="read_file", description="", parameters={}),
        BuiltinTool(name="bash", description="", parameters={}),
        BuiltinTool(name="nl2sql_query", description="", parameters={}),
    ]
    active = loop._tools_active_for_llm()
    names = {t.name for t in active}
    assert names == {"tool_search", "execute_code", "read_file", "bash", "nl2sql_query"}


def test_agent_loop_deferred_tool_names_excludes_builtins():
    from services.agent_service import AgentLoop

    loop = object.__new__(AgentLoop)
    loop.core_tool_names = {"tool_search", "read_file", "execute_code"}
    loop.tool_catalog = ToolCatalog([
        _entry("read_file", is_builtin=True, tool_type="builtin"),
        _entry("execute_code", is_builtin=True, tool_type="builtin"),
        _entry("tool_search", is_builtin=True, tool_type="builtin"),
        _entry("nl2sql_query", is_builtin=False, tool_type="mcp"),
        _entry("weather_api", is_builtin=False, tool_type="mcp"),
    ])
    deferred = loop._deferred_tool_names()
    assert deferred == {"nl2sql_query", "weather_api"}


def test_agent_loop_tools_active_eager():
    from services.agent_service import AgentLoop

    loop = object.__new__(AgentLoop)
    loop.tool_loading_cfg = ToolSearchConfig(enabled=False, mode="eager")
    loop.available_tools = [
        BuiltinTool(name="a", description="", parameters={}),
        BuiltinTool(name="b", description="", parameters={}),
    ]
    assert len(loop._tools_active_for_llm()) == 2
