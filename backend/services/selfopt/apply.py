"""Apply AgentVersion snapshot onto an Agent instance for a single chat turn (in-memory)."""
from __future__ import annotations

from typing import Any, Dict, Optional

from models import Agent, AgentVersion


_SNAPSHOT_FIELDS = (
    "system_prompt",
    "model_service_id",
    "max_iterations",
    "step_timeout_seconds",
    "timeout_seconds",
    "tool_retry_count",
    "tool_retry_backoff",
    "allow_repeat_tool_calls",
    "max_repeat_threshold",
    "single_call_token_limit",
    "composition_config",
    "workflow_definition",
    "tool_permissions",
    "token_budget",
    "autonomy_level",
)


def apply_version_snapshot_in_memory(agent: Agent, version: Optional[AgentVersion]) -> Agent:
    """Mutate agent attributes from snapshot without committing. Safe for A/B treatment."""
    if not version or not isinstance(version.snapshot, dict):
        return agent
    snap: Dict[str, Any] = version.snapshot
    for field in _SNAPSHOT_FIELDS:
        if field in snap and snap[field] is not None:
            setattr(agent, field, snap[field])
    return agent
