"""Built-in / platform agents that must not be deleted or deprecated."""
from __future__ import annotations

from typing import Any, Optional

OPS_AGENT_NAME = "vela-ops-assistant"

PROTECTED_AGENT_NAMES = frozenset({OPS_AGENT_NAME})


def is_protected_agent_name(name: Optional[str]) -> bool:
    return bool(name) and name in PROTECTED_AGENT_NAMES


def assert_agent_mutable(agent: Any, *, action: str = "修改") -> None:
    """Raise ValueError if agent is a protected platform agent."""
    if agent is not None and is_protected_agent_name(getattr(agent, "name", None)):
        raise ValueError(f"内置智能体 {OPS_AGENT_NAME} 不可{action}")
