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


def _emit_guardrail_span(decision: GuardDecision) -> None:
    try:
        from services.monitor.oi_tracing import mark_span_ok, oi_span, set_span_attrs
        from services.monitor.openinference_attrs import attrs_for_guardrail

        ev = decision.to_event()
        with oi_span(
            f"guard.{decision.checkpoint or 'unknown'}",
            attrs_for_guardrail(
                checkpoint=decision.checkpoint,
                decision=ev.get("decision", ""),
                reason=decision.reason,
                action=decision.action,
                extra=decision.attrs,
            ),
        ) as span:
            set_span_attrs(
                span,
                attrs_for_guardrail(
                    checkpoint=decision.checkpoint,
                    decision=ev.get("decision", ""),
                    reason=decision.reason,
                    action=decision.action,
                    extra=decision.attrs,
                ),
            )
            mark_span_ok(span)
    except Exception:
        pass


def check_before_tool(
    tool_name: str,
    tool_args: Dict[str, Any],
    *,
    allowed_tool_names: Optional[set] = None,
    require_approval_tools: Optional[set] = None,
) -> GuardDecision:
    name = (tool_name or "").strip()
    if allowed_tool_names is not None and name and name not in allowed_tool_names:
        decision = GuardDecision(
            allowed=False,
            checkpoint="before_tool",
            reason=f"Tool [{name}] not in agent allowlist",
            action="block",
            attrs={"tool_name": name},
        )
        _emit_guardrail_span(decision)
        return decision
    if require_approval_tools and name in require_approval_tools:
        decision = GuardDecision(
            allowed=True,
            checkpoint="before_tool",
            reason=f"Tool [{name}] requires HITL",
            action="require_hitl",
            attrs={"tool_name": name},
        )
        _emit_guardrail_span(decision)
        return decision
    decision = GuardDecision(allowed=True, checkpoint="before_tool", attrs={"tool_name": name})
    _emit_guardrail_span(decision)
    return decision


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
        decision = GuardDecision(
            allowed=False,
            checkpoint="before_reply",
            reason="Empty assistant reply",
            action="block",
        )
        _emit_guardrail_span(decision)
        return decision
    lowered = text.lower()
    email_claims = ("已读邮件", "邮件内容", "inbox", "mailbox")
    if connector_tool_names and any(k in text for k in email_claims):
        called = set(tools_called or [])
        if not called.intersection(set(connector_tool_names)):
            decision = GuardDecision(
                allowed=True,
                checkpoint="before_reply",
                reason="Email claim without connector tool call (warn)",
                action="warn",
                attrs={"tools_called": list(called)},
            )
            _emit_guardrail_span(decision)
            return decision
    if "connection timed out" in lowered or "connecttimeout" in lowered:
        decision = GuardDecision(
            allowed=True,
            checkpoint="before_reply",
            reason="Connect timeout surfaced in reply",
            action="warn",
        )
        _emit_guardrail_span(decision)
        return decision
    decision = GuardDecision(allowed=True, checkpoint="before_reply")
    _emit_guardrail_span(decision)
    return decision
