from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode, urljoin, urlparse

import httpx
from sqlalchemy.orm import Session

from services.mcp.crypto import decrypt_secret, encrypt_secret
from services.mcp.jsonrpc import McpAuthError, McpError


def load_oauth_settings() -> Dict[str, str]:
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    yaml_path = os.path.join(backend_dir, "vela.yaml")
    redirect = os.getenv("MCP_OAUTH_REDIRECT_URI", "").strip()
    if os.path.exists(yaml_path):
        try:
            import yaml

            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            mcp = (data.get("mcp") or {}).get("oauth") or {}
            redirect = redirect or str(mcp.get("redirect_uri") or "").strip()
        except Exception:
            pass
    return {"redirect_uri": redirect}


def generate_pkce() -> Tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def parse_www_authenticate(header: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    if not header:
        return result
    parts = header.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() in ("bearer", "dpop"):
        header = parts[1]
    for chunk in header.split(","):
        item = chunk.strip()
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        result[key.strip().strip('"')] = value.strip().strip('"')
    return result


async def fetch_json(url: str, timeout: float = 15.0) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.get(url, headers={"Accept": "application/json"})
        if resp.status_code >= 400:
            raise McpError(f"获取 OAuth 元数据失败 HTTP {resp.status_code}: {url}")
        data = resp.json()
        if not isinstance(data, dict):
            raise McpError("OAuth 元数据不是 JSON 对象")
        return data


def _origin(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


async def discover_authorization_server(mcp_url: str, www_authenticate: str = "") -> Dict[str, Any]:
    params = parse_www_authenticate(www_authenticate)
    resource_meta_url = params.get("resource_metadata") or params.get("resource")
    origin = _origin(mcp_url)
    candidates = []
    if resource_meta_url:
        candidates.append(resource_meta_url)
    if origin:
        parsed = urlparse(mcp_url)
        path = parsed.path.rstrip("/")
        if path:
            candidates.append(urljoin(origin + "/", f".well-known/oauth-protected-resource{path}"))
        candidates.append(urljoin(origin + "/", ".well-known/oauth-protected-resource"))
        candidates.append(urljoin(origin + "/", ".well-known/oauth-authorization-server"))
        candidates.append(urljoin(origin + "/", ".well-known/openid-configuration"))

    resource_meta: Dict[str, Any] = {}
    as_meta: Dict[str, Any] = {}
    last_error = "未找到 OAuth 元数据"
    for url in candidates:
        try:
            data = await fetch_json(url)
        except Exception as exc:
            last_error = str(exc)
            continue
        if data.get("authorization_endpoint") and data.get("token_endpoint"):
            as_meta = data
            break
        if data.get("authorization_servers") or data.get("resource"):
            resource_meta = data
            servers = data.get("authorization_servers") or []
            if servers:
                as_url = str(servers[0]).rstrip("/")
                meta_urls = []
                if as_url.endswith("oauth-authorization-server") or as_url.endswith("openid-configuration"):
                    meta_urls.append(as_url)
                else:
                    meta_urls.extend([
                        as_url + "/.well-known/oauth-authorization-server",
                        as_url + "/.well-known/openid-configuration",
                    ])
                for meta_url in meta_urls:
                    try:
                        as_meta = await fetch_json(meta_url)
                        if as_meta.get("token_endpoint"):
                            break
                    except Exception:
                        continue
                if as_meta.get("token_endpoint"):
                    break
            if not as_meta:
                continue
    if not as_meta.get("authorization_endpoint") or not as_meta.get("token_endpoint"):
        raise McpError(last_error)
    return {
        "resource_metadata": resource_meta,
        "as_metadata": as_meta,
        "resource": resource_meta.get("resource") or origin or mcp_url,
    }


async def register_client(as_meta: Dict[str, Any], redirect_uri: str, client_name: str = "Vela Agent") -> Dict[str, str]:
    endpoint = as_meta.get("registration_endpoint")
    if not endpoint:
        return {}
    body = {
        "client_name": client_name,
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "client_uri": "https://vela.local",
    }
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        resp = await client.post(endpoint, json=body, headers={"Accept": "application/json"})
        if resp.status_code >= 400:
            return {}
        data = resp.json() if resp.content else {}
    if not isinstance(data, dict) or not data.get("client_id"):
        return {}
    return {
        "client_id": str(data.get("client_id") or ""),
        "client_secret": str(data.get("client_secret") or ""),
    }


def build_authorization_url(
    as_meta: Dict[str, Any],
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    resource: str = "",
    scope: str = "",
) -> str:
    endpoint = as_meta.get("authorization_endpoint")
    if not endpoint:
        raise McpError("授权服务器缺少 authorization_endpoint")
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if scope:
        params["scope"] = scope
    if resource:
        params["resource"] = resource
    return f"{endpoint}?{urlencode(params)}"


async def exchange_code(
    as_meta: Dict[str, Any],
    *,
    code: str,
    redirect_uri: str,
    client_id: str,
    client_secret: str = "",
    code_verifier: str,
    resource: str = "",
) -> Dict[str, Any]:
    token_url = as_meta.get("token_endpoint")
    if not token_url:
        raise McpError("授权服务器缺少 token_endpoint")
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": code_verifier,
    }
    if resource:
        data["resource"] = resource
    headers = {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}
    auth = (client_id, client_secret) if client_secret else None
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        resp = await client.post(token_url, data=data, headers=headers, auth=auth)
        if resp.status_code >= 400:
            raise McpError(f"换取 access_token 失败: {resp.text[:400]}")
        payload = resp.json()
    if not isinstance(payload, dict) or not payload.get("access_token"):
        raise McpError("token 响应缺少 access_token")
    return payload


async def refresh_access_token(
    as_meta: Dict[str, Any],
    *,
    refresh_token: str,
    client_id: str,
    client_secret: str = "",
    resource: str = "",
) -> Dict[str, Any]:
    token_url = as_meta.get("token_endpoint")
    if not token_url:
        raise McpError("授权服务器缺少 token_endpoint")
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }
    if resource:
        data["resource"] = resource
    auth = (client_id, client_secret) if client_secret else None
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        resp = await client.post(
            token_url,
            data=data,
            headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
            auth=auth,
        )
        if resp.status_code >= 400:
            raise McpAuthError(f"刷新 access_token 失败: {resp.text[:400]}")
        payload = resp.json()
    if not isinstance(payload, dict) or not payload.get("access_token"):
        raise McpAuthError("刷新 token 响应缺少 access_token")
    return payload


