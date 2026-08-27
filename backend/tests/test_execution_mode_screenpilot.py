"""Execution mode + structured tool JSON for ScreenPilot agent tasks."""

from services.agent_service import (
    AgentLoop,
    _analyze_execution_mode,
    _looks_like_screenpilot_task,
)


def test_looks_like_screenpilot_task_xhs_publish():
    msg = '使用驭屏系统，发布小红书帖文。标题：“我的测试贴”，正文：“这是一个使用agent发布的测试贴文”'
    assert _looks_like_screenpilot_task(msg) is True
    assert _analyze_execution_mode(msg, has_tools=True, has_kb=False, has_skills=False) == "react"


def test_parse_structured_tool_params_alias():
    content = (
        '我将查找技能。\n\n```json\n'
        '{\n  "tool": "cu_search_skills",\n  "params": {\n    "query": "小红书 发布帖文"\n  }\n}\n'
        "```"
    )
    parsed = AgentLoop._parse_structured_output(None, content)
    assert parsed is not None
    assert parsed["tool_name"] == "cu_search_skills"
    assert parsed["arguments"]["query"] == "小红书 发布帖文"


if __name__ == "__main__":
    test_looks_like_screenpilot_task_xhs_publish()
    test_parse_structured_tool_params_alias()
    print("ok")
