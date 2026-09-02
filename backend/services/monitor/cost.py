"""Token cost estimation from model pricing table."""

from __future__ import annotations

from typing import Any, Dict, Optional

# USD per 1M tokens (input, output) — lightweight defaults
DEFAULT_PRICING: Dict[str, tuple[float, float]] = {
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.6),
    "gpt-4": (30.0, 60.0),
    "gpt-3.5-turbo": (0.5, 1.5),
    "claude-3-5-sonnet": (3.0, 15.0),
    "claude-3-haiku": (0.25, 1.25),
    "default": (1.0, 3.0),
}


def _match_pricing(model_name: str) -> tuple[float, float]:
    name = (model_name or "").lower()
    for key, pricing in DEFAULT_PRICING.items():
        if key != "default" and key in name:
            return pricing
    return DEFAULT_PRICING["default"]


def estimate_cost_usd(
    *,
    token_in: int = 0,
    token_out: int = 0,
    model_name: str = "",
) -> float:
    in_price, out_price = _match_pricing(model_name)
    return round((token_in * in_price + token_out * out_price) / 1_000_000, 6)


def aggregate_run_cost(runs: list, *, model_name: str = "") -> Dict[str, Any]:
    total_in = sum((r.token_in or 0) for r in runs)
    total_out = sum((r.token_out or 0) for r in runs)
    cost = estimate_cost_usd(token_in=total_in, token_out=total_out, model_name=model_name)
    return {
        "total_tokens": total_in + total_out,
        "token_in": total_in,
        "token_out": total_out,
        "estimated_cost_usd": cost,
    }
