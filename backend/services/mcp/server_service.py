from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from models import McpOAuthCredential, McpServer, Tool, ToolStatus, ToolType, gen_uuid, now_utc
from services.mcp.client import discover_mcp_tools
from services.mcp.config import (
    AUTH_OAUTH,
    TRANSPORT_STDIO,
)
from services.mcp.oauth import ensure_access_token


def server_to_config(server: McpServer, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg: Dict[str, Any] = {
        "transport": server.transport or TRANSPORT_STDIO,
        "mcp_command": server.command or "",
        "mcp_args": server.args or [],
        "mcp_env": server.env or {},
        "mcp_url": server.url or "",
        "mcp_headers": server.headers or {},
        "auth_type": server.auth_type or "none",
        "mcp_server_id": server.server_id,
    }
    if extra:
        cfg.update(extra)
    return cfg


def server_status_payload(server: McpServer, cred: Optional[McpOAuthCredential] = None) -> Dict[str, Any]:
    oauth_status = "not_required"
    if server.auth_type == AUTH_OAUTH:
        if cred and cred.access_token_enc:
            oauth_status = "authorized"
        else:
            oauth_status = "unauthorized"
    source = ""
    if (server.transport or TRANSPORT_STDIO) == TRANSPORT_STDIO:
        parts = [server.command or "", *(server.args or [])]
        source = " ".join(str(p) for p in parts if p)
    else:
        source = urlparse(server.url or "").netloc or (server.url or "")
    return {
        "server_id": server.server_id,
        "name": server.name,
        "display_name": server.display_name or server.name,
        "description": server.description or "",
        "transport": server.transport,
        "command": server.command or "",
        "args": server.args or [],
        "env": server.env or {},
        "url": server.url or "",
        "headers": server.headers or {},
        "auth_type": server.auth_type or "none",
        "status": server.status,
        "last_synced_at": server.last_synced_at,
        "last_error": server.last_error or "",
        "oauth_status": oauth_status,
        "source": source,
        "created_at": server.created_at,
        "updated_at": server.updated_at,
    }


async def connection_config_for_server(db: Session, server: McpServer) -> Dict[str, Any]:
    cfg = server_to_config(server)
    if server.auth_type == AUTH_OAUTH:
        token = await ensure_access_token(db, server)
        cfg["auth_type"] = "bearer"
        cfg["auth_token"] = token
    return cfg


async def resolve_tool_connection(db: Session, tool: Tool) -> Dict[str, Any]:
    config = dict(tool.config or {})
    server_id = getattr(tool, "mcp_server_id", None) or config.get("mcp_server_id")
    if not server_id:
        return config
    server = db.query(McpServer).filter(McpServer.server_id == server_id).first()
    if not server:
        raise McpError("关联的 MCP Server 不存在")
    if server.status == "DISABLED":
        raise McpError("MCP Server 已禁用")
    merged = server_to_config(server, extra=config)
    if server.auth_type == AUTH_OAUTH:
        token = await ensure_access_token(db, server)
        merged["auth_type"] = "bearer"
        merged["auth_token"] = token
    return merged


def _unique_tool_name(db: Session, base: str) -> str:
    name = base
    n = 2
    while db.query(Tool).filter(Tool.name == name).first():
        name = f"{base}_{n}"
        n += 1
    return name


async def sync_server_tools(db: Session, server: McpServer) -> Dict[str, Any]:
    cfg = await connection_config_for_server(db, server)
    discovered = await discover_mcp_tools(cfg, timeout_seconds=45)
    if not discovered.get("success"):
        server.last_error = discovered.get("error") or "同步失败"
        server.status = "ERROR"
        server.updated_at = now_utc()
        db.commit()
        return {"success": False, "error": server.last_error}

    remote_tools: List[Dict[str, Any]] = discovered.get("tools") or []
    existing = db.query(Tool).filter(Tool.mcp_server_id == server.server_id).all()
    by_remote_name = {}
    for t in existing:
        remote = (t.config or {}).get("mcp_tool_name") or t.name
        by_remote_name[remote] = t

    created = 0
    updated = 0
    seen = set()
    prefix = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in server.name) or "mcp"
    for item in remote_tools:
        remote_name = item.get("name") or ""
        if not remote_name:
            continue
        seen.add(remote_name)
        schema = item.get("inputSchema") or {"type": "object", "properties": {}, "required": []}
        desc = item.get("description") or f"MCP 工具: {remote_name}"
        tool = by_remote_name.get(remote_name)
        tool_config = {
            "mcp_server_id": server.server_id,
            "mcp_tool_name": remote_name,
            "transport": server.transport,
        }
        if tool:
            tool.display_name = tool.display_name or remote_name
            tool.description = desc
            tool.parameters_schema = schema
            tool.config = tool_config
            tool.status = ToolStatus.ACTIVE
            tool.updated_at = now_utc()
            updated += 1
        else:
            tool = Tool(
                tool_id=gen_uuid(),
                name=_unique_tool_name(db, f"{prefix}_{remote_name}"),
                display_name=remote_name,
                description=desc,
                tool_type=ToolType.MCP,
                config=tool_config,
                parameters_schema=schema,
                mcp_server_id=server.server_id,
            )
            db.add(tool)
            created += 1

    removed = 0
    for remote_name, tool in by_remote_name.items():
        if remote_name not in seen:
            tool.status = ToolStatus.INACTIVE
            tool.updated_at = now_utc()
            removed += 1

    server.last_synced_at = now_utc()
    server.last_error = ""
    server.status = "ACTIVE"
    server.updated_at = now_utc()
    db.commit()
    return {
        "success": True,
        "created": created,
        "updated": updated,
        "deactivated": removed,
        "total": len(remote_tools),
        "tools": remote_tools,
    }
