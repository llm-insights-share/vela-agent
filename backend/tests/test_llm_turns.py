"""Tests for LLM turn card normalization."""
from services.llm_call_recorder import (
    attach_tool_results,
    bind_session,
    build_input_preview,
    build_turn_from_record,
    get_llm_turns,
    record_call,
    turns_from_llm_calls,
    unbind_session,
)


def test_build_input_preview_first_call():
    messages = [
        {"role": "system", "content": "you are helpful"},
        {"role": "user", "content": "hello world"},
    ]
    preview = build_input_preview(messages, prev_count=0, tools=[{"x": 1}])
    assert preview["has_system"] is True
    assert preview["tools_count"] == 1
    assert any(m["role"] == "user" for m in preview["messages"])
    assert "系统提示已注入" in preview["summary"]


def test_build_input_preview_delta():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1", "function": {"name": "t", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "1", "content": "ok"},
    ]
    preview = build_input_preview(messages, prev_count=2)
    roles = [m["role"] for m in preview["messages"]]
    assert roles == ["assistant", "tool"]


def test_record_and_attach_tool_results():
    bind_session("sess-1")
    try:
        record_call(
            model_name="demo",
            messages=[{"role": "user", "content": "go"}],
            tools=None,
            max_tokens=100,
            temperature=0.7,
            completion={
                "choices": [{
                    "message": {
                        "content": None,
                        "reasoning_content": "plan",
                        "tool_calls": [{
                            "id": "c1",
                            "function": {"name": "bash", "arguments": "{\"cmd\":\"ls\"}"},
                        }],
                    }
                }]
            },
            duration_ms=5,
            source="react",
        )
        attach_tool_results([{
            "tool_call_id": "c1",
            "name": "bash",
            "content": "file.txt",
            "ok": True,
        }])
        turns = get_llm_turns()
        assert len(turns) == 1
        assert turns[0]["thinking"] == "plan"
        assert turns[0]["response"]["tool_calls"][0]["name"] == "bash"
        assert turns[0]["tool_results"][0]["content_preview"] == "file.txt"
    finally:
        unbind_session()


def test_turns_from_llm_calls_rebuild():
    calls = [
        {
            "call_id": "a",
            "seq": 1,
            "source": "react",
            "model_name": "m",
            "duration_ms": 1,
            "input": {
                "messages": [{"role": "user", "content": "hi"}],
                "tools": None,
            },
            "output": {
                "content": "hello",
                "reasoning_content": "r",
                "tool_calls": None,
            },
        }
    ]
    turns = turns_from_llm_calls(calls)
    assert turns[0]["response"]["content"] == "hello"
    assert turns[0]["thinking"] == "r"


def test_build_turn_from_record_truncates():
    rec = {
        "call_id": "x",
        "seq": 3,
        "source": "direct",
        "model_name": "m",
        "duration_ms": 9,
        "input": {"messages": [{"role": "user", "content": "a" * 5000}], "tools": []},
        "output": {"content": "b" * 50, "reasoning_content": None, "tool_calls": None},
    }
    turn = build_turn_from_record(rec, prev_message_count=0)
    assert turn["seq"] == 3
    assert turn["input"]["messages"][0]["content"].endswith("…")
