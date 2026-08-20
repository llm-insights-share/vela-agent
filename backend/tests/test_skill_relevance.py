"""Tests for skill relevance scoring and budget resolution."""
from types import SimpleNamespace

from services.agent_service import _compute_skill_relevance, AgentLoop
from services.skill_budget import resolve_skill_budget, DEFAULT_SKILL_BUDGET


def _skill(**kwargs):
    defaults = {
        "name": "test-skill",
        "description": "",
        "skill_content": "",
        "tools": [],
        "manifest": {},
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_relevance_from_skill_content_when_description_empty():
    skill = _skill(
        description="",
        skill_content="为用户生成一份沪市奥比中光今日开盘走势报告，包含开盘价对比。",
    )
    message = "请生成奥比中光688322今日开盘走势报告"
    score = _compute_skill_relevance(message, skill)
    assert score > 0.15


def test_relevance_trigger_keywords_exact_match():
    skill = _skill(
        manifest={"trigger_keywords": ["开盘走势", "688322"]},
    )
    message = "现在是上午9:25，请生成开盘走势报告"
    assert _compute_skill_relevance(message, skill) == 1.0


def test_relevance_quoted_phrase_in_skill_content():
    skill = _skill(
        description="",
        skill_content='当用户提到「开盘走势」时，优先抓取实时行情。',
    )
    message = "请输出今日开盘走势分析"
    assert _compute_skill_relevance(message, skill) == 1.0


def test_resolve_skill_budget_uses_manifest():
    skill = _skill(
        manifest={
            "tool_budget": {
                "max_web_search": 3,
                "max_tavily_per_iter": 1,
                "max_tool_rounds": 2,
                "min_timeout_seconds": 240,
            }
        }
    )
    budget = resolve_skill_budget(skill)
    assert budget.max_web_search == 3
    assert budget.max_tavily_per_iter == 1
    assert budget.max_tool_rounds == 2
    assert budget.min_timeout_seconds == 240


def test_resolve_skill_budget_fallback():
    budget = resolve_skill_budget(_skill())
    assert budget == DEFAULT_SKILL_BUDGET


def test_check_web_tool_allowed_respects_budget():
    loop = object.__new__(AgentLoop)
    loop.active_skill_name = "demo"
    loop._web_search_calls = 5
    loop.skill_budget = resolve_skill_budget(
        _skill(manifest={"tool_budget": {"max_web_search": 5}})
    )
    msg = AgentLoop._check_web_tool_allowed(loop, "tavily_web_search", 0)
    assert msg is not None
    assert "搜索上限" in msg
