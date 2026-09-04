"""Monitor & Eval tests."""

from __future__ import annotations

from datetime import datetime

from database import SessionLocal, init_db
from models import (
    Agent,
    AgentRun,
    AgentRunStatus,
    AgentSpan,
    AgentStatus,
    AgentType,
    EvalCase,
    EvalDataset,
    EvalJob,
    EvalJobResult,
    EvalJobStatus,
    EvalRuleEvaluator,
    ModelProvider,
    ModelService,
    ProviderStatus,
    Session as SessionModel,
    gen_uuid,
)
from services.eval.evaluator import (
    compare_jobs,
    delete_dataset_cascade,
    evaluate_case_rules,
    run_eval_job,
    serialize_rule_evaluator,
)
from services.monitor.alerts import monitor_summary, resolve_run_id
from services.monitor.guardrails import check_before_reply, check_before_tool
from services.monitor.trace_sink import record_agent_run


def _create_agent(db):
    provider = ModelProvider(
        provider_code=f"p_{datetime.now().timestamp()}",
        display_name="p",
        base_url="https://example.com/v1",
        api_key="x",
        status=ProviderStatus.ACTIVE,
    )
    db.add(provider)
    db.commit()
    model = ModelService(
        provider_id=provider.provider_id,
        model_name="m",
        display_name="m",
    )
    db.add(model)
    db.commit()
    agent = Agent(
        agent_id=gen_uuid(),
        name=f"agent_{datetime.now().timestamp()}",
        model_service_id=model.model_service_id,
        status=AgentStatus.DRAFT,
        agent_type=AgentType.SINGLE,
    )
    db.add(agent)
    db.commit()
    return agent


def _session(db, agent_id):
    s = SessionModel(
        session_id=gen_uuid(),
        agent_id=agent_id,
        messages=[{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}],
        llm_calls=[
            {
                "call_id": "c1",
                "seq": 1,
                "duration_ms": 120,
                "source": "chat",
                "model_name": "test",
                "input": {"messages": [{"role": "user", "content": "hi"}]},
                "output": {"content": "hello", "usage": {"prompt_tokens": 10, "completion_tokens": 5}},
            }
        ],
        trace_id="trace-1",
    )
    db.add(s)
    db.commit()
    return s


def test_guardrails_block_empty_reply():
    d = check_before_reply("")
    assert d.allowed is False


def test_guardrails_tool_allowlist():
    d = check_before_tool("bash", {}, allowed_tool_names={"read_file"})
    assert d.allowed is False


def test_record_agent_run_creates_spans():
    init_db()
    db = SessionLocal()
    try:
        agent = _create_agent(db)
        session = _session(db, agent.agent_id)
        run_id = record_agent_run(
            db,
            session=session,
            agent=agent,
            result={
                "content": "hello",
                "execution_mode": "react",
                "run_metrics": {"elapsed_ms": 200, "tool_rounds": 0},
                "execution_story": {"summary": "done", "phases": []},
            },
        )
        assert run_id
        run = db.query(AgentRun).filter(AgentRun.run_id == run_id).first()
        assert run.status == AgentRunStatus.SUCCESS.value
        spans = db.query(AgentSpan).filter(AgentSpan.run_id == run_id).all()
        assert len(spans) >= 2
        llm_spans = [s for s in spans if s.kind == "chat"]
        assert llm_spans
        assert (llm_spans[0].attrs_json or {}).get("openinference.span.kind") == "LLM"
        assert (llm_spans[0].attrs_json or {}).get("llm.model_name") == "test"
    finally:
        db.close()


def test_eval_job_rules():
    case = EvalCase(
        case_id="c1",
        dataset_id="d1",
        input_text="test",
        expected_tools=["search_messages"],
        expected_keywords=["结果"],
    )
    ev = evaluate_case_rules(
        case,
        reply="这是结果",
        tools_called=["search_messages"],
        elapsed_ms=1000,
    )
    assert ev["passed"] is True


def test_eval_expected_output():
    case = EvalCase(
        case_id="c2",
        dataset_id="d1",
        input_text="q",
        expected_output="hello world",
    )
    ev = evaluate_case_rules(case, reply="hello world", elapsed_ms=100)
    assert ev["passed"] is True
    ev2 = evaluate_case_rules(case, reply="wrong", elapsed_ms=100)
    assert ev2["passed"] is False


def test_resolve_run_id_by_message_index():
    init_db()
    db = SessionLocal()
    try:
        agent = _create_agent(db)
        session = _session(db, agent.agent_id)
        run = AgentRun(
            run_id=gen_uuid(),
            session_id=session.session_id,
            agent_id=agent.agent_id,
            status=AgentRunStatus.SUCCESS.value,
            message_index=1,
            summary="hi",
        )
        db.add(run)
        db.commit()
        rid = resolve_run_id(db, run_id=None, session_id=session.session_id, message_index=1)
        assert rid == run.run_id
    finally:
        db.close()


