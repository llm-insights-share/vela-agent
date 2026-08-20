from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, Optional

from services.mcp.config import CLIENT_INFO, McpConnectionConfig, PREFERRED_PROTOCOL, compat_uvx_mcp_args
from services.mcp.jsonrpc import (
    McpError,
    decode_ndjson_line,
    encode_ndjson,
    extract_result,
    make_notification,
    make_request,
)


class StdioSession:
    def __init__(self, cfg: McpConnectionConfig, timeout_seconds: float = 30):
        self.cfg = cfg
        self.timeout_seconds = timeout_seconds
        self._process: Optional[asyncio.subprocess.Process] = None
        self._next_id = 1
        self._stderr_chunks: list[bytes] = []
        self._stderr_task: Optional[asyncio.Task] = None

    async def __aenter__(self) -> "StdioSession":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def start(self) -> None:
        merged_env = {**os.environ, **(self.cfg.env or {})}
        spawn_args = compat_uvx_mcp_args(self.cfg.command, list(self.cfg.args or []))
        try:
            self._process = await asyncio.create_subprocess_exec(
                self.cfg.command,
                *spawn_args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=merged_env,
            )
        except FileNotFoundError as exc:
            raise McpError(f"MCP 命令不存在: {self.cfg.command}") from exc

        self._stderr_task = asyncio.create_task(self._drain_stderr())
        await self.initialize()

    async def _drain_stderr(self) -> None:
        if not self._process or not self._process.stderr:
            return
        try:
            while True:
                chunk = await self._process.stderr.read(4096)
                if not chunk:
                    break
                self._stderr_chunks.append(chunk)
                if sum(len(c) for c in self._stderr_chunks) > 8000:
                    self._stderr_chunks = self._stderr_chunks[-4:]
        except Exception:
            return

    def _stderr_text(self) -> str:
        return b"".join(self._stderr_chunks).decode("utf-8", errors="replace")[-1500:]

    async def _read_message(self, timeout: float) -> Dict[str, Any]:
        if not self._process or not self._process.stdout:
            raise McpError("MCP 进程未启动")
        while True:
            try:
                line = await asyncio.wait_for(self._process.stdout.readline(), timeout=timeout)
            except asyncio.TimeoutError as exc:
                extra = self._stderr_text()
                hint = f"；stderr: {extra}" if extra else ""
                raise McpError(f"MCP stdio 读取超时 ({timeout}s){hint}") from exc
            if not line:
                extra = self._stderr_text()
                hint = f"；stderr: {extra}" if extra else ""
                raise McpError(f"MCP 进程已退出{hint}")
            try:
                msg = decode_ndjson_line(line)
            except Exception as exc:
                extra = self._stderr_text()
                hint = f"；stderr: {extra}" if extra else ""
                raise McpError(f"MCP stdio JSON 解析失败: {exc}{hint}") from exc
            if msg is None:
                continue
            if "id" not in msg and msg.get("method"):
                continue
            return msg

    async def _write(self, payload: Dict[str, Any]) -> None:
        if not self._process or not self._process.stdin:
            raise McpError("MCP 进程未启动")
        self._process.stdin.write(encode_ndjson(payload))
        await self._process.stdin.drain()

    async def initialize(self) -> Dict[str, Any]:
        req_id = self._next_id
        self._next_id += 1
        await self._write(
            make_request(
                req_id,
                "initialize",
                {
                    "protocolVersion": PREFERRED_PROTOCOL,
                    "capabilities": {},
                    "clientInfo": CLIENT_INFO,
                },
            )
        )
        try:
            msg = await self._read_message(timeout=min(15.0, self.timeout_seconds))
        except McpError:
            raise
        result = extract_result(msg)
        await self._write(make_notification("notifications/initialized", {}))
        return result if isinstance(result, dict) else {}

    async def request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        req_id = self._next_id
        self._next_id += 1
        await self._write(make_request(req_id, method, params or {}))
        msg = await self._read_message(timeout=self.timeout_seconds)
        if msg.get("id") not in (None, req_id):
            extra = await self._read_message(timeout=self.timeout_seconds)
            if extra.get("id") == req_id:
                msg = extra
        return extract_result(msg)

    async def close(self) -> None:
        proc = self._process
        self._process = None
        if self._stderr_task:
            self._stderr_task.cancel()
            self._stderr_task = None
        if not proc:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
