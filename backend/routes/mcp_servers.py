from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from database import get_db
from models import McpOAuthCredential, McpOAuthState, McpServer, Tool, gen_uuid, now_utc
from schemas import McpOAuthStartRequest, McpServerCreate, McpServerUpdate, McpToolLlmTestRequest, McpToolTestRequest
from services.mcp.config import AUTH_OAUTH, TRANSPORT_SSE, TRANSPORT_STDIO, TRANSPORT_STREAMABLE_HTTP, parse_mcp_config
from services.mcp.crypto import decrypt_secret
from services.mcp.jsonrpc import McpAuthError, McpError
from services.mcp.oauth import (
    apply_discovered_metadata,
    build_authorization_url,
    discover_authorization_server,
    exchange_code,
    generate_pkce,
    load_oauth_settings,
    register_client,
    store_tokens,
)
from services.mcp.server_service import (
    connection_config_for_server,
    server_status_payload,
    sync_server_tools,
)

router = APIRouter(prefix="/api/v1/mcp/servers", tags=["mcp-servers"])

_VALID_TRANSPORTS = {TRANSPORT_STDIO, TRANSPORT_SSE, TRANSPORT_STREAMABLE_HTTP, "http"}


def _tool_count(db: Session, server_id: str) -> int:
    return db.query(Tool).filter(Tool.mcp_server_id == server_id).count()


def _serialize(db: Session, server: McpServer) -> dict:
    cred = db.query(McpOAuthCredential).filter(McpOAuthCredential.server_id == server.server_id).first()
    payload = server_status_payload(server, cred)
    payload["tool_count"] = _tool_count(db, server.server_id)
    return payload


def _validate_connection_fields(transport: str, command: str, url: str) -> None:
    cfg = parse_mcp_config({
        "transport": transport,
        "mcp_command": command,
        "mcp_url": url,
    })
    err = cfg.validate()
    if err:
        raise HTTPException(status_code=400, detail=err)


@router.get("")
def list_servers(db: Session = Depends(get_db)):
    servers = (
        db.query(McpServer)
        .filter(McpServer.owner_user_id.is_(None))
        .order_by(McpServer.created_at.desc())
        .all()
    )
    return {"items": [_serialize(db, s) for s in servers], "total": len(servers)}


@router.post("", status_code=201)
def create_server(data: McpServerCreate, db: Session = Depends(get_db)):
    transport = data.transport if data.transport != "http" else TRANSPORT_STREAMABLE_HTTP
    if transport not in _VALID_TRANSPORTS:
        raise HTTPException(status_code=400, detail="不支持的传输方式")
    _validate_connection_fields(transport, data.command, data.url)
    existing = db.query(McpServer).filter(McpServer.name == data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="MCP Server 名称已存在")
    server = McpServer(
        server_id=gen_uuid(),
        name=data.name,
        display_name=data.display_name or data.name,
        description=data.description,
        transport=transport,
        command=data.command,
        args=data.args or [],
        env=data.env or {},
        url=data.url,
        headers=data.headers or {},
        auth_type=data.auth_type or "none",
    )
    db.add(server)
    db.commit()
    db.refresh(server)
    return _serialize(db, server)


@router.get("/{server_id}")
def get_server(server_id: str, db: Session = Depends(get_db)):
    server = db.query(McpServer).filter(McpServer.server_id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="MCP Server 不存在")
    return _serialize(db, server)


@router.put("/{server_id}")
def update_server(server_id: str, data: McpServerUpdate, db: Session = Depends(get_db)):
    server = db.query(McpServer).filter(McpServer.server_id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="MCP Server 不存在")
    fields = data.model_dump(exclude_unset=True)
    if fields.get("transport") == "http":
        fields["transport"] = TRANSPORT_STREAMABLE_HTTP
    for key, value in fields.items():
        setattr(server, key, value)
    _validate_connection_fields(server.transport, server.command or "", server.url or "")
    server.updated_at = now_utc()
    db.commit()
    db.refresh(server)
    return _serialize(db, server)


@router.delete("/{server_id}")
def delete_server(server_id: str, db: Session = Depends(get_db)):
    server = db.query(McpServer).filter(McpServer.server_id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="MCP Server 不存在")
    tools = db.query(Tool).filter(Tool.mcp_server_id == server_id).all()
    for tool in tools:
        tool.mcp_server_id = None
        cfg = dict(tool.config or {})
        cfg.pop("mcp_server_id", None)
        tool.config = cfg
    db.query(McpOAuthState).filter(McpOAuthState.server_id == server_id).delete()
    db.query(McpOAuthCredential).filter(McpOAuthCredential.server_id == server_id).delete()
    db.delete(server)
    db.commit()
    return {"message": "MCP Server 已删除", "unlinked_tools": len(tools)}


@router.post("/{server_id}/discover")
async def discover_server(server_id: str, db: Session = Depends(get_db)):
    from services.mcp.client import discover_mcp_tools

    server = db.query(McpServer).filter(McpServer.server_id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="MCP Server 不存在")
    try:
        cfg = await connection_config_for_server(db, server)
    except McpAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except McpError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return await discover_mcp_tools(cfg, timeout_seconds=45)


@router.post("/{server_id}/test-tool")
async def test_server_tool(
    server_id: str,
    data: McpToolTestRequest,
    db: Session = Depends(get_db),
):
    from services.mcp.client import call_mcp_tool

    server = db.query(McpServer).filter(McpServer.server_id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="MCP Server 不存在")
    if not (data.tool_name or "").strip():
        raise HTTPException(status_code=400, detail="tool_name 必填")
    try:
        cfg = await connection_config_for_server(db, server)
    except McpAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except McpError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    result = await call_mcp_tool(
        cfg,
        data.tool_name.strip(),
        data.arguments or {},
        timeout_seconds=60,
    )
    if not result.get("success"):
        status = result.get("status_code")
        if status in (401, 403):
            raise HTTPException(status_code=status, detail=result.get("error") or "调用失败")
    return result


