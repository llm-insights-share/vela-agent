from __future__ import annotations

from typing import Dict

from services.mcp.config import AUTH_BEARER, AUTH_OAUTH, McpConnectionConfig


def build_http_headers(cfg: McpConnectionConfig) -> Dict[str, str]:
    headers = {k: v for k, v in (cfg.headers or {}).items() if k and v is not None}
    token = (cfg.auth_token or "").strip()
    if cfg.auth_type in (AUTH_BEARER, AUTH_OAUTH) and token:
        if "authorization" not in {k.lower() for k in headers}:
            headers["Authorization"] = f"Bearer {token}"
    return headers
