from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from services.mcp.auth import build_http_headers
from services.mcp.config import CLIENT_INFO, McpConnectionConfig, PREFERRED_PROTOCOL
from services.mcp.jsonrpc import (
    McpAuthError,
    McpError,
    extract_result,
    jsonrpc_from_http_body,
    make_notification,
    make_request,
)


class StreamableHttpSession:
    def __init__(self, cfg: McpConnectionConfig, timeout_seconds: float = 30, http: Optional[httpx.AsyncClient] = None):
        self.cfg = cfg
        self.timeout_seconds = timeout_seconds
        self._owns_http = http is None
        self._http = http
        self._next_id = 1
        self.session_id = ""

    async def __aenter__(self) -> "StreamableHttpSession":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def start(self) -> None:
        if self._http is None:
            timeout = httpx.Timeout(
                connect=10.0,
                read=float(self.timeout_seconds),
                write=30.0,
                pool=10.0,
            )
            self._http = httpx.AsyncClient(timeout=timeout, follow_redirects=True)
        await self.initialize()

    def _headers(self) -> Dict[str, str]:
        headers = build_http_headers(self.cfg)
        headers["Content-Type"] = "application/json"
        headers["Accept"] = "application/json, text/event-stream"
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    async def _post(self, payload: Dict[str, Any]) -> httpx.Response:
        assert self._http is not None
        resp = await self._http.post(self.cfg.url, json=payload, headers=self._headers())
        sid = resp.headers.get("mcp-session-id") or resp.headers.get("Mcp-Session-Id")
        if sid:
            self.session_id = sid
        if resp.status_code == 401:
            raise McpAuthError(
                "MCP 服务器需要认证（401）",
                www_authenticate=resp.headers.get("www-authenticate") or "",
            )
        if resp.status_code >= 400:
            raise McpError(
                f"MCP HTTP {resp.status_code}: {resp.text[:500]}",
                status_code=resp.status_code,
            )
        return resp

    async def initialize(self) -> Dict[str, Any]:
        req_id = self._next_id
        self._next_id += 1
        resp = await self._post(
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
        msg = jsonrpc_from_http_body(resp.headers.get("content-type", ""), resp.text, req_id)
        result = extract_result(msg)
        notify = make_notification("notifications/initialized", {})
        try:
            notify_resp = await self._post(notify)
            if notify_resp.status_code not in (200, 202, 204):
                pass
        except McpError:
            pass
        return result if isinstance(result, dict) else {}

    async def request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        req_id = self._next_id
        self._next_id += 1
        resp = await self._post(make_request(req_id, method, params or {}))
        msg = jsonrpc_from_http_body(resp.headers.get("content-type", ""), resp.text, req_id)
        return extract_result(msg)

    async def close(self) -> None:
        if self._owns_http and self._http is not None:
            await self._http.aclose()
        self._http = None
