"""LLM-as-a-Judge with configurable sampling."""

from __future__ import annotations

import random
import re
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from models import AgentRun, AgentScore, EvalJudgeEvaluator, ModelService, gen_uuid, now_utc


DEFAULT_JUDGE_PROMPT = """You are an evaluation judge. Score the assistant reply from 0.0 to 1.0.
User input: {input_text}
Assistant reply: {reply}
Rubric: {rubric}
Respond with ONLY a decimal number between 0 and 1."""


def _parse_score(text: str) -> Optional[float]:
    match = re.search(r"(0\.\d+|1\.0|1|0)", (text or "").strip())
    if not match:
        return None
    val = float(match.group(1))
    return max(0.0, min(1.0, val))


async def maybe_run_judge(
    db: Session,
    *,
    run: AgentRun,
    input_text: str = "",
) -> Optional[AgentScore]:
    """Sample and run LLM judge evaluators for a completed run."""
    evaluators: List[EvalJudgeEvaluator] = (
        db.query(EvalJudgeEvaluator)
        .filter(EvalJudgeEvaluator.enabled.is_(True))
        .all()
    )
    if not evaluators:
        return None

    applicable = [
        ev
        for ev in evaluators
        if not ev.agent_id or ev.agent_id == run.agent_id
    ]
    if not applicable:
        return None

    ev = applicable[0]
    if random.random() > float(ev.sample_rate or 0.1):
        return None

    existing = (
        db.query(AgentScore)
        .filter(AgentScore.run_id == run.run_id, AgentScore.score_name == "llm_judge")
        .first()
    )
    if existing:
        return existing

    model_svc = None
    if ev.model_service_id:
        model_svc = (
            db.query(ModelService)
            .filter(ModelService.model_service_id == ev.model_service_id)
            .first()
        )
    if not model_svc:
        from models import Agent

        agent = db.query(Agent).filter(Agent.agent_id == run.agent_id).first()
        if agent:
            model_svc = (
                db.query(ModelService)
                .filter(ModelService.model_service_id == agent.model_service_id)
                .first()
            )
    if not model_svc:
        return None

    from models import ModelProvider
    from services.model_provider import ModelProviderService

    provider = (
        db.query(ModelProvider)
        .filter(ModelProvider.provider_id == model_svc.provider_id)
        .first()
    )
    if not provider:
        return None

    template = ev.prompt_template or DEFAULT_JUDGE_PROMPT
    prompt = template.format(
        input_text=input_text or run.summary or "",
        reply=run.summary or "",
        rubric="Quality, accuracy, helpfulness",
    )
    try:
        resp = await ModelProviderService.chat_completion(
            provider,
            model_svc.model_name,
            [{"role": "user", "content": prompt}],
            max_tokens=32,
            temperature=0.0,
            source="eval_judge",
        )
        content = (resp.get("choices") or [{}])[0].get("message", {}).get("content", "")
        if not content:
            content = resp.get("content") or ""
        score_val = _parse_score(content)
        if score_val is None:
            return None
    except Exception:
        return None

    row = AgentScore(
        score_id=gen_uuid(),
        run_id=run.run_id,
        score_name="llm_judge",
        value=score_val,
        data_type="NUMERIC",
        source="judge",
        comment=f"evaluator={ev.name}",
    )
    db.add(row)
    db.commit()
    return row


def serialize_judge_evaluator(ev: EvalJudgeEvaluator) -> Dict[str, Any]:
    return {
        "evaluator_id": ev.evaluator_id,
        "name": ev.name,
        "agent_id": ev.agent_id,
        "enabled": ev.enabled,
        "sample_rate": ev.sample_rate,
        "prompt_template": ev.prompt_template,
        "model_service_id": ev.model_service_id,
        "created_at": ev.created_at.isoformat() if ev.created_at else None,
    }
