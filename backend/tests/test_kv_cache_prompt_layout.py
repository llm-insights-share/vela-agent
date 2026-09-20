"""KV-cache friendly prompt layout: system/user split, digest truncation, tools order."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from services.agent_service import AgentLoop
from services.builtin_tools import BuiltinTool
from services.tool_search.config import ToolSearchConfig


def _minimal_loop(**overrides) -> AgentLoop:
    loop = object.__new__(AgentLoop)
    loop.db = MagicMock()
    loop.db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
    loop.agent = SimpleNamespace(system_prompt="你是测试助手。")
    loop.session = SimpleNamespace(session_id="sess-kv-1", messages=[])
    loop.available_tools = [
        BuiltinTool(name="execute_code", description="run code", parameters={}),
        BuiltinTool(name="bash", description="shell", parameters={}),
    ]
    loop.connector_context = ""
    loop.knowledge_context = "\n\n## 知识库\n- kb_a"
    loop.project_context = "\n\n## 项目\n项目指令"
    loop.skill_context = "\n\n你需要使用以下 Skill：\n## Skill: demo\n做演示"
    loop.active_skill_name = "demo"
    loop.execution_hints = None
    loop._memory_context = ""
    loop.tool_loading_cfg = ToolSearchConfig(enabled=False, mode="all")
    loop.user_message = "用户问题"
    loop.original_user_message = "用户问题"
    loop.skip_history = False
    loop.attachment_metadata = []
    loop._context_blocks = []
    loop._current_mode = "react"
    loop.SKILL_MAX_CHARS = AgentLoop.SKILL_MAX_CHARS
    for k, v in overrides.items():
        setattr(loop, k, v)
    return loop


def test_system_prompt_layout_stable_blocks():
    loop = _minimal_loop()
    # Inject memory into user message the same way _ensure_memory_loaded does.
    mem = "【系统附注·长期记忆】\n我喜欢喝茶"
    loop.user_message = f"用户问题\n\n---\n{mem}"
    loop._memory_context = mem

    system = loop._build_system_prompt()
    assert "你是测试助手。" in system
    assert "workspaces/sess-kv-1/" in system
    assert "backend/data/workspaces" not in system
    assert "当前日期：" in system
    # Date should be after project / knowledge (near the end).
    date_idx = system.rfind("当前日期：")
    assert date_idx > system.find("## 知识库")
    assert date_idx > system.find("## 项目")
    # Memory and Skill must not live in system.
    assert "长期记忆" not in system
    assert "喜欢喝茶" not in system
    assert "【系统附注·Skill" not in system
    assert "Skill: demo" not in system


def test_memory_and_skill_only_on_user_for_llm():
    loop = _minimal_loop()
    mem_block = (
        "\n\n---\n【系统附注·长期记忆·必须遵从】\n"
        "以下是你的长期记忆，请优先使用其中的事实。\n"
        "【核心记忆】用户代号小明"
    )
    loop.user_message = "你好" + mem_block
    loop.original_user_message = "你好"
    loop.session.messages = []

    messages = loop._build_initial_messages()
    assert messages[0]["role"] == "system"
    assert "小明" not in messages[0]["content"]
    assert "Skill: demo" not in messages[0]["content"]

    user_msg = messages[-1]
    assert user_msg["role"] == "user"
    content = user_msg["content"]
    assert "小明" in content
    assert "【系统附注·Skill" in content
    assert "Skill: demo" in content


def test_digest_plus_tail_truncation_and_sanitize():
    loop = _minimal_loop(skip_history=False)
    loop.skill_context = ""
    loop.active_skill_name = None
    loop.user_message = "最新问题"
    loop.original_user_message = "最新问题"

    history = []
    for i in range(AgentLoop.MAX_CONTEXT_MESSAGES + 5):
        history.append({"role": "user", "content": f"old-user-{i}"})
        history.append({"role": "assistant", "content": f"old-asst-{i}"})
    # Tail starts mid tool-chain: orphan tool after truncate should be filled.
    history.append({
        "role": "assistant",
        "content": "",
        "tool_calls": [{
            "id": "call_orphan",
            "type": "function",
            "function": {"name": "bash", "arguments": "{}"},
        }],
    })
    history.append({"role": "tool", "tool_call_id": "call_orphan", "content": "ok"})
    loop.session.messages = history

    messages = loop._build_initial_messages()
    messages = loop._truncate_context(messages)

    assert messages[0]["role"] == "system"
    digests = [
        m for m in messages
        if m.get("role") == "user"
        and isinstance(m.get("content"), str)
        and m["content"].startswith("【上下文摘要·已截断较早回合】")
    ]
    assert len(digests) == 1
    assert "old-user-0" in digests[0]["content"] or "old-user-" in digests[0]["content"]

    # Recent tail retained (latest user turn present).
    assert any(
        m.get("role") == "user" and "最新问题" in AgentLoop._content_to_str(m.get("content"))
        for m in messages
    )

    sanitized = AgentLoop._sanitize_messages_for_llm(messages)
    # No orphan tool without preceding assistant tool_calls.
    expected_ids = set()
    for m in sanitized:
        if m.get("role") == "assistant":
            expected_ids = {tc.get("id") for tc in (m.get("tool_calls") or []) if tc.get("id")}
        elif m.get("role") == "tool":
            assert m.get("tool_call_id") in expected_ids


def test_build_tool_defs_sorted_by_name():
    tools = [
        BuiltinTool(name="zeta_tool", description="", parameters={}),
        BuiltinTool(name="alpha_tool", description="", parameters={}),
        BuiltinTool(name="mid_tool", description="", parameters={}),
    ]
    defs = AgentLoop._build_tool_defs(tools)
    names = [d["function"]["name"] for d in defs]
    assert names == ["alpha_tool", "mid_tool", "zeta_tool"]


def test_extract_cached_tokens_from_usage():
    assert AgentLoop._extract_cached_tokens({"prompt_tokens_details": {"cached_tokens": 42}}) == 42
    assert AgentLoop._extract_cached_tokens({"cache_read_input_tokens": 7}) == 7
    assert AgentLoop._extract_cached_tokens({"total_tokens": 100}) is None
