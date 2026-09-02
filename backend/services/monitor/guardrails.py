"""Runtime guardrails embedded in AgentLoop control points."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class GuardDecision:
    allowed: bool
    checkpoint: str
    reason: str = ""
    action: str = "allow"
    attrs: Dict[str, Any] = field(default_factory=dict)

    def to_event(self) -> Dict[str, Any]:
        return {
            "checkpoint": self.checkpoint,
            "decision": "block" if not self.allowed else "allow",
            "reason": self.reason,
            "action": self.action,
            **self.attrs,
        }


MAX_TOOL_RESULT_CHARS = 12000
DANGEROUS_TOOLS = {"bash", "execute_code", "write_query"}


def check_before_tool(
    tool_name: str,
    tool_args: Dict[str, Any],
    *,
    allowed_tool_names: Optional[set] = None,
    require_approval_tools: Optional[set] = None,
) -> GuardDecision:
    name = (tool_name or "").strip()
    if allowed_tool_names is not None and name and name not in allowed_tool_names:
        return GuardDecision(
            allowed=False,
            checkpoint="before_tool",
            reason=f"Tool [{name}] not in agent allowlist",
            action="block",
            attrs={"tool_name": name},
        )
    if require_approval_tools and name in require_approval_tools:
        return GuardDecision(
            allowed=True,
            checkpoint="before_tool",
            reason=f"Tool [{name}] requires HITL",
            action="require_hitl",
            attrs={"tool_name": name},
        )
    return GuardDecision(allowed=True, checkpoint="before_tool", attrs={"tool_name": name})


def truncate_tool_result(result: Any) -> Any:
    if result is None:
        return result
    try:
        text = json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result
    except (TypeError, ValueError):
        text = str(result)
    if len(text) <= MAX_TOOL_RESULT_CHARS:
        return result
    if isinstance(result, dict):
        return {**result, "_truncated": True, "preview": text[:MAX_TOOL_RESULT_CHARS]}
    return text[:MAX_TOOL_RESULT_CHARS] + "…[truncated]"


def check_before_reply(
    content: str,
    *,
    execution_mode: str = "",
    connector_tool_names: Optional[List[str]] = None,
    tools_called: Optional[List[str]] = None,
) -> GuardDecision:
    text = (content or "").strip()
    if not text:
        return GuardDecision(
            allowed=False,
            checkpoint="before_reply",
            reason="Empty assistant reply",
            action="block",
        )
    lowered = text.lower()
    email_claims = ("已读邮件", "邮件内容", "inbox", "mailbox")
    if connector_tool_names and any(k in text for k in email_claims):
        called = set(tools_called or [])
        if not called.intersection(set(connector_tool_names)):
            return GuardDecision(
                allowed=True,
                checkpoint="before_reply",
                reason="Email claim without connector tool call (warn)",
                action="warn",
                attrs={"tools_called": list(called)},
            )
    if "connection timed out" in lowered or "connecttimeout" in lowered:
        return GuardDecision(
            allowed=True,
            checkpoint="before_reply",
            reason="Connect timeout surfaced in reply",
            action="warn",
        )
    return GuardDecision(allowed=True, checkpoint="before_reply")
