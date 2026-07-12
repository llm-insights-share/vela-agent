"""Select concrete rewrite method from judge signals."""
from __future__ import annotations

from services.query_rewrite.types import DialogueContext, RewriteDecision


def select_method(decision: RewriteDecision, query: str, ctx: DialogueContext) -> str:
    if decision.tier == 0:
        return "pass_through"

    signals = decision.signals or {}

    if decision.tier == 1:
        if signals.get("has_reference") or signals.get("is_elliptical") or signals.get("shares_entity"):
            return "CR"
        if signals.get("colloquial") or signals.get("short_no_entity"):
            return "EX"
        return "CR"

    # Tier 2
    if signals.get("followup_memory") and ctx.memory_enabled:
        return "MR"
    if signals.get("followup_memory") and not ctx.memory_enabled:
        # Still try MR-style clarification via LLM without memory probe hard-fail
        return "MR"
    if signals.get("multi_hop"):
        return "MH"
    return "HD"
