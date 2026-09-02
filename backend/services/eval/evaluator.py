"""Rule-based evaluators + eval job runner."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from models import (
    Agent,
    AgentRun,
    AgentSpan,
    EvalCase,
    EvalDataset,
    EvalJob,
    EvalJobResult,
    EvalJobStatus,
    EvalRuleEvaluator,
    Session as SessionModel,
    SessionStatus,
    gen_uuid,
    now_utc,
)

DEFAULT_RULES = {
    "expected_tools": [],
    "expected_keywords": [],
    "forbidden_patterns": ["虚构", "placeholder", "TODO:"],
    "max_duration_ms": 120000,
    "pass_threshold": 0.8,
    "match_expected_output": True,
}


def _merge_rules(case: EvalCase, evaluator: Optional[EvalRuleEvaluator]) -> Dict[str, Any]:
    rules = dict(DEFAULT_RULES)
    if evaluator and evaluator.rules_json:
        rules.update(evaluator.rules_json)
    if case.expected_tools:
        rules["expected_tools"] = list(case.expected_tools)
    if case.expected_keywords:
        rules["expected_keywords"] = list(case.expected_keywords)
    return rules


def evaluate_case_rules(
    case: EvalCase,
    *,
    run: Optional[AgentRun] = None,
    reply: str = "",
    tools_called: Optional[List[str]] = None,
    elapsed_ms: int = 0,
    rules: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Evaluate a single case against rules (no LLM judge)."""
    cfg = rules or _merge_rules(case, None)
    scores: Dict[str, float] = {}
    details: List[str] = []
    passed = True
    tools_called = tools_called or []

    expected_tools = list(cfg.get("expected_tools") or [])
    if expected_tools:
        hit = all(t in tools_called for t in expected_tools)
        scores["tool_selection"] = 1.0 if hit else 0.0
        if not hit:
            passed = False
            details.append(f"Missing tools: expected {expected_tools}, got {tools_called}")

    for kw in cfg.get("expected_keywords") or []:
        if kw and kw not in (reply or ""):
            scores.setdefault("keywords", 0.0)
            passed = False
            details.append(f"Missing keyword: {kw}")
        else:
            scores.setdefault("keywords", 1.0)

    expected_output = (case.expected_output or "").strip()
    if expected_output and cfg.get("match_expected_output", True):
        norm_reply = (reply or "").strip()
        hit = expected_output in norm_reply or norm_reply == expected_output
        scores["expected_output"] = 1.0 if hit else 0.0
        if not hit:
            passed = False
            details.append("Reply does not match expected_output")

    max_dur = int(cfg.get("max_duration_ms") or 120000)
    if elapsed_ms and elapsed_ms > max_dur:
        scores["duration"] = 0.0
        passed = False
        details.append(f"Duration {elapsed_ms}ms exceeds {max_dur}ms")

    for bad in cfg.get("forbidden_patterns") or []:
        if bad in (reply or ""):
            scores["forbidden"] = 0.0
            passed = False
            details.append(f"Forbidden pattern: {bad}")

    if run and run.status != "SUCCESS":
        scores["run_status"] = 0.0
        passed = False
        details.append(f"Run status: {run.status}")

    if not scores:
        scores["overall"] = 1.0 if passed else 0.0
    else:
        scores["overall"] = sum(scores.values()) / len(scores)

    threshold = float(cfg.get("pass_threshold") or 0.8)
    return {
        "passed": passed and scores.get("overall", 0) >= threshold,
        "scores": scores,
        "details": details,
    }


def _tools_from_run(db: Session, run: AgentRun) -> List[str]:
    spans = db.query(AgentSpan).filter(AgentSpan.run_id == run.run_id).all()
    names = []
    for s in spans:
        if s.kind == "execute_tool" and s.name.startswith("execute_tool."):
            names.append(s.name.split(".", 1)[-1])
    return names


def _get_evaluator(db: Session, evaluator_id: str) -> Optional[EvalRuleEvaluator]:
    if not evaluator_id:
        return None
    return (
        db.query(EvalRuleEvaluator)
        .filter(EvalRuleEvaluator.evaluator_id == evaluator_id)
        .first()
    )


