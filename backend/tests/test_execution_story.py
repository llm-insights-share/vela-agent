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


def test_from_coordinator_with_trail():
    trail = [
        {
            "round": 1,
            "role_name": "资料收集",
            "receiver": "agent-1",
            "task": "收集 2024 年材料",
            "success": True,
            "duration_ms": 1200,
            "tokens": 800,
        },
        {
            "round": 1,
            "role_name": "风险分析",
            "receiver": "agent-2",
            "task": "分析风险点",
            "success": True,
            "duration_ms": 900,
            "tokens": 500,
        },
    ]
    story = ExecutionStoryBuilder.from_coordinator(
        trail,
        ["[Coordinator] 开始处理用户任务: 输出审计立项说明书", "[Coordinator] 任务完成，总 Token: 1300"],
        user_message="输出审计立项说明书",
        status="done",
    )
    assert story["status"] == "done"
    act = next(p for p in story["phases"] if p["id"] == "act")
    assert len(act["steps"]) == 2
    assert act["steps"][0]["role_name"] == "资料收集"
    assert any(p["id"] == "deliver" for p in story["phases"])


def test_from_coordinator_hitl():
    story = ExecutionStoryBuilder.from_coordinator(
        [{"round": 1, "role_name": "报告撰写", "task": "写报告", "success": True, "duration_ms": 100}],
        ["[Coordinator] 交付前 HITL Gate 已触发"],
        user_message="出报告",
        hitl=True,
    )
    assert story["status"] == "hitl_wait"
    assert "待交付" in story["summary"] or "审批" in story["summary"]
    verify = next(p for p in story["phases"] if p["id"] == "verify")
    assert verify["status"] == "hitl"
