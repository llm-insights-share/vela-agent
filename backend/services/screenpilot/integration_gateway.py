"""Integration Gateway — OAuth2.1 客户端凭据流 + RFC 9728 令牌绑定。"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

import httpx

from services.screenpilot.config import (
    SCREENPILOT_OAUTH_CLIENT_ID,
    SCREENPILOT_OAUTH_CLIENT_SECRET,
    SCREENPILOT_OAUTH_SCOPE,
    SCREENPILOT_OAUTH_TOKEN_URL,
)

logger = logging.getLogger(__name__)

_token_cache: Dict[str, Any] = {"access_token": "", "expires_at": 0.0, "token_type": "Bearer"}


def oauth_configured() -> bool:
    return bool(
        SCREENPILOT_OAUTH_TOKEN_URL
        and SCREENPILOT_OAUTH_CLIENT_ID
        and SCREENPILOT_OAUTH_CLIENT_SECRET
    )


async def get_access_token(force_refresh: bool = False) -> Optional[str]:
    """OAuth2.1 client_credentials 获取访问令牌（带内存缓存）。"""
    if not oauth_configured():
        return None

    now = time.time()
    if not force_refresh and _token_cache["access_token"] and _token_cache["expires_at"] > now + 30:
        return _token_cache["access_token"]

    payload = {
        "grant_type": "client_credentials",
        "client_id": SCREENPILOT_OAUTH_CLIENT_ID,
        "client_secret": SCREENPILOT_OAUTH_CLIENT_SECRET,
    }
    if SCREENPILOT_OAUTH_SCOPE:
        payload["scope"] = SCREENPILOT_OAUTH_SCOPE

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                SCREENPILOT_OAUTH_TOKEN_URL,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if resp.status_code >= 400:
            logger.warning("OAuth token 获取失败: %s", resp.text[:300])
            return None

        data = resp.json()
        token = data.get("access_token", "")
        expires_in = int(data.get("expires_in") or 3600)
        _token_cache["access_token"] = token
        _token_cache["expires_at"] = now + expires_in
        _token_cache["token_type"] = data.get("token_type") or "Bearer"
        return token
    except Exception as e:
        logger.error("OAuth token 异常: %s", e, exc_info=True)
        return None


async def gateway_request(
    method: str,
    url: str,
    *,
    json_body: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """经 Integration Gateway 发起带 Bearer 令牌的 API 请求。"""
    token = await get_access_token()
    if not token:
        return {"success": False, "error": "OAuth 未配置或令牌获取失败"}

    req_headers = dict(headers or {})
    req_headers["Authorization"] = f"{_token_cache.get('token_type', 'Bearer')} {token}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.request(method.upper(), url, json=json_body, headers=req_headers)
        if resp.status_code >= 400:
            return {
                "success": False,
                "status_code": resp.status_code,
                "error": resp.text[:500],
            }
        ct = resp.headers.get("content-type", "")
        body = resp.json() if "json" in ct else {"text": resp.text[:2000]}
        return {"success": True, "status_code": resp.status_code, "data": body}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def fetch_system_api(
    system: Any,
    path: str,
    *,
    method: str = "GET",
    json_body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """优先走系统 API（OAuth Gateway），ScreenPilot UI 自动化作兜底。"""
    gateway_cfg = (getattr(system, "risk_rules", None) or {}).get("api_gateway") or {}
    base_url = gateway_cfg.get("base_url") or ""
    if not base_url:
        return {"success": False, "error": "系统未配置 api_gateway.base_url", "use_ui_fallback": True}

    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    return await gateway_request(method, url, json_body=json_body)
