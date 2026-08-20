"""Tests for LLM message history sanitization."""
from services.agent_service import AgentLoop


def test_sanitize_drops_orphan_tool_messages():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "assistant", "content": "calling"},
        {"role": "tool", "tool_call_id": "call_1", "content": "result"},
        {"role": "user", "content": "hi"},
    ]
    out = AgentLoop._sanitize_messages_for_llm(messages)
    assert len(out) == 3
    assert out[0]["role"] == "system"
    assert out[1]["role"] == "assistant"
    assert out[2]["role"] == "user"
    assert all(m.get("role") != "tool" for m in out)


def test_sanitize_keeps_valid_tool_chain():
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "x", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
        {"role": "assistant", "content": "done"},
    ]
    out = AgentLoop._sanitize_messages_for_llm(messages)
    assert len(out) == 3
    assert out[1]["role"] == "tool"