def store_tokens(cred, token_payload: Dict[str, Any]) -> None:
    from models import now_utc

    cred.access_token_enc = encrypt_secret(str(token_payload.get("access_token") or ""))
    refresh = token_payload.get("refresh_token")
    if refresh:
        cred.refresh_token_enc = encrypt_secret(str(refresh))
    expires_in = int(token_payload.get("expires_in") or 3600)
    cred.expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(expires_in - 30, 30))
    cred.scope = str(token_payload.get("scope") or cred.scope or "")
    cred.token_type = str(token_payload.get("token_type") or "Bearer")
    cred.updated_at = now_utc()


def apply_discovered_metadata(cred, discovered: Dict[str, Any], client: Dict[str, str], redirect_uri: str) -> None:
    as_meta = discovered.get("as_metadata") or {}
    cred.authorization_endpoint = as_meta.get("authorization_endpoint") or ""
    cred.token_endpoint = as_meta.get("token_endpoint") or ""
    cred.registration_endpoint = as_meta.get("registration_endpoint") or ""
    cred.as_metadata_json = json.dumps(as_meta, ensure_ascii=False)
    cred.resource = discovered.get("resource") or cred.resource or ""
    cred.redirect_uri = redirect_uri
    if client.get("client_id"):
        cred.client_id = client["client_id"]
    if client.get("client_secret"):
        cred.client_secret_enc = encrypt_secret(client["client_secret"])


async def ensure_access_token(db: Session, server) -> str:
    from models import McpOAuthCredential, now_utc

    cred = db.query(McpOAuthCredential).filter(McpOAuthCredential.server_id == server.server_id).first()
    if not cred or not cred.access_token_enc:
        raise McpAuthError("MCP Server 尚未完成 OAuth 授权")
    token = decrypt_secret(cred.access_token_enc)
    expires = cred.expires_at
    now = datetime.now(timezone.utc)
    if expires and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if token and expires and expires > now:
        return token
    refresh = decrypt_secret(cred.refresh_token_enc or "")
    if not refresh:
        raise McpAuthError("OAuth 令牌已过期，请重新授权")
    as_meta = {}
    if cred.as_metadata_json:
        try:
            as_meta = json.loads(cred.as_metadata_json)
        except Exception:
            as_meta = {}
    if not as_meta.get("token_endpoint") and cred.token_endpoint:
        as_meta["token_endpoint"] = cred.token_endpoint
    payload = await refresh_access_token(
        as_meta,
        refresh_token=refresh,
        client_id=cred.client_id,
        client_secret=decrypt_secret(cred.client_secret_enc or ""),
        resource=cred.resource or "",
    )
    store_tokens(cred, payload)
    db.add(cred)
    db.commit()
    db.refresh(cred)
    return decrypt_secret(cred.access_token_enc)