@router.post("/{server_id}/test-tool-llm")
async def test_server_tool_llm(
    server_id: str,
    data: McpToolLlmTestRequest,
    db: Session = Depends(get_db),
):
    from services.mcp.client import call_mcp_tool
    from services.mcp_tool_llm_test import run_mcp_tool_llm_test

    server = db.query(McpServer).filter(McpServer.server_id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="MCP Server 不存在")
    try:
        cfg = await connection_config_for_server(db, server)
    except McpAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except McpError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    async def _exec(tool_name: str, arguments: dict):
        return await call_mcp_tool(
            cfg,
            tool_name,
            arguments or {},
            timeout_seconds=60,
        )

    return await run_mcp_tool_llm_test(
        db,
        tool_name=data.tool_name,
        instruction=data.instruction,
        model_service_id=data.model_service_id,
        input_schema=data.input_schema or {},
        execute_tool=_exec,
    )


@router.post("/{server_id}/sync")
async def sync_server(server_id: str, db: Session = Depends(get_db)):
    server = db.query(McpServer).filter(McpServer.server_id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="MCP Server 不存在")
    try:
        result = await sync_server_tools(db, server)
    except McpAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except McpError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@router.post("/{server_id}/oauth/start")
async def start_oauth(
    server_id: str,
    data: McpOAuthStartRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    server = db.query(McpServer).filter(McpServer.server_id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="MCP Server 不存在")
    if server.transport == TRANSPORT_STDIO:
        raise HTTPException(status_code=400, detail="stdio 传输不支持 OAuth")
    if not server.url:
        raise HTTPException(status_code=400, detail="请先配置 MCP URL")

    settings = load_oauth_settings()
    redirect_uri = settings.get("redirect_uri") or str(request.base_url).rstrip("/") + "/api/v1/mcp/oauth/callback"
    try:
        discovered = await discover_authorization_server(server.url)
    except McpError as exc:
        raise HTTPException(status_code=400, detail=f"发现 OAuth 元数据失败: {exc}")

    cred = db.query(McpOAuthCredential).filter(McpOAuthCredential.server_id == server_id).first()
    if not cred:
        cred = McpOAuthCredential(credential_id=gen_uuid(), server_id=server_id)
        db.add(cred)

    client = {}
    if data.client_id:
        client = {"client_id": data.client_id}
    elif cred.client_id:
        client = {"client_id": cred.client_id, "client_secret": decrypt_secret(cred.client_secret_enc or "")}
    else:
        client = await register_client(discovered.get("as_metadata") or {}, redirect_uri)
    if not client.get("client_id"):
        raise HTTPException(status_code=400, detail="授权服务器未返回 client_id，请手动填写 Client ID")

    apply_discovered_metadata(cred, discovered, client, redirect_uri)
    server.auth_type = AUTH_OAUTH
    verifier, challenge = generate_pkce()
    import secrets

    state = secrets.token_urlsafe(24)
    db.add(
        McpOAuthState(
            state=state,
            server_id=server_id,
            code_verifier=verifier,
            redirect_uri=redirect_uri,
            frontend_redirect=data.frontend_redirect or "",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        )
    )
    db.commit()
    auth_url = build_authorization_url(
        discovered.get("as_metadata") or {},
        client_id=client["client_id"],
        redirect_uri=redirect_uri,
        state=state,
        code_challenge=challenge,
        resource=discovered.get("resource") or "",
        scope=data.scope,
    )
    return {"authorization_url": auth_url, "state": state}


oauth_callback_router = APIRouter(tags=["mcp-oauth"])


@oauth_callback_router.get("/api/v1/mcp/oauth/callback")
async def oauth_callback(
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    if error:
        return RedirectResponse(url=f"/connectors?mcp_oauth=error&message={error}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="缺少 code 或 state")
    row = db.query(McpOAuthState).filter(McpOAuthState.state == state).first()
    if not row:
        raise HTTPException(status_code=400, detail="OAuth state 无效或已过期")
    expires = row.expires_at
    if expires and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires and expires < datetime.now(timezone.utc):
        db.delete(row)
        db.commit()
        raise HTTPException(status_code=400, detail="OAuth state 已过期")

    server = db.query(McpServer).filter(McpServer.server_id == row.server_id).first()
    cred = db.query(McpOAuthCredential).filter(McpOAuthCredential.server_id == row.server_id).first()
    if not server or not cred:
        raise HTTPException(status_code=404, detail="MCP Server 或凭证不存在")

    import json

    as_meta = {}
    if cred.as_metadata_json:
        try:
            as_meta = json.loads(cred.as_metadata_json)
        except Exception:
            as_meta = {"token_endpoint": cred.token_endpoint}
    try:
        payload = await exchange_code(
            as_meta,
            code=code,
            redirect_uri=row.redirect_uri or cred.redirect_uri,
            client_id=cred.client_id,
            client_secret=decrypt_secret(cred.client_secret_enc or ""),
            code_verifier=row.code_verifier,
            resource=cred.resource or "",
        )
        store_tokens(cred, payload)
        server.auth_type = AUTH_OAUTH
        server.last_error = ""
        server.status = "ACTIVE"
        frontend = row.frontend_redirect or f"/connectors?mcp_oauth=ok&server_id={server.server_id}"
        db.delete(row)
        db.commit()
        return RedirectResponse(url=frontend)
    except McpError as exc:
        server.last_error = str(exc)
        db.delete(row)
        db.commit()
        return RedirectResponse(url=f"/connectors?mcp_oauth=error&message={exc}")
