"""ScreenPilot MCP 长驻进程池 — 避免每次工具调用 spawn 子进程。"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ScreenPilotMcpPool:
    """单例 MCP stdio 进程池。"""

    def __init__(self) -> None:
        self._process: Optional[asyncio.subprocess.Process] = None
        self._lock = asyncio.Lock()
        self._req_id = 100
        self._initialized = False
        self._command_key = ""

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    async def _readline(self, timeout: float) -> str:
        assert self._process and self._process.stdout
        line = await asyncio.wait_for(self._process.stdout.readline(), timeout=timeout)
        return line.decode().strip()

    async def _write(self, payload: Dict[str, Any]) -> None:
        assert self._process and self._process.stdin
        self._process.stdin.write((json.dumps(payload) + "\n").encode())
        await self._process.stdin.drain()

    async def _ensure_process(
        self, command: str, args: list, env: Dict[str, str], timeout: float
    ) -> None:
        key = f"{command}|{' '.join(args)}"
        if self._process and self._process.returncode is None and self._command_key == key:
            return

        await self._shutdown_unlocked()

        merged_env = {**os.environ, **env}
        self._process = await asyncio.create_subprocess_exec(
            command,
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=merged_env,
        )
        self._command_key = key
        self._initialized = False

        await self._write(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "vela-agent-pool", "version": "1.0.0"},
                },
            }
        )
        init_resp = json.loads(await self._readline(min(timeout, 15)))
        if "error" in init_resp:
            await self._shutdown_unlocked()
            raise RuntimeError(f"MCP 池初始化失败: {init_resp['error']}")

        await self._write(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        )
        self._initialized = True

    async def _shutdown_unlocked(self) -> None:
        if self._process and self._process.returncode is None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=3)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
        self._process = None
        self._initialized = False
        self._command_key = ""

    async def shutdown(self) -> None:
        async with self._lock:
            await self._shutdown_unlocked()

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        *,
        command: str,
        args: list,
        env: Dict[str, str],
        timeout_seconds: float = 60,
    ) -> Dict[str, Any]:
        async with self._lock:
            try:
                await self._ensure_process(command, args, env, timeout_seconds)
                req_id = self._next_id()
                await self._write(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "method": "tools/call",
                        "params": {"name": tool_name, "arguments": arguments},
                    }
                )
                call_resp = json.loads(await self._readline(timeout_seconds))
            except asyncio.TimeoutError:
                await self._shutdown_unlocked()
                return {"success": False, "error": f"MCP 池调用超时 ({timeout_seconds}s)"}
            except Exception as e:
                await self._shutdown_unlocked()
                return {"success": False, "error": f"MCP 池异常: {e}"}

        if "error" in call_resp:
            return {"success": False, "error": f"MCP 调用失败: {call_resp['error']}"}

        result = call_resp.get("result", {})
        if result.get("isError"):
            err_text = ""
            for item in result.get("content", []):
                if isinstance(item, dict) and item.get("type") == "text":
                    err_text = item.get("text", "")
                    break
            return {"success": False, "error": err_text or "MCP 工具返回错误"}

        text_parts = []
        for item in result.get("content", []):
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(item.get("text", ""))
        result_text = "\n".join(text_parts) if text_parts else json.dumps(result)
        return {"success": True, "result": result_text}


async def call_screenpilot_inprocess(
    tool_name: str, arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """进程内直接调用 ScreenPilot 服务（最快路径，不经 MCP 子进程）。"""
    import inspect

    from database import SessionLocal
    from services.screenpilot.service import TOOL_HANDLERS
    from services.screenpilot.run_task import run_task

    def _filter_kwargs(fn, args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            sig = inspect.signature(fn)
        except (TypeError, ValueError):
            return args or {}
        if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
            return args or {}
        allowed = {k for k in sig.parameters if k != "db"}
        return {k: v for k, v in (args or {}).items() if k in allowed}

    db = SessionLocal()
    try:

        if tool_name == "cu_run_task":
            result = await run_task(db, **_filter_kwargs(run_task, arguments))
        elif tool_name in TOOL_HANDLERS:
            handler = TOOL_HANDLERS[tool_name]
            filtered = _filter_kwargs(handler, arguments)
            result = await handler(db, **filtered)
        else:
            return {"success": False, "error": f"未知 ScreenPilot 工具: {tool_name}"}

        if result.get("hitl_pending"):
            return {"success": True, "result": json.dumps(result, ensure_ascii=False), "raw": result}
        if not result.get("success", True) and result.get("error"):
            return {"success": False, "error": result.get("error", "执行失败")}
        return {"success": True, "result": json.dumps(result, ensure_ascii=False), "raw": result}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        db.close()


screenpilot_mcp_pool = ScreenPilotMcpPool()


def default_pool_command() -> tuple:
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return (
        sys.executable,
        ["-m", "services.screenpilot.mcp_server"],
        {"SCREENPILOT_ENABLED": "true", "PYTHONPATH": backend_dir},
    )
