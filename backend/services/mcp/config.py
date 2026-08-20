from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

TRANSPORT_STDIO = "stdio"
TRANSPORT_SSE = "sse"
TRANSPORT_STREAMABLE_HTTP = "streamable_http"

AUTH_NONE = "none"
AUTH_BEARER = "bearer"
AUTH_OAUTH = "oauth"

SUPPORTED_TRANSPORTS = (TRANSPORT_STDIO, TRANSPORT_SSE, TRANSPORT_STREAMABLE_HTTP)
PREFERRED_PROTOCOL = "2025-03-26"
FALLBACK_PROTOCOL = "2024-11-05"
CLIENT_INFO = {"name": "vela-agent", "version": "1.0.0"}


@dataclass
class McpConnectionConfig:
    transport: str = TRANSPORT_STDIO
    command: str = ""
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    url: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    auth_type: str = AUTH_NONE
    auth_token: str = ""
    mcp_server_id: str = ""
    tool_name: str = ""

    def validate(self) -> Optional[str]:
        if self.transport not in SUPPORTED_TRANSPORTS:
            return f"不支持的 MCP 传输方式: {self.transport}"
        if self.transport == TRANSPORT_STDIO:
            if not self.command:
                return "MCP 工具缺少 command 配置"
        else:
            if not (self.url or "").strip():
                return "MCP 远程传输缺少 url 配置"
            parsed = urlparse(self.url.strip())
            if parsed.scheme not in ("http", "https"):
                return "MCP URL 仅支持 http/https"
        if self.auth_type not in (AUTH_NONE, AUTH_BEARER, AUTH_OAUTH):
            return f"不支持的认证方式: {self.auth_type}"
        return None


def _as_str_dict(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(k): "" if v is None else str(v) for k, v in value.items()}


def _as_str_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(x) for x in value]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def compat_uvx_mcp_args(command: str, args: Optional[List[str]] = None) -> List[str]:
    """Keep mcp-server-sqlite on MCP SDK 1.x; SDK 2.0 removed Server.list_resources."""
    import os

    cmd = os.path.basename(command or "")
    out = list(args or [])
    if cmd != "uvx":
        return out
    if "mcp-server-sqlite" not in out:
        return out
    if any("mcp<2" in str(a) or str(a).startswith("mcp<") for a in out):
        return out
    return ["--with", "mcp<2", *out]


def parse_mcp_config(config: Optional[Dict[str, Any]]) -> McpConnectionConfig:
    cfg = config or {}
    transport = (cfg.get("transport") or "").strip() or TRANSPORT_STDIO
    if transport == "http":
        transport = TRANSPORT_STREAMABLE_HTTP
    auth_type = (cfg.get("auth_type") or AUTH_NONE).strip() or AUTH_NONE
    token = cfg.get("auth_token") or cfg.get("bearer_token") or ""
    return McpConnectionConfig(
        transport=transport,
        command=cfg.get("mcp_command", "") or cfg.get("command", "") or "",
        args=_as_str_list(cfg.get("mcp_args") or cfg.get("args")),
        env=_as_str_dict(cfg.get("mcp_env") or cfg.get("env")),
        url=(cfg.get("mcp_url") or cfg.get("url") or "").strip(),
        headers=_as_str_dict(cfg.get("mcp_headers") or cfg.get("headers")),
        auth_type=auth_type,
        auth_token=str(token or ""),
        mcp_server_id=str(cfg.get("mcp_server_id") or ""),
        tool_name=str(cfg.get("mcp_tool_name") or cfg.get("server_name") or ""),
    )


def connection_source_label(cfg: McpConnectionConfig) -> str:
    if cfg.transport == TRANSPORT_STDIO:
        parts = [cfg.command, *cfg.args]
        return " ".join(p for p in parts if p).strip() or "stdio"
    host = urlparse(cfg.url).netloc or cfg.url
    return host or cfg.transport
