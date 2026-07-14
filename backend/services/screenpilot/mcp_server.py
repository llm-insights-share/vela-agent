#!/usr/bin/env python3
"""ScreenPilot stdio MCP Server — 暴露 cu_* 工具供 Vela Agent 调用。"""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Dict

from database import SessionLocal
from services.screenpilot.service import (
    act_ui,
    compile_skill,
    extract_ui,
    navigate_ui,
    observe_session,
    replay_skill,
    search_skills,
    vision_query,
    wait_for_otp_ui,
)
from services.screenpilot.run_task import run_task

TOOLS = [
    {
        "name": "cu_navigate",
        "description": "打开目标系统页面并可选执行登录宏，返回 SoM 标注观测结果",
        "inputSchema": {
            "type": "object",
            "properties": {
                "system_id": {
                    "type": "string",
                    "description": "已注册系统的 system_id（UUID）或系统名称（如 xhs）",
                },
                "url": {
                    "type": "string",
                    "description": "目标 URL，省略时使用系统 entry_url；勿自行猜测域名，优先省略或只传路径如 explore",
                },
                "screen_session_id": {"type": "string", "description": "可选，已有浏览器会话 ID"},
                "vela_session_id": {"type": "string", "description": "Vela Agent 会话 ID"},
                "agent_id": {"type": "string", "description": "Agent ID"},
                "auto_login": {"type": "boolean", "default": True},
            },
            "required": ["system_id"],
        },
    },
    {
        "name": "cu_observe",
        "description": (
            "观测当前页面：截图 + 无障碍树 + DOM 合并 SoM 元素编号；"
            "返回 total_elements/truncated/scope，弹窗内元素优先；"
            "元素过少或含 canvas 时返回 suggest_vision=true，可再调 cu_vision"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "screen_session_id": {"type": "string"},
            },
            "required": ["screen_session_id"],
        },
    },
    {
        "name": "cu_act",
        "description": (
            "在企业内系统页面上执行原子操作；T2/T3 动作将触发 HITL 网关。"
            "短信登录：勾选协议后填手机号，先点输入框旁短文案发码控件（button 或 link），"
            "确认倒计时后再填验证码并点主提交；wait 的 value 只能是毫秒数字，等短信请用 cu_wait_for_otp。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "screen_session_id": {"type": "string"},
                "action": {
                    "type": "string",
                    "enum": [
                        "navigate", "click", "type", "select",
                        "upload", "scroll", "wait", "extract", "screenshot",
                    ],
                },
                "target_ref": {
                    "type": "string",
                    "description": "SoM 编号，如 [7]；click 时优先使用",
                },
                "value": {
                    "type": "string",
                    "description": (
                        "navigate 的 URL；type 的输入文本；"
                        "click 且无 target_ref 时可用 value=text=按钮文案 或 css=selector 兜底点击"
                    ),
                },
                "vela_session_id": {"type": "string"},
                "agent_id": {"type": "string"},
            },
            "required": ["screen_session_id", "action"],
        },
    },
    {
        "name": "cu_extract",
        "description": "提取当前页面正文文本",
        "inputSchema": {
            "type": "object",
            "properties": {"screen_session_id": {"type": "string"}},
            "required": ["screen_session_id"],
        },
    },
    {
        "name": "cu_replay_skill",
        "description": "确定性重放已编译 UI 技能；指纹失效时返回 needs_replan",
        "inputSchema": {
            "type": "object",
            "properties": {
                "skill_id": {"type": "string"},
                "screen_session_id": {"type": "string"},
                "params": {"type": "object"},
                "vela_session_id": {"type": "string"},
                "agent_id": {"type": "string"},
            },
            "required": ["skill_id", "screen_session_id"],
        },
    },
    {
        "name": "cu_compile_skill",
        "description": "将当前会话轨迹编译为可重放 UI 技能模板",
        "inputSchema": {
            "type": "object",
            "properties": {
                "screen_session_id": {"type": "string"},
                "name": {"type": "string"},
                "description": {"type": "string"},
                "scope": {"type": "string", "default": "default"},
            },
            "required": ["screen_session_id", "name"],
        },
    },
    {
        "name": "cu_search_skills",
        "description": "按任务描述语义检索 UI 技能（FAISS）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "scope": {"type": "string", "default": "default"},
                "top_k": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "cu_wait_for_otp",
        "description": "暂停任务并弹出 HITL，等待用户输入短信/邮箱验证码后继续登录",
        "inputSchema": {
            "type": "object",
            "properties": {
                "screen_session_id": {"type": "string"},
                "selector": {
                    "type": "string",
                    "description": "验证码输入框 CSS 选择器",
                },
                "submit_selector": {
                    "type": "string",
                    "description": "可选，提交按钮选择器",
                },
                "prompt": {
                    "type": "string",
                    "default": "请输入短信验证码",
                },
                "vela_session_id": {"type": "string"},
                "agent_id": {"type": "string"},
            },
            "required": ["screen_session_id", "selector"],
        },
    },
    {
        "name": "cu_run_task",
        "description": (
            "高级任务：Observe-Plan-Act-Verify；优先技能重放，未完成时返回 needs_agent + plan_hints。"
            "goal 可含规则：url_contains= / title_contains= / text_contains="
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "system_id": {
                    "type": "string",
                    "description": "已注册系统的 system_id（UUID）或系统名称（如 xhs）",
                },
                "goal": {"type": "string", "description": "任务目标描述"},
                "screen_session_id": {"type": "string"},
                "skill_id": {"type": "string"},
                "params": {"type": "object"},
                "scope": {"type": "string", "default": "default"},
                "max_steps": {"type": "integer", "default": 6},
                "vela_session_id": {"type": "string"},
                "agent_id": {"type": "string"},
            },
            "required": ["system_id", "goal"],
        },
    },
    {
        "name": "cu_vision",
        "description": (
            "对当前页面截图做视觉问答（a11y/SoM 不足或 canvas 时使用）。"
            "不自动调用；当 cu_observe 返回 suggest_vision=true 时再考虑。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "screen_session_id": {"type": "string"},
                "question": {
                    "type": "string",
                    "description": "关于截图的问题，例如「登录按钮在哪里」",
                },
                "use_som": {
                    "type": "boolean",
                    "default": False,
                    "description": "为 true 时使用 SoM 叠加图而非原截图",
                },
            },
            "required": ["screen_session_id", "question"],
        },
    },
]


