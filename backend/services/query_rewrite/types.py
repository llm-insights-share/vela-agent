"""Query rewrite engine data types."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class DialogueContext:
    """Dialogue state available to the judge / rewriters."""

    turn_index: int = 0
    recent_messages: List[Dict[str, Any]] = field(default_factory=list)
    entity_slots: List[str] = field(default_factory=list)
    last_user_text: str = ""
    last_assistant_text: str = ""
    context_summary: str = ""
    agent_id: str = ""
    user_id: str = ""
    memory_enabled: bool = False
    kb_ids: List[str] = field(default_factory=list)
    topic_tags: List[str] = field(default_factory=list)
    time_hint: str = ""


@dataclass
class RewriteDecision:
    tier: int  # 0 / 1 / 2
    action: str  # pass_through | rule_based_rewrite | llm_rewrite
    score: float = 0.0
    rule_score: float = 0.0
    coherence_gap: float = 0.0
    probe_penalty: float = 0.0
    signals: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RewriteResult:
    original: str
    rewritten: str
    tier: int = 0
    method: str = "pass_through"  # pass_through | CR | EX | HD | MH | MR
    score: float = 0.0
    confidence: float = 1.0
    sub_queries: Optional[List[Dict[str, Any]]] = None
    fallback_reason: Optional[str] = None
    need_clarification: bool = False
    clarification: Optional[str] = None
    latency_ms: float = 0.0
    decision: Optional[Dict[str, Any]] = None
    tokens_used: int = 0

    @property
    def query_for_downstream(self) -> str:
        if self.need_clarification and self.clarification:
            return self.original
        return self.rewritten or self.original

    def to_dict(self) -> Dict[str, Any]:
        return {
            "original": self.original,
            "rewritten": self.rewritten,
            "query_for_downstream": self.query_for_downstream,
            "tier": self.tier,
            "method": self.method,
            "score": self.score,
            "confidence": self.confidence,
            "sub_queries": self.sub_queries,
            "fallback_reason": self.fallback_reason,
            "need_clarification": self.need_clarification,
            "clarification": self.clarification,
            "latency_ms": round(self.latency_ms, 2),
            "decision": self.decision,
            "tokens_used": self.tokens_used,
        }

    def summary_line(self) -> str:
        if self.tier == 0 and self.method == "pass_through":
            return f"[QueryRewrite] T0 透传 (score={self.score:.2f}, {self.latency_ms:.0f}ms)"
        parts = [
            f"[QueryRewrite] T{self.tier}/{self.method}",
            f"score={self.score:.2f}",
            f"{self.latency_ms:.0f}ms",
        ]
        if self.fallback_reason:
            parts.append(f"fallback={self.fallback_reason}")
        if self.need_clarification:
            parts.append("NEED_CLARIFICATION")
        elif self.rewritten and self.rewritten != self.original:
            preview = self.rewritten[:80].replace("\n", " ")
            parts.append(f"→ {preview}")
        return " ".join(parts)
