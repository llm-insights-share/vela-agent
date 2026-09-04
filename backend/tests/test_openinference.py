"""OpenInference attribute + export unit tests."""

from __future__ import annotations

from services.monitor.export import export_run_otel_json
from services.monitor.openinference_attrs import (
    attrs_for_agent,
    attrs_for_guardrail,
    attrs_for_llm_call,
    attrs_for_retriever,
    attrs_for_tool,
    flatten_dict,
    legacy_kind_for_oi,
    oi_kind_from_legacy,
)


def test_flatten_dict_nested():
    flat = flatten_dict({"a": {"b": 1}, "list": [{"x": 2}]})
    assert flat["a.b"] == 1
    assert flat["list.0.x"] == 2


def test_kind_mapping_roundtrip():
    assert legacy_kind_for_oi("LLM") == "chat"
    assert legacy_kind_for_oi("TOOL") == "execute_tool"
    assert legacy_kind_for_oi("GUARDRAIL") == "guard_decision"
    assert oi_kind_from_legacy("chat") == "LLM"
    assert oi_kind_from_legacy("execute_tool") == "TOOL"


def test_attrs_for_llm_call_required_keys():
    attrs = attrs_for_llm_call(
        model_name="gpt-test",
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "search"}}],
        max_tokens=100,
        temperature=0.2,
        output_content="hello",
        usage={"prompt_tokens": 3, "completion_tokens": 2},
        source="react",
    )
    assert attrs["openinference.span.kind"] == "LLM"
    assert attrs["llm.model_name"] == "gpt-test"
    assert attrs["llm.token_count.prompt"] == 3
    assert attrs["llm.token_count.completion"] == 2
    assert "llm.input_messages.0.message.role" in attrs
    assert attrs["llm.input_messages.0.message.role"] == "user"
    assert "input.value" in attrs
    assert "output.value" in attrs


def test_attrs_for_tool_and_guard():
    t = attrs_for_tool(tool_name="bash", parameters={"cmd": "ls"}, output={"ok": True})
    assert t["openinference.span.kind"] == "TOOL"
    assert t["tool.name"] == "bash"
    g = attrs_for_guardrail(checkpoint="before_tool", decision="allow", action="allow")
    assert g["openinference.span.kind"] == "GUARDRAIL"


def test_attrs_for_agent_and_retriever():
    a = attrs_for_agent(session_id="s1", user_id="u1", agent_id="a1", input_text="q")
    assert a["openinference.span.kind"] == "AGENT"
    assert a["session.id"] == "s1"
    r = attrs_for_retriever(
        query="weather",
        documents=[{"chunk_id": "c1", "content": "doc", "score": 0.9}],
    )
    assert r["openinference.span.kind"] == "RETRIEVER"
    assert "retrieval.documents.0.document.id" in r or any(
        "document.id" in k for k in r
    )


def test_export_includes_openinference_kind():
    payload = export_run_otel_json(
        {
            "run_id": "r1",
            "trace_id": "abc",
            "session_id": "s1",
            "agent_id": "a1",
            "caller_id": "u1",
            "attrs_json": {"evaluations.0.evaluation.name": "llm_judge"},
        },
        [
            {
                "span_id": "sp1",
                "name": "chat.react",
                "kind": "chat",
                "attrs_json": {
                    "openinference.span.kind": "LLM",
                    "llm.model_name": "m",
                },
                "duration_ms": 10,
                "status": "OK",
                "started_at": None,
            }
        ],
    )
    assert "openinference-json" in payload
    assert "openinference.span.kind" in payload
    assert "LLM" in payload
    assert "evaluations.0.evaluation.name" in payload


def test_dual_write_buffer_to_postgres():
    from datetime import datetime

    from database import SessionLocal, init_db
    from models import (
        Agent,
        AgentSpan,
        AgentStatus,
        AgentType,
        ModelProvider,
        ModelService,
        ProviderStatus,
        Session as SessionModel,
        gen_uuid,
    )
    from services.monitor.oi_tracing import mark_span_ok, oi_span
    from services.monitor.openinference_attrs import attrs_for_agent, attrs_for_llm_call
    from services.monitor.otel_setup import setup_tracer_provider
    from services.monitor.span_buffer import get_turn_context, start_turn_context
    from services.monitor.trace_sink import record_agent_run

    setup_tracer_provider(force=True)
    init_db()
    db = SessionLocal()
    try:
        ts = datetime.now().timestamp()
        provider = ModelProvider(
            provider_code=f"oi_{ts}",
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
            name=f"oi_agent_{ts}",
            model_service_id=model.model_service_id,
            status=AgentStatus.DRAFT,
            agent_type=AgentType.SINGLE,
        )
        db.add(agent)
        db.commit()
        session = SessionModel(
            session_id=gen_uuid(),
            agent_id=agent.agent_id,
            messages=[{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}],
            llm_calls=[],
            trace_id="b" * 32,
        )
        db.add(session)
        db.commit()

        run_id = gen_uuid()
        start_turn_context(
            run_id=run_id,
            session_id=session.session_id,
            agent_id=agent.agent_id,
            otel_enabled=True,
        )
        with oi_span(
            "agent.run",
            attrs_for_agent(session_id=session.session_id, agent_id=agent.agent_id, input_text="hi"),
        ) as sp:
            with oi_span(
                "chat.react",
                attrs_for_llm_call(
                    model_name="m",
                    messages=[{"role": "user", "content": "hi"}],
                    output_content="hello",
                    usage={"prompt_tokens": 1, "completion_tokens": 1},
                ),
            ) as lsp:
                mark_span_ok(lsp)
            mark_span_ok(sp)

        ctx = get_turn_context()
        assert ctx is not None
        assert len(ctx.spans) >= 2
        rid = record_agent_run(
            db,
            session=session,
            agent=agent,
            result={"content": "hello", "run_metrics": {"elapsed_ms": 10}, "execution_mode": "react"},
            story_status="done",
            success=True,
        )
        assert rid == run_id
        spans = db.query(AgentSpan).filter(AgentSpan.run_id == rid).all()
        kinds = {(s.attrs_json or {}).get("openinference.span.kind") for s in spans}
        assert "LLM" in kinds
        assert "AGENT" in kinds
    finally:
        db.close()