async def _dispatch(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    import inspect

    def _filter_kwargs(fn, args: Dict[str, Any]) -> Dict[str, Any]:
        """Drop injected keys (e.g. vela_session_id) that the handler does not accept."""
        try:
            sig = inspect.signature(fn)
        except (TypeError, ValueError):
            return args
        if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
            return args
        allowed = {k for k in sig.parameters if k != "db"}
        return {k: v for k, v in (args or {}).items() if k in allowed}

    db = SessionLocal()
    try:

        if name == "cu_navigate":
            return await navigate_ui(db, **_filter_kwargs(navigate_ui, arguments))
        if name == "cu_observe":
            args = _filter_kwargs(observe_session, arguments)
            return await observe_session(db, args.get("screen_session_id") or arguments["screen_session_id"])
        if name == "cu_act":
            return await act_ui(db, **_filter_kwargs(act_ui, arguments))
        if name == "cu_extract":
            return await extract_ui(db, arguments["screen_session_id"])
        if name == "cu_replay_skill":
            return await replay_skill(db, **_filter_kwargs(replay_skill, arguments))
        if name == "cu_compile_skill":
            return await compile_skill(db, **_filter_kwargs(compile_skill, arguments))
        if name == "cu_search_skills":
            filtered = _filter_kwargs(search_skills, arguments)
            return await search_skills(db, **filtered)
        if name == "cu_run_task":
            return await run_task(db, **_filter_kwargs(run_task, arguments))
        if name == "cu_wait_for_otp":
            return await wait_for_otp_ui(db, **_filter_kwargs(wait_for_otp_ui, arguments))
        if name == "cu_vision":
            return await vision_query(db, **_filter_kwargs(vision_query, arguments))
        return {"success": False, "error": f"未知工具: {name}"}
    finally:
        db.close()


def _tool_result(data: Dict[str, Any], is_error: bool = False) -> Dict[str, Any]:
    text = json.dumps(data, ensure_ascii=False)
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _handle_request(req: Dict[str, Any]) -> Dict[str, Any]:
    req_id = req.get("id")
    method = req.get("method", "")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "vela-screenpilot", "version": "0.1.0"},
            },
        }

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name", "")
        arguments = params.get("arguments") or {}
        try:
            result = asyncio.run(_dispatch(name, arguments))
            is_err = not result.get("success", False) and not result.get("hitl_pending")
            return {"jsonrpc": "2.0", "id": req_id, "result": _tool_result(result, is_err)}
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": _tool_result({"success": False, "error": str(e)}, True),
            }

    if req_id is not None:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }
    return None


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = _handle_request(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
