"""Tests for ExecutionStoryBuilder."""
from services.execution_story import ExecutionStoryBuilder


def test_happy_path_phases():
    b = ExecutionStoryBuilder()
    b.add_intent("查采购")
    b.add_tool_result("nl2sql_query", "ok", ok=True)
    b.add_deliver()
    story = b.finalize()
    assert story["status"] == "done"
    ids = [p["id"] for p in story["phases"]]
    assert "understand" in ids
    assert "act" in ids
    assert "deliver" in ids
    assert story["metrics"]["tool_calls"] == 1


def test_hitl_status():
    b = ExecutionStoryBuilder()
    b.add_intent("提交")
    b.add_hitl("cu_act", "appr-1")
    story = b.finalize(status="hitl_wait")
    assert story["status"] == "hitl_wait"
    verify = next(p for p in story["phases"] if p["id"] == "verify")
    assert verify["status"] == "hitl"


def test_from_thinking_log_fallback():
    story = ExecutionStoryBuilder.from_thinking_log(
        "[Memory] 已注入\n工具 [tavily_web_search] 结果: hello",
        user_message="搜索新闻",
    )
    assert story["version"] == 1
    assert any(p["id"] == "gather" for p in story["phases"])
    assert any(p["id"] == "act" for p in story["phases"])