def test_compare_jobs():
    init_db()
    db = SessionLocal()
    try:
        ds_id = gen_uuid()
        case_id = gen_uuid()
        job_a = gen_uuid()
        job_b = gen_uuid()
        db.add(EvalDataset(dataset_id=ds_id, name=f"ds_cmp_{datetime.now().timestamp()}"))
        db.commit()
        db.add(EvalCase(case_id=case_id, dataset_id=ds_id, input_text="x"))
        db.add(EvalJob(job_id=job_a, dataset_id=ds_id, status=EvalJobStatus.SUCCESS.value))
        db.add(EvalJob(job_id=job_b, dataset_id=ds_id, status=EvalJobStatus.SUCCESS.value))
        db.commit()
        db.add(EvalJobResult(result_id=gen_uuid(), job_id=job_a, case_id=case_id, passed=True, scores={"overall": 1.0}))
        db.add(EvalJobResult(result_id=gen_uuid(), job_id=job_b, case_id=case_id, passed=False, scores={"overall": 0.0}))
        db.commit()
        cmp = compare_jobs(db, job_a, job_b)
        assert cmp["rows"][0]["regression"] is True
    finally:
        db.close()


def test_rule_evaluator_serialize():
    ev = EvalRuleEvaluator(
        evaluator_id="e1",
        name="default",
        rules_json={"forbidden_patterns": ["bad"]},
    )
    data = serialize_rule_evaluator(ev)
    assert data["name"] == "default"
    assert "forbidden_patterns" in (data.get("rules_json") or {})


def test_monitor_summary_empty():
    init_db()
    db = SessionLocal()
    try:
        s = monitor_summary(db, agent_id=gen_uuid(), days=7)
        assert s["total_runs"] == 0
        assert "success_rate" in s
        assert "timeseries" in s
    finally:
        db.close()


def test_delete_dataset_cascade():
    init_db()
    db = SessionLocal()
    try:
        ds_id = gen_uuid()
        case_id = gen_uuid()
        job_id = gen_uuid()
        ds = EvalDataset(dataset_id=ds_id, name=f"ds_{datetime.now().timestamp()}", agent_id="")
        db.add(ds)
        db.commit()
        db.add(
            EvalCase(
                case_id=case_id,
                dataset_id=ds_id,
                input_text="x",
                expected_tools=["t"],
            )
        )
        db.add(
            EvalJob(
                job_id=job_id,
                dataset_id=ds_id,
                status=EvalJobStatus.SUCCESS.value,
                pass_threshold=0.8,
            )
        )
        db.commit()
        db.add(
            EvalJobResult(
                result_id=gen_uuid(),
                job_id=job_id,
                case_id=case_id,
                passed=True,
                scores={"overall": 1.0},
            )
        )
        db.commit()

        stats = delete_dataset_cascade(db, ds_id)
        assert stats["cases"] == 1
        assert stats["jobs"] == 1
        assert stats["job_results"] == 1
        assert db.query(EvalDataset).filter(EvalDataset.dataset_id == ds_id).first() is None
    finally:
        db.close()


def test_delete_dataset_rejects_running_job():
    init_db()
    db = SessionLocal()
    try:
        ds_id = gen_uuid()
        ds = EvalDataset(dataset_id=ds_id, name=f"ds_run_{datetime.now().timestamp()}", agent_id="")
        db.add(ds)
        db.commit()
        db.add(
            EvalJob(
                job_id=gen_uuid(),
                dataset_id=ds_id,
                status=EvalJobStatus.RUNNING.value,
            )
        )
        db.commit()

        try:
            delete_dataset_cascade(db, ds_id)
            assert False, "expected ValueError"
        except ValueError as e:
            assert "running" in str(e).lower() or "pending" in str(e).lower()
    finally:
        db.close()


def test_eval_job_list_and_run():
    init_db()
    db = SessionLocal()
    try:
        ds_id = gen_uuid()
        ds = EvalDataset(dataset_id=ds_id, name=f"ds_job_{datetime.now().timestamp()}", agent_id="")
        db.add(ds)
        db.commit()
        db.add(
            EvalCase(
                case_id=gen_uuid(),
                dataset_id=ds_id,
                input_text="结果 ok",
                expected_keywords=["结果"],
            )
        )
        job = EvalJob(job_id=gen_uuid(), dataset_id=ds_id, pass_threshold=0.8)
        db.add(job)
        db.commit()

        result = run_eval_job(db, job.job_id)
        assert result["status"] == EvalJobStatus.SUCCESS.value
        assert result["summary"]["pass_rate"] == 1.0

        jobs = db.query(EvalJob).filter(EvalJob.dataset_id == ds_id).all()
        assert len(jobs) == 1
        rows = db.query(EvalJobResult).filter(EvalJobResult.job_id == job.job_id).all()
        assert len(rows) == 1
        assert rows[0].passed is True
    finally:
        db.close()
