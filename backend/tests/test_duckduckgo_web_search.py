"""DuckDuckGo web search + provider filtering."""
from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_execute_duckduckgo_search_success():
    from services.builtin_tools import _execute_duckduckgo_search

    fake_rows = [
        {
            "title": "示例标题",
            "href": "https://example.com/a",
            "body": "摘要内容一二三",
        }
    ]

    with patch(
        "services.builtin_tools._ddg_collect_search_results",
        return_value=fake_rows,
    ):
        result = await _execute_duckduckgo_search({"query": "测试", "max_results": 3})

    assert result["success"] is True
    assert "## 搜索结果" in result["result"]
    assert "示例标题" in result["result"]
    assert "https://example.com/a" in result["result"]
    assert "摘要内容" in result["result"]


@pytest.mark.asyncio
async def test_execute_duckduckgo_search_fallback_to_httpx():
    from services.builtin_tools import _ddg_collect_search_results

    fake_rows = [{"title": "HTML 结果", "href": "https://example.com/html", "body": "ok"}]

    def _fake_collect(query, region, timelimit, max_results, log_fn=None):
        if log_fn:
            log_fn("H1", "test", "library fail", {"strategy": "library"})
        return fake_rows

    with patch(
        "services.builtin_tools._ddg_search_via_library",
        side_effect=RuntimeError("library blocked"),
    ), patch(
        "services.builtin_tools._ddg_search_via_httpx_html",
        return_value=fake_rows,
    ):
        rows = _ddg_collect_search_results("测试", "wt-wt", None, 3)

    assert rows == fake_rows


def test_parse_ddg_html_page_extracts_results():
    from services.builtin_tools import _parse_ddg_html_page

    html = """
    <a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com">示例标题</a>
    <a class="result__snippet">这是摘要</a>
    """
    rows = _parse_ddg_html_page(html, 5)
    assert len(rows) == 1
    assert rows[0]["title"] == "示例标题"
    assert rows[0]["href"] == "https://example.com"
    assert "摘要" in rows[0]["body"]


@pytest.mark.asyncio
async def test_execute_duckduckgo_search_missing_query():
    from services.builtin_tools import _execute_duckduckgo_search

    result = await _execute_duckduckgo_search({})
    assert result["success"] is False
    assert "query" in result["error"]


@pytest.mark.asyncio
async def test_execute_duckduckgo_search_failure():
    from services.builtin_tools import _execute_duckduckgo_search

    with patch(
        "services.builtin_tools._ddg_collect_search_results",
        side_effect=RuntimeError("network down"),
    ):
        result = await _execute_duckduckgo_search({"query": "x"})

    assert result["success"] is False
    assert "DuckDuckGo" in result["error"]


def test_get_builtin_tools_for_runtime_filters_tavily():
    from services.builtin_tools import (
        WEB_SEARCH_TOOL_NAMES,
        get_builtin_tools_for_runtime,
    )

    with patch(
        "services.builtin_tools.get_web_search_provider", return_value="tavily"
    ):
        names = {t.name for t in get_builtin_tools_for_runtime()}
    assert "tavily_web_search" in names
    assert "duckduckgo_web_search" not in names
    assert "web_extract" in names
    assert names & WEB_SEARCH_TOOL_NAMES == {"tavily_web_search"}


def test_get_builtin_tools_for_runtime_filters_duckduckgo():
    from services.builtin_tools import (
        WEB_SEARCH_TOOL_NAMES,
        get_builtin_tools_for_runtime,
    )

    with patch(
        "services.builtin_tools.get_web_search_provider", return_value="duckduckgo"
    ):
        names = {t.name for t in get_builtin_tools_for_runtime()}
    assert "duckduckgo_web_search" in names
    assert "tavily_web_search" not in names
    assert "web_extract" in names
    assert names & WEB_SEARCH_TOOL_NAMES == {"duckduckgo_web_search"}


def test_check_web_tool_allowed_per_iter_for_ddg():
    from services.agent_service import AgentLoop
    from services.skill_budget import resolve_skill_budget

    class _Skill:
        manifest = {"tool_budget": {"max_web_search": 5, "max_tavily_per_iter": 1}}

    loop = object.__new__(AgentLoop)
    loop.active_skill_name = "demo"
    loop._web_search_calls = 0
    loop.skill_budget = resolve_skill_budget(_Skill())

    assert AgentLoop._check_web_tool_allowed(loop, "duckduckgo_web_search", 0) is None
    msg = AgentLoop._check_web_tool_allowed(loop, "duckduckgo_web_search", 1)
    assert msg is not None
    assert "本轮搜索" in msg
