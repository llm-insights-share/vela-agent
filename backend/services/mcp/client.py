from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional

from services.mcp.config import (
    TRANSPORT_SSE,
    TRANSPORT_STDIO,
    TRANSPORT_STREAMABLE_HTTP,
    McpConnectionConfig,
    parse_mcp_config,
)
from services.mcp.jsonrpc import McpError
from services.mcp.transports.sse import SseSession
from services.mcp.transports.stdio import StdioSession
from services.mcp.transports.streamable_http import StreamableHttpSession


def _open_session(cfg: McpConnectionConfig, timeout_seconds: float):
    if cfg.transport == TRANSPORT_STDIO:
        return StdioSession(cfg, timeout_seconds=timeout_seconds)
    if cfg.transport == TRANSPORT_SSE:
        return SseSession(cfg, timeout_seconds=timeout_seconds)
    if cfg.transport in (TRANSPORT_STREAMABLE_HTTP, "http"):
        return StreamableHttpSession(cfg, timeout_seconds=timeout_seconds)
    raise McpError(f"不支持的 MCP 传输方式: {cfg.transport}")


@asynccontextmanager
async def mcp_session(cfg: McpConnectionConfig, timeout_seconds: float = 30) -> AsyncIterator[Any]:
    err = cfg.validate()
    if err:
        raise McpError(err)
    session = _open_session(cfg, timeout_seconds)
    await session.start()
    try:
        yield session
    finally:
        await session.close()


def _tool_info_list(raw_tools: Any) -> List[Dict[str, Any]]:
    tools = raw_tools if isinstance(raw_tools, list) else []
    items: List[Dict[str, Any]] = []
    for t in tools:
        if not isinstance(t, dict):
            continue
        items.append(
            {
                "name": t.get("name", "") or "",
                "description": t.get("description", "") or "",
                "inputSchema": t.get("inputSchema") or {},
            }
        )
    return items


def _content_to_text(result: Any) -> str:
    import json

    if not isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False)
    content = result.get("content", [])
    parts: List[str] = []
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", "") or "")
            elif isinstance(item, str):
                parts.append(item)
    if parts:
        return "\n".join(parts)
    return json.dumps(result, ensure_ascii=False)


async def discover_mcp_tools(
    config: Optional[Dict[str, Any]] = None,
    *,
    timeout_seconds: int = 30,
    **legacy_kwargs: Any,
) -> Dict[str, Any]:
    raw = dict(config or {})
    if legacy_kwargs:
        if "command" in legacy_kwargs:
            raw.setdefault("mcp_command", legacy_kwargs.get("command") or "")
        if "args" in legacy_kwargs:
            raw.setdefault("mcp_args", legacy_kwargs.get("args") or [])
        if "env" in legacy_kwargs:
            raw.setdefault("mcp_env", legacy_kwargs.get("env") or {})
        if "url" in legacy_kwargs:
            raw.setdefault("mcp_url", legacy_kwargs.get("url") or "")
        if "headers" in legacy_kwargs:
            raw.setdefault("mcp_headers", legacy_kwargs.get("headers") or {})
        if "transport" in legacy_kwargs:
            raw.setdefault("transport", legacy_kwargs.get("transport"))
        if "auth_type" in legacy_kwargs:
            raw.setdefault("auth_type", legacy_kwargs.get("auth_type"))
        if "auth_token" in legacy_kwargs:
            raw.setdefault("auth_token", legacy_kwargs.get("auth_token"))
    cfg = parse_mcp_config(raw)
    try:
        async with mcp_session(cfg, timeout_seconds=float(timeout_seconds)) as session:
            result = await session.request("tools/list", {})
        tools = _tool_info_list((result or {}).get("tools") if isinstance(result, dict) else [])
        return {"success": True, "tools": tools, "total": len(tools)}
    except McpError as exc:
        return {"success": False, "error": str(exc), "status_code": exc.status_code}
    except Exception as exc:
        return {"success": False, "error": f"获取工具列表异常: {exc}"}


async def call_mcp_tool(
    config: Dict[str, Any],
    tool_name: str,
    arguments: Dict[str, Any],
    timeout_seconds: int = 60,
) -> Dict[str, Any]:
    cfg = parse_mcp_config(config)
    try:
        async with mcp_session(cfg, timeout_seconds=float(timeout_seconds)) as session:
            result = await session.request(
                "tools/call",
                {"name": tool_name, "arguments": arguments or {}},
            )
        if isinstance(result, dict) and result.get("isError"):
            return {"success": False, "error": _content_to_text(result) or "MCP 工具返回错误"}
        text = _content_to_text(result)
        return {"success": True, "result": text, "raw": result}
    except McpError as exc:
        return {"success": False, "error": str(exc), "status_code": exc.status_code}
    except Exception as exc:
        return {"success": False, "error": f"MCP 调用异常: {exc}"}
