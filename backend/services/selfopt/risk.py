"""Risk tier mapping and hard deny for forbidden change kinds."""
from __future__ import annotations

from typing import Any, Dict, FrozenSet

TIER_T0 = "T0"
TIER_T1 = "T1"
TIER_T2 = "T2"
TIER_T3 = "T3"
TIER_FORBIDDEN = "FORBIDDEN"

CHANGE_KIND_TIERS: Dict[str, str] = {
    "retrieval_params": TIER_T0,
    "prompt_fewshot": TIER_T1,
    "tool_routing": TIER_T2,
    "skill_distill": TIER_T2,
    "guardrail": TIER_FORBIDDEN,
    "audit": TIER_FORBIDDEN,
    "observability": TIER_FORBIDDEN,
    "auth": TIER_FORBIDDEN,
}

FORBIDDEN_DIFF_KEYS: FrozenSet[str] = frozenset(
    {
        "guardrail",
        "guardrails",
        "audit",
        "observability",
        "auth",
        "trace",
        "otel",
    }
)


def classify_risk_tier(change_kind: str) -> str:
    return CHANGE_KIND_TIERS.get(str(change_kind or "").strip(), TIER_T2)


def is_forbidden_change_kind(change_kind: str) -> bool:
    return classify_risk_tier(change_kind) == TIER_FORBIDDEN


def validate_diff_json(diff_json: Any) -> None:
    """Raise ValueError if diff touches forbidden keys."""
    if not isinstance(diff_json, dict):
        raise ValueError("diff_json 必须为对象")
    for key in diff_json.keys():
        k = str(key).strip().lower()
        if k in FORBIDDEN_DIFF_KEYS or k.startswith("guardrail") or k.startswith("audit"):
            raise ValueError(f"禁止自优化字段: {key}")
    # Nested deny markers
    for nested in ("patch", "changes", "fields"):
        sub = diff_json.get(nested)
        if isinstance(sub, dict):
            for key in sub.keys():
                k = str(key).strip().lower()
                if k in FORBIDDEN_DIFF_KEYS:
                    raise ValueError(f"禁止自优化字段: {key}")