async def _rerun_case(
    db: Session,
    *,
    case: EvalCase,
    agent_id: str,
) -> tuple[str, Optional[AgentRun], str, List[str], int]:
    """Create ephemeral session, run agent once, return reply + run."""
    from services.agent_service import AgentService

    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if not agent:
        raise ValueError("Agent not found for rerun")

    session = SessionModel(
        session_id=gen_uuid(),
        agent_id=agent_id,
        status=SessionStatus.ACTIVE,
        messages=[],
        title=f"eval-rerun-{case.case_id[:8]}",
    )
    db.add(session)
    db.commit()

    result = await AgentService.chat_with_agent(
        db=db,
        agent_id=agent_id,
        session_id=session.session_id,
        message=case.input_text or "test",
        skip_history=True,
    )
    reply = (result.get("content") or "")[:5000]
    run = (
        db.query(AgentRun)
        .filter(AgentRun.session_id == session.session_id)
        .order_by(AgentRun.started_at.desc())
        .first()
    )
    tools_called: List[str] = []
    elapsed = 0
    if run:
        tools_called = _tools_from_run(db, run)
        elapsed = run.elapsed_ms or 0
    return reply, run, reply, tools_called, elapsed


def run_eval_job(db: Session, job_id: str) -> Dict[str, Any]:
    job = db.query(EvalJob).filter(EvalJob.job_id == job_id).first()
    if not job:
        raise ValueError("Eval job not found")
    cases = db.query(EvalCase).filter(EvalCase.dataset_id == job.dataset_id).all()
    dataset = db.query(EvalDataset).filter(EvalDataset.dataset_id == job.dataset_id).first()
    evaluator = _get_evaluator(db, job.evaluator_id or "")
    agent_id = job.agent_id or (dataset.agent_id if dataset else "")

    job.status = EvalJobStatus.RUNNING.value
    job.started_at = now_utc()
    db.commit()

    passed_count = 0
    results: List[EvalJobResult] = []
    for case in cases:
        run = None
        reply = ""
        tools_called: List[str] = []
        elapsed = 0

        if job.run_mode == "rerun" and agent_id:
            try:
                reply, run, _, tools_called, elapsed = asyncio.run(
                    _rerun_case(db, case=case, agent_id=agent_id)
                )
            except Exception as exc:
                ev = {
                    "passed": False,
                    "scores": {"overall": 0.0},
                    "details": [f"Rerun failed: {exc}"],
                }
                row = EvalJobResult(
                    result_id=gen_uuid(),
                    job_id=job.job_id,
                    case_id=case.case_id,
                    passed=False,
                    scores=ev["scores"],
                    details={"messages": ev["details"]},
                )
                db.add(row)
                results.append(row)
                continue
        elif case.source_run_id:
            run = db.query(AgentRun).filter(AgentRun.run_id == case.source_run_id).first()
            if run:
                reply = run.summary or ""
                tools_called = _tools_from_run(db, run)
                elapsed = run.elapsed_ms or 0
        else:
            reply = case.input_text or ""

        rules = _merge_rules(case, evaluator)
        ev = evaluate_case_rules(
            case,
            run=run,
            reply=reply,
            tools_called=tools_called,
            elapsed_ms=elapsed,
            rules=rules,
        )
        if ev["passed"]:
            passed_count += 1
        row = EvalJobResult(
            result_id=gen_uuid(),
            job_id=job.job_id,
            case_id=case.case_id,
            passed=ev["passed"],
            scores=ev["scores"],
            details={"messages": ev["details"], "reply_preview": (reply or "")[:200]},
        )
        db.add(row)
        results.append(row)

    total = len(cases) or 1
    pass_rate = passed_count / total
    job.status = EvalJobStatus.SUCCESS.value if pass_rate >= (job.pass_threshold or 0.8) else EvalJobStatus.FAILED.value
    job.finished_at = now_utc()
    job.summary = {
        "total": len(cases),
        "passed": passed_count,
        "pass_rate": round(pass_rate, 4),
        "threshold": job.pass_threshold,
        "run_mode": job.run_mode or "replay",
    }
    db.commit()
    return {"job_id": job.job_id, "status": job.status, "summary": job.summary}


def compare_jobs(db: Session, job_id_a: str, job_id_b: str) -> Dict[str, Any]:
    job_a = db.query(EvalJob).filter(EvalJob.job_id == job_id_a).first()
    job_b = db.query(EvalJob).filter(EvalJob.job_id == job_id_b).first()
    if not job_a or not job_b:
        raise ValueError("Job not found")
    if job_a.dataset_id != job_b.dataset_id:
        raise ValueError("Jobs must share the same dataset")

    results_a = {
        r.case_id: r
        for r in db.query(EvalJobResult).filter(EvalJobResult.job_id == job_id_a).all()
    }
    results_b = {
        r.case_id: r
        for r in db.query(EvalJobResult).filter(EvalJobResult.job_id == job_id_b).all()
    }
    case_ids = sorted(set(results_a.keys()) | set(results_b.keys()))
    cases = {
        c.case_id: c
        for c in db.query(EvalCase).filter(EvalCase.case_id.in_(case_ids)).all()
    } if case_ids else {}

    rows = []
    for cid in case_ids:
        ra = results_a.get(cid)
        rb = results_b.get(cid)
        case = cases.get(cid)
        rows.append(
            {
                "case_id": cid,
                "input_preview": (case.input_text or "")[:120] if case else "",
                "job_a_passed": ra.passed if ra else None,
                "job_b_passed": rb.passed if rb else None,
                "job_a_score": (ra.scores or {}).get("overall") if ra else None,
                "job_b_score": (rb.scores or {}).get("overall") if rb else None,
                "regression": bool(ra and rb and ra.passed and not rb.passed),
            }
        )
    return {
        "dataset_id": job_a.dataset_id,
        "job_a": {"job_id": job_id_a, "summary": job_a.summary or {}},
        "job_b": {"job_id": job_id_b, "summary": job_b.summary or {}},
        "rows": rows,
    }


