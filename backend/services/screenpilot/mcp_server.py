#!/usr/bin/env python3
"""ScreenPilot stdio MCP Server — 暴露 ui_* 工具供 Vela Agent 调用。"""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Dict

from database import SessionLocal
from services.screenpilot.service import (
    act_ui,
    extract_ui,
    navigate_ui,
    observe_session,
    replay_skill_stub,
)

TOOLS = [
    {
        "name": "ui_navigate",
        "description": "打开目标系统页面并可选执行登录宏，返回 SoM 标注观测结果",
        "inputSchema": {
            "type": "object",
            "properties": {
                "system_id": {"type": "string", "description": "注册的系统 ID"},
                "url": {"type": "string", "description": "目标 URL，默认使用系统入口"},
                "screen_session_id": {"type": "string", "description": "可选，已有浏览器会话 ID"},
                "vela_session_id": {"type": "string", "description": "Vela Agent 会话 ID"},
                "agent_id": {"type": "string", "description": "Agent ID"},
                "auto_login": {"type": "boolean", "default": True},
            },
            "required": ["system_id"],
        },
    },
    {
        "name": "ui_observe",
        "description": "观测当前页面：截图 + 无障碍树 + SoM 元素编号",
        "inputSchema": {
            "type": "object",
            "properties": {
                "screen_session_id": {"type": "string"},
            },
            "required": ["screen_session_id"],
        },
    },
    {
        "name": "ui_act",
        "description": "在企业内系统页面上执行原子操作；T2/T3 动作将触发 HITL 网关",
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
                "target_ref": {"type": "string", "description": "SoM 编号，如 [7]"},
                "value": {"type": "string"},
                "vela_session_id": {"type": "string"},
                "agent_id": {"type": "string"},
            },
            "required": ["screen_session_id", "action"],
        },
    },
    {
        "name": "ui_extract",
        "description": "提取当前页面正文文本",
        "inputSchema": {
            "type": "object",
            "properties": {"screen_session_id": {"type": "string"}},
            "required": ["screen_session_id"],
        },
    },
    {
        "name": "ui_replay_skill",
        "description": "确定性重放已编译 UI 技能（P1 stub）",
        "inputSchema": {
            "type": "object",
            "properties": {"skill_id": {"type": "string"}, "params": {"type": "object"}},
            "required": ["skill_id"],
        },
    },
]


async def _dispatch(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    db = SessionLocal()
    try:
        if name == "ui_navigate":
            return await navigate_ui(db, **arguments)
        if name == "ui_observe":
            return await observe_session(db, arguments["screen_session_id"])
        if name == "ui_act":
            return await act_ui(db, **arguments)
        if name == "ui_extract":
            return await extract_ui(db, arguments["screen_session_id"])
        if name == "ui_replay_skill":
            return await replay_skill_stub(**arguments)
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
