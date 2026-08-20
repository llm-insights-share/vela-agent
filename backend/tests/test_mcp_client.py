import asyncio
import json
import os
import sys

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from services.mcp.auth import build_http_headers
from services.mcp.client import call_mcp_tool, discover_mcp_tools
from services.mcp.config import parse_mcp_config, compat_uvx_mcp_args
from services.mcp.jsonrpc import parse_sse_events
from services.mcp.oauth import generate_pkce, parse_www_authenticate
from services.mcp.transports.streamable_http import StreamableHttpSession


STDIO_SCRIPT = os.path.join(os.path.dirname(__file__), "mcp_stdio_echo.py")


def _jsonrpc_reply(msg):
    method = msg.get("method")
    req_id = msg.get("id")
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "serverInfo": {"name": "vela-test-http"},
            },
        }
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": "ping",
                        "description": "Ping tool",
                        "inputSchema": {"type": "object", "properties": {}},
                    }
                ]
            },
        }
    if method == "tools/call":
        args = (msg.get("params") or {}).get("arguments") or {}
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"content": [{"type": "text", "text": f"pong:{args.get('n', '')}"}]},
        }
    if req_id is not None:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "unknown"}}
    return None


def _require_bearer(request):
    auth = request.headers.get("authorization") or ""
    return auth == "Bearer secret-token"


async def streamable_endpoint(request):
    if request.headers.get("x-require-auth") == "1" and not _require_bearer(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    payload = await request.json()
    reply = _jsonrpc_reply(payload)
    headers = {"Mcp-Session-Id": "sess-1"}
    if reply is None:
        return Response(status_code=202, headers=headers)
    if request.headers.get("x-sse-body") == "1":
        body = f"event: message\ndata: {json.dumps(reply)}\n\n"
        return Response(body, media_type="text/event-stream", headers=headers)
    return JSONResponse(reply, headers=headers)


_SSE_QUEUE: asyncio.Queue | None = None


async def sse_get(request):
    global _SSE_QUEUE
    if request.headers.get("x-require-auth") == "1" and not _require_bearer(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    _SSE_QUEUE = asyncio.Queue()

    async def gen():
        yield "event: endpoint\ndata: /messages\n\n"
        while True:
            try:
                reply = await asyncio.wait_for(_SSE_QUEUE.get(), timeout=0.2)
            except asyncio.TimeoutError:
                continue
            if reply is None:
                break
            yield f"event: message\ndata: {json.dumps(reply)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


async def sse_post(request):
    payload = await request.json()
    reply = _jsonrpc_reply(payload)
    if reply is not None and _SSE_QUEUE is not None:
        await _SSE_QUEUE.put(reply)
    return Response(status_code=202)


def make_asgi_app():
    return Starlette(routes=[
        Route("/mcp", streamable_endpoint, methods=["POST"]),
        Route("/sse", sse_get, methods=["GET"]),
        Route("/messages", sse_post, methods=["POST"]),
    ])


@pytest.mark.asyncio
async def test_stdio_discover_and_call():
    cfg = {
        "transport": "stdio",
        "mcp_command": sys.executable,
        "mcp_args": [STDIO_SCRIPT],
    }
    listed = await discover_mcp_tools(cfg, timeout_seconds=15)
    assert listed["success"] is True
    assert listed["tools"][0]["name"] == "echo"
    called = await call_mcp_tool(cfg, "echo", {"text": "hello"}, timeout_seconds=15)
    assert called["success"] is True
    assert "hello" in called["result"]


@pytest.mark.asyncio
async def test_streamable_http_json_and_bearer():
    transport = httpx.ASGITransport(app=make_asgi_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://mcp.test") as client:
        session = StreamableHttpSession(
            parse_mcp_config({
                "transport": "streamable_http",
                "mcp_url": "http://mcp.test/mcp",
                "auth_type": "bearer",
                "auth_token": "secret-token",
                "mcp_headers": {"x-require-auth": "1"},
            }),
            timeout_seconds=10,
            http=client,
        )
        await session.start()
        tools = await session.request("tools/list", {})
        assert tools["tools"][0]["name"] == "ping"
        result = await session.request("tools/call", {"name": "ping", "arguments": {"n": 7}})
        assert "pong:7" in result["content"][0]["text"]
        await session.close()


@pytest.mark.asyncio
async def test_streamable_http_sse_body():
    transport = httpx.ASGITransport(app=make_asgi_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://mcp.test") as client:
        session = StreamableHttpSession(
            parse_mcp_config({
                "transport": "streamable_http",
                "mcp_url": "http://mcp.test/mcp",
                "mcp_headers": {"x-sse-body": "1"},
            }),
            timeout_seconds=10,
            http=client,
        )
        await session.start()
        tools = await session.request("tools/list", {})
        assert tools["tools"][0]["name"] == "ping"
        await session.close()


@pytest.mark.asyncio
async def test_sse_transport_discover():
    import socket
    import uvicorn

    global _SSE_QUEUE
    _SSE_QUEUE = None
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    config = uvicorn.Config(make_asgi_app(), host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(50):
            if server.started:
                break
            await asyncio.sleep(0.05)
        listed = await discover_mcp_tools({
            "transport": "sse",
            "mcp_url": f"http://127.0.0.1:{port}/sse",
        }, timeout_seconds=15)
        assert listed["success"] is True, listed
        assert listed["tools"][0]["name"] == "ping"
    finally:
        server.should_exit = True
        await task


def test_parse_config_defaults_to_stdio():
    cfg = parse_mcp_config({"mcp_command": "npx", "mcp_args": ["-y", "x"]})
    assert cfg.transport == "stdio"
    assert cfg.validate() is None


def test_parse_config_requires_url_for_http():
    cfg = parse_mcp_config({"transport": "streamable_http"})
    assert cfg.validate()


def test_bearer_header_injection():
    cfg = parse_mcp_config({
        "transport": "sse",
        "mcp_url": "https://example.com/sse",
        "auth_type": "bearer",
        "auth_token": "abc",
        "mcp_headers": {"X-Custom": "1"},
    })
    headers = build_http_headers(cfg)
    assert headers["Authorization"] == "Bearer abc"
    assert headers["X-Custom"] == "1"


def test_pkce_and_www_authenticate():
    verifier, challenge = generate_pkce()
    assert verifier
    assert challenge
    parsed = parse_www_authenticate(
        'Bearer realm="mcp", resource_metadata="https://ex.com/.well-known/oauth-protected-resource"'
    )
    assert parsed["resource_metadata"] == "https://ex.com/.well-known/oauth-protected-resource"


def test_compat_uvx_mcp_args_pins_sqlite_sdk():
    pinned = compat_uvx_mcp_args("uvx", ["mcp-server-sqlite", "--db-path", "./data.db"])
    assert pinned[:2] == ["--with", "mcp<2"]
    assert pinned[2:] == ["mcp-server-sqlite", "--db-path", "./data.db"]
    already = ["--with", "mcp<2", "mcp-server-sqlite"]
    assert compat_uvx_mcp_args("uvx", already) == already
    untouched = ["mcp-server-fetch"]
    assert compat_uvx_mcp_args("uvx", untouched) == untouched


def test_parse_sse_events():
    events = parse_sse_events("event: endpoint\ndata: /messages?sid=1\n\nevent: message\ndata: {\"ok\":1}\n\n")
    assert events[0]["event"] == "endpoint"
    assert "/messages" in events[0]["data"]
    assert events[1]["event"] == "message"