def serialize_rule_evaluator(ev: EvalRuleEvaluator) -> Dict[str, Any]:
    return {
        "evaluator_id": ev.evaluator_id,
        "name": ev.name,
        "agent_id": ev.agent_id,
        "enabled": ev.enabled,
        "rules_json": ev.rules_json or {},
        "created_at": ev.created_at.isoformat() if ev.created_at else None,
    }


def delete_dataset_cascade(db: Session, dataset_id: str) -> dict:
    """Delete dataset with cases, job results, and jobs."""
    ds = db.query(EvalDataset).filter(EvalDataset.dataset_id == dataset_id).first()
    if not ds:
        raise ValueError("Dataset not found")

    running = (
        db.query(EvalJob)
        .filter(
            EvalJob.dataset_id == dataset_id,
            EvalJob.status.in_([EvalJobStatus.PENDING.value, EvalJobStatus.RUNNING.value]),
        )
        .count()
    )
    if running:
        raise ValueError("Cannot delete dataset with pending or running jobs")

    job_ids = [
        j.job_id
        for j in db.query(EvalJob).filter(EvalJob.dataset_id == dataset_id).all()
    ]
    deleted = {"cases": 0, "job_results": 0, "jobs": 0}
    if job_ids:
        deleted["job_results"] = (
            db.query(EvalJobResult)
            .filter(EvalJobResult.job_id.in_(job_ids))
            .delete(synchronize_session=False)
        )
        deleted["jobs"] = (
            db.query(EvalJob)
            .filter(EvalJob.job_id.in_(job_ids))
            .delete(synchronize_session=False)
        )
    deleted["cases"] = (
        db.query(EvalCase)
        .filter(EvalCase.dataset_id == dataset_id)
        .delete(synchronize_session=False)
    )
    db.delete(ds)
    db.commit()
    return deleted


def add_run_to_dataset(
    db: Session,
    *,
    dataset_id: str,
    run_id: str,
    input_text: str = "",
) -> EvalCase:
    run = db.query(AgentRun).filter(AgentRun.run_id == run_id).first()
    if not run:
        raise ValueError("Run not found")
    tools = _tools_from_run(db, run)
    case = EvalCase(
        case_id=gen_uuid(),
        dataset_id=dataset_id,
        input_text=input_text or run.summary or "",
        expected_output=run.summary or "",
        expected_tools=tools,
        source_run_id=run_id,
        rubric="Auto-imported badcase from monitor",
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def batch_import_feedback(
    db: Session,
    *,
    dataset_id: str,
    agent_id: str,
    days: int = 7,
) -> Dict[str, Any]:
    """Import negative feedback runs into dataset."""
    from datetime import timedelta

    from models import AgentFeedback

    since = datetime.now(timezone.utc) - timedelta(days=days)
    q = db.query(AgentFeedback).filter(
        AgentFeedback.created_at >= since,
        AgentFeedback.rating < 0,
    )
    if agent_id:
        q = q.filter(AgentFeedback.agent_id == agent_id)
    feedbacks = q.all()
    imported = 0
    for fb in feedbacks:
        run_id = fb.run_id
        if not run_id and fb.session_id and fb.message_index >= 0:
            run = (
                db.query(AgentRun)
                .filter(
                    AgentRun.session_id == fb.session_id,
                    AgentRun.message_index == fb.message_index,
                )
                .order_by(AgentRun.started_at.desc())
                .first()
            )
            run_id = run.run_id if run else None
        if not run_id:
            continue
        existing = (
            db.query(EvalCase)
            .filter(EvalCase.dataset_id == dataset_id, EvalCase.source_run_id == run_id)
            .first()
        )
        if existing:
            continue
        add_run_to_dataset(db, dataset_id=dataset_id, run_id=run_id)
        imported += 1
    return {"imported": imported, "total_feedback": len(feedbacks)}
