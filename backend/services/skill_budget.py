"""Skill manifest tool budget resolution."""
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class SkillBudget:
    max_web_search: int = 5
    max_tavily_per_iter: int = 2
    max_tool_rounds: int = 3
    min_timeout_seconds: int = 180


DEFAULT_SKILL_BUDGET = SkillBudget()


def resolve_skill_budget(skill: Any) -> SkillBudget:
    """Read tool_budget from SkillPack.manifest with class-level fallbacks."""
    if skill is None:
        return DEFAULT_SKILL_BUDGET
    manifest = getattr(skill, "manifest", None) or {}
    if not isinstance(manifest, dict):
        return DEFAULT_SKILL_BUDGET
    raw = manifest.get("tool_budget") or {}
    if not isinstance(raw, dict):
        return DEFAULT_SKILL_BUDGET

    def _int(key: str, default: int) -> int:
        val = raw.get(key)
        if val is None:
            return default
        try:
            return max(1, int(val))
        except (TypeError, ValueError):
            return default

    return SkillBudget(
        max_web_search=_int("max_web_search", DEFAULT_SKILL_BUDGET.max_web_search),
        max_tavily_per_iter=_int("max_tavily_per_iter", DEFAULT_SKILL_BUDGET.max_tavily_per_iter),
        max_tool_rounds=_int("max_tool_rounds", DEFAULT_SKILL_BUDGET.max_tool_rounds),
        min_timeout_seconds=_int("min_timeout_seconds", DEFAULT_SKILL_BUDGET.min_timeout_seconds),
    )


def get_execution_hints(skill: Any) -> Optional[str]:
    if skill is None:
        return None
    manifest = getattr(skill, "manifest", None) or {}
    if not isinstance(manifest, dict):
        return None
    hints = manifest.get("execution_hints")
    if hints is None:
        return None
    text = str(hints).strip()
    return text or None
