"""QueryRewriteEngine: judge → method → execute with safe fallbacks."""
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from services.query_rewrite.judge import build_dialogue_context, lightweight_judge
from services.query_rewrite.method_router import select_method
from services.query_rewrite.rule_rewriter import rule_rewrite
from services.query_rewrite.types import DialogueContext, RewriteResult

# Semantic drift guard: reject rewrite if similarity below this
DRIFT_SIM_THRESHOLD = 0.35
T2_TIMEOUT_SECONDS = 25.0
MIN_ACCEPT_CONFIDENCE = 0.45


class QueryRewriteEngine:
    def __init__(
        self,
        db: Session,
        provider=None,
        model_svc=None,
        *,
        t2_timeout_seconds: float = T2_TIMEOUT_SECONDS,
    ):
        self.db = db
        self.provider = provider
        self.model_svc = model_svc
        self.t2_timeout_seconds = t2_timeout_seconds

    async def rewrite(
        self,
        query: str,
        ctx: Optional[DialogueContext] = None,
        *,
        messages: Optional[List[Dict[str, Any]]] = None,
        agent_id: str = "",
        user_id: str = "",
        memory_enabled: bool = False,
        kb_ids: Optional[List[str]] = None,
    ) -> RewriteResult:
        started = time.perf_counter()
        original = (query or "").strip()
        if not original:
            return RewriteResult(
                original=query or "",
                rewritten=query or "",
                tier=0,
                method="pass_through",
                latency_ms=(time.perf_counter() - started) * 1000,
            )

        if ctx is None:
            ctx = build_dialogue_context(
                messages,
                agent_id=agent_id,
                user_id=user_id,
                memory_enabled=memory_enabled,
                kb_ids=kb_ids,
            )

        decision = lightweight_judge(original, ctx)
        method = select_method(decision, original, ctx)

        if decision.tier == 0 or method == "pass_through":
            return RewriteResult(
                original=original,
                rewritten=original,
                tier=0,
                method="pass_through",
                score=decision.score,
                confidence=1.0,
                latency_ms=(time.perf_counter() - started) * 1000,
                decision=decision.to_dict(),
            )

        result: Optional[RewriteResult] = None
        try:
            if decision.tier == 1:
                result = self._run_t1(original, ctx, method, decision)
            else:
                result = await self._run_t2(original, ctx, method, decision)
        except Exception as exc:
            # T2/T1 hard failure → degrade
            result = self._degrade(original, ctx, decision, method, reason=f"exception:{exc}")

        assert result is not None

        # Low confidence → fallback to original (keep candidate in rewritten field for offline)
        if (
            not result.need_clarification
            and result.method != "pass_through"
            and result.confidence < MIN_ACCEPT_CONFIDENCE
            and result.rewritten != original
        ):
            result.fallback_reason = result.fallback_reason or "low_confidence"
            result.rewritten = original
            result.confidence = 0.0

        # Semantic drift check (skip for HyDE which intentionally expands)
        if (
            result.method not in ("pass_through", "HD")
            and not result.need_clarification
            and result.rewritten
            and result.rewritten != original
            and not result.fallback_reason
        ):
            if not self._passes_drift_check(original, result.rewritten):
                result.fallback_reason = "semantic_drift"
                result.rewritten = original
                result.confidence = 0.0

        result.latency_ms = (time.perf_counter() - started) * 1000
        result.decision = decision.to_dict()
        result.score = decision.score
        return result

    def _run_t1(
        self,
        original: str,
        ctx: DialogueContext,
        method: str,
        decision,
    ) -> RewriteResult:
        rewritten, conf, used = rule_rewrite(original, ctx, method)
        if conf <= 0 or rewritten == original:
            return RewriteResult(
                original=original,
                rewritten=original,
                tier=1,
                method=used,
                score=decision.score,
                confidence=0.0,
                fallback_reason="t1_no_change",
            )
        return RewriteResult(
            original=original,
            rewritten=rewritten,
            tier=1,
            method=used,
            score=decision.score,
            confidence=conf,
        )

    async def _run_t2(
        self,
        original: str,
        ctx: DialogueContext,
        method: str,
        decision,
    ) -> RewriteResult:
        if not self.provider or not self.model_svc:
            return self._degrade(original, ctx, decision, method, reason="no_llm")

        from services.query_rewrite import llm_rewriter as lr

        try:
            if method == "HD":
                rewritten, conf, tokens = await asyncio.wait_for(
                    lr.rewrite_hyde(
                        original, ctx, self.provider, self.model_svc,
                        timeout_seconds=self.t2_timeout_seconds,
                    ),
                    timeout=self.t2_timeout_seconds + 5,
                )
                return RewriteResult(
                    original=original,
                    rewritten=rewritten,
                    tier=2,
                    method="HD",
                    score=decision.score,
                    confidence=conf,
                    tokens_used=tokens,
                )

            if method == "MH":
                rewritten, conf, tokens, steps = await asyncio.wait_for(
                    lr.rewrite_multi_hop(
                        original, ctx, self.provider, self.model_svc,
                        timeout_seconds=self.t2_timeout_seconds,
                    ),
                    timeout=self.t2_timeout_seconds + 5,
                )
                return RewriteResult(
                    original=original,
                    rewritten=rewritten,
                    tier=2,
                    method="MH",
                    score=decision.score,
                    confidence=conf,
                    sub_queries=steps,
                    tokens_used=tokens,
                    fallback_reason=None if conf > 0 else "mh_parse_failed",
                )

            # MR
            rewritten, conf, tokens, need_clar, clar = await asyncio.wait_for(
                lr.rewrite_memory_anchor(
                    original, ctx, self.provider, self.model_svc, self.db,
                    timeout_seconds=self.t2_timeout_seconds,
                ),
                timeout=self.t2_timeout_seconds + 5,
            )
            return RewriteResult(
                original=original,
                rewritten=rewritten if not need_clar else original,
                tier=2,
                method="MR",
                score=decision.score,
                confidence=conf,
                need_clarification=need_clar,
                clarification=clar,
                tokens_used=tokens,
            )
        except asyncio.TimeoutError:
            return self._degrade(original, ctx, decision, method, reason="t2_timeout")
        except Exception as exc:
            return self._degrade(original, ctx, decision, method, reason=f"t2_error:{exc}")

    def _degrade(
        self,
        original: str,
        ctx: DialogueContext,
        decision,
        method: str,
        reason: str,
    ) -> RewriteResult:
        """Prefer T1 rule rewrite; else pass-through."""
        rewritten, conf, used = rule_rewrite(original, ctx, "CR")
        if conf > 0 and rewritten != original:
            return RewriteResult(
                original=original,
                rewritten=rewritten,
                tier=1,
                method=used,
                score=decision.score,
                confidence=conf,
                fallback_reason=reason,
            )
        return RewriteResult(
            original=original,
            rewritten=original,
            tier=0,
            method="pass_through",
            score=decision.score,
            confidence=0.0,
            fallback_reason=reason,
        )

    @staticmethod
    def _passes_drift_check(original: str, rewritten: str) -> bool:
        try:
            from services.knowledge_service import _create_embedding_model
            import numpy as np

            model = _create_embedding_model()
            vecs = model.encode([original, rewritten[:500]], normalize_embeddings=True)
            a = np.asarray(vecs[0], dtype="float32").reshape(-1)
            b = np.asarray(vecs[1], dtype="float32").reshape(-1)
            denom = float(np.linalg.norm(a) * np.linalg.norm(b))
            if denom <= 1e-9:
                return True
            sim = float(np.dot(a, b) / denom)
            return sim >= DRIFT_SIM_THRESHOLD
        except Exception:
            return True
