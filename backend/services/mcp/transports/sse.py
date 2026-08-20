from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional
from urllib.parse import urljoin, urlparse

import httpx

from services.mcp.auth import build_http_headers
from services.mcp.config import CLIENT_INFO, FALLBACK_PROTOCOL, McpConnectionConfig
from services.mcp.jsonrpc import (
    McpAuthError,
    McpError,
    extract_result,
    make_notification,
    make_request,
)


class SseSession:
    """MCP 2024-11-05 HTTP+SSE transport."""

    def __init__(self, cfg: McpConnectionConfig, timeout_seconds: float = 30, http: Optional[httpx.AsyncClient] = None):
        self.cfg = cfg
        self.timeout_seconds = timeout_seconds
        self._owns_http = http is None
        self._http = http
        self._next_id = 1
        self._post_url = ""
        self._pending: Dict[Any, asyncio.Future] = {}
        self._reader_task: Optional[asyncio.Task] = None
        self._endpoint_ready = asyncio.Event()
        self._reader_error: Optional[BaseException] = None
        self._closed = False

    async def __aenter__(self) -> "SseSession":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def start(self) -> None:
        if self._http is None:
            timeout = httpx.Timeout(
                connect=10.0,
                read=None,
                write=30.0,
                pool=10.0,
            )
            self._http = httpx.AsyncClient(timeout=timeout, follow_redirects=True)
        self._reader_task = asyncio.create_task(self._read_sse())
        try:
            await asyncio.wait_for(self._endpoint_ready.wait(), timeout=min(20.0, self.timeout_seconds + 5))
        except asyncio.TimeoutError as exc:
            await self.close()
            raise McpError("等待 SSE endpoint 事件超时") from exc
        if self._reader_error:
            err = self._reader_error
            await self.close()
            raise err
        await self.initialize()

    def _headers(self, *, sse: bool = False) -> Dict[str, str]:
        headers = build_http_headers(self.cfg)
        if sse:
            headers["Accept"] = "text/event-stream"
            headers["Cache-Control"] = "no-cache"
        else:
            headers["Content-Type"] = "application/json"
            headers["Accept"] = "application/json, text/event-stream"
        return headers

    def _resolve_post_url(self, data: str) -> str:
        data = (data or "").strip()
        if data.startswith("http://") or data.startswith("https://"):
            return data
        return urljoin(self.cfg.url, data)

    async def _read_sse(self) -> None:
        assert self._http is not None
        try:
            async with self._http.stream("GET", self.cfg.url, headers=self._headers(sse=True)) as resp:
                if resp.status_code == 401:
                    self._reader_error = McpAuthError(
                        "MCP 服务器需要认证（401）",
                        www_authenticate=resp.headers.get("www-authenticate") or "",
                    )
                    self._endpoint_ready.set()
                    return
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", errors="replace")[:500]
                    self._reader_error = McpError(
                        f"MCP SSE {resp.status_code}: {body}", status_code=resp.status_code
                    )
                    self._endpoint_ready.set()
                    return
                event_type = "message"
                data_lines: list[str] = []
                async for line in resp.aiter_lines():
                    if self._closed:
                        break
                    if line is None:
                        continue
                    if line.startswith(":"):
                        continue
                    if line == "":
                        await self._dispatch_event(event_type, "\n".join(data_lines))
                        event_type = "message"
                        data_lines = []
                        continue
                    if line.startswith("event:"):
                        event_type = line[6:].strip() or "message"
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not self._closed:
                self._reader_error = McpError(f"SSE 连接中断: {exc}")
                for fut in list(self._pending.values()):
                    if not fut.done():
                        fut.set_exception(self._reader_error)
            if not self._endpoint_ready.is_set():
                self._endpoint_ready.set()

    async def _dispatch_event(self, event_type: str, data: str) -> None:
        if event_type == "endpoint":
            self._post_url = self._resolve_post_url(data)
            self._endpoint_ready.set()
            return
        if not data.strip():
            return
        try:
            msg = json.loads(data)
        except json.JSONDecodeError:
            return
        if not isinstance(msg, dict):
            return
        if event_type in ("endpoint",) or msg.get("method") == "endpoint":
            return
        req_id = msg.get("id")
        fut = self._pending.get(req_id)
        if fut and not fut.done():
            fut.set_result(msg)

    async def initialize(self) -> Dict[str, Any]:
        result = await self.request(
            "initialize",
            {
                "protocolVersion": FALLBACK_PROTOCOL,
                "capabilities": {},
                "clientInfo": CLIENT_INFO,
            },
        )
        try:
            await self._post(make_notification("notifications/initialized", {}))
        except McpError:
            pass
        return result if isinstance(result, dict) else {}

    async def _post(self, payload: Dict[str, Any]) -> None:
        if not self._post_url:
            raise McpError("SSE 尚未收到 endpoint")
        assert self._http is not None
        resp = await self._http.post(self._post_url, json=payload, headers=self._headers())
        if resp.status_code == 401:
            raise McpAuthError(
                "MCP 服务器需要认证（401）",
                www_authenticate=resp.headers.get("www-authenticate") or "",
            )
        if resp.status_code >= 400:
            raise McpError(f"MCP SSE POST {resp.status_code}: {resp.text[:500]}", status_code=resp.status_code)

    async def request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        req_id = self._next_id
        self._next_id += 1
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[req_id] = fut
        try:
            await self._post(make_request(req_id, method, params or {}))
            msg = await asyncio.wait_for(fut, timeout=self.timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise McpError(f"MCP SSE 等待响应超时 ({self.timeout_seconds}s)") from exc
        finally:
            self._pending.pop(req_id, None)
        return extract_result(msg)

    async def close(self) -> None:
        self._closed = True
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
            self._reader_task = None
        if self._owns_http and self._http is not None:
            await self._http.aclose()
        self._http = None
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()
