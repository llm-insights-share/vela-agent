from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database import get_db
from deps import CurrentUser
from models import McpOAuthCredential, McpOAuthState, McpServer, gen_uuid, now_utc
from schemas import (
    ConnectorCustomCreate,
    ConnectorFromCatalogCreate,
    ConnectorUpdate,
    McpOAuthStartRequest,
    McpToolLlmTestRequest,
    McpToolTestRequest,
    SessionConnectorsUpdate,
)
from services.connector_catalog import get_catalog_template, list_catalog_templates
from services.connector_service import (
    call_connector_tool,
    create_connector_from_catalog,
    create_custom_connector,
    delete_connector,
    disconnect_connector,
    discover_connector,
    get_user_connector,
    list_user_connectors,
    serialize_connector,
    sync_connector,
    test_connector,
    update_connector,
)
from services.mcp.config import AUTH_OAUTH, TRANSPORT_STDIO
from services.mcp.crypto import decrypt_secret
from services.mcp.jsonrpc import McpError
from services.mcp.oauth import (
    apply_discovered_metadata,
    build_authorization_url,
    discover_authorization_server,
    generate_pkce,
    load_oauth_settings,
    register_client,
)

router = APIRouter(prefix="/api/v1/connectors", tags=["connectors"])


def _get_owned(db: Session, user_id: str, connector_id: str):
    connector = get_user_connector(db, user_id, connector_id)
    if not connector:
        raise HTTPException(status_code=404, detail="连接器不存在")
    return connector


@router.get("/catalog")
def get_catalog(user: CurrentUser):
    return {"items": list_catalog_templates()}


@router.get("")
def list_connectors(user: CurrentUser, db: Session = Depends(get_db)):
    items = list_user_connectors(db, user.user_id)
    return {"items": items, "total": len(items)}


@router.post("/from-catalog", status_code=201)
def create_from_catalog(
    data: ConnectorFromCatalogCreate,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    if not get_catalog_template(data.catalog_key) or data.catalog_key == "custom":
        raise HTTPException(status_code=400, detail="无效的 catalog_key")
    try:
        connector = create_connector_from_catalog(
            db,
            user_id=user.user_id,
            catalog_key=data.catalog_key,
            credentials=data.credentials or {},
            name=data.name,
            display_name=data.display_name,
            description=data.description,
            connector_config=data.connector_config or {},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return serialize_connector(db, connector)


@router.post("", status_code=201)
def create_custom(
    data: ConnectorCustomCreate,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    try:
        connector = create_custom_connector(
            db,
            user_id=user.user_id,
            name=data.name,
            display_name=data.display_name,
            description=data.description,
            transport=data.transport,
            command=data.command,
            args=data.args,
            env=data.env,
            url=data.url,
            headers=data.headers,
            auth_type=data.auth_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return serialize_connector(db, connector)


@router.get("/{connector_id}")
def get_connector(connector_id: str, user: CurrentUser, db: Session = Depends(get_db)):
    connector = _get_owned(db, user.user_id, connector_id)
    return serialize_connector(db, connector)


@router.put("/{connector_id}")
def update_connector_route(
    connector_id: str,
    data: ConnectorUpdate,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    connector = _get_owned(db, user.user_id, connector_id)
    try:
        connector = update_connector(
            db,
            connector,
            display_name=data.display_name,
            description=data.description,
            connector_config=data.connector_config,
            credentials=data.credentials,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return serialize_connector(db, connector)


@router.delete("/{connector_id}")
def delete_connector_route(
    connector_id: str,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    connector = _get_owned(db, user.user_id, connector_id)
    delete_connector(db, connector)
    return {"message": "连接器已删除"}


@router.post("/{connector_id}/discover")
async def discover_connector_route(
    connector_id: str,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    connector = _get_owned(db, user.user_id, connector_id)
    try:
        return await discover_connector(db, connector)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{connector_id}/sync")
async def sync_connector_route(
    connector_id: str,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    connector = _get_owned(db, user.user_id, connector_id)
    result = await sync_connector(db, connector)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "同步失败")
    return result


@router.post("/{connector_id}/test")
async def test_connector_route(
    connector_id: str,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    connector = _get_owned(db, user.user_id, connector_id)
    result = await test_connector(db, connector)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "连接测试失败")
    return result


@router.post("/{connector_id}/test-tool")
async def test_connector_tool_route(
    connector_id: str,
    data: McpToolTestRequest,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    connector = _get_owned(db, user.user_id, connector_id)
    result = await call_connector_tool(
        db,
        connector,
        tool_name=data.tool_name,
        arguments=data.arguments or {},
    )
    if not result.get("success"):
        # Still return body so UI can show error in modal; use 200 with success=false
        # when callers expect soft failure. Keep 400 for hard auth/config errors only.
        status = result.get("status_code")
        if status in (401, 403):
            raise HTTPException(status_code=status, detail=result.get("error") or "调用失败")
    return result


@router.post("/{connector_id}/test-tool-llm")
async def test_connector_tool_llm_route(
    connector_id: str,
    data: McpToolLlmTestRequest,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    from services.mcp_tool_llm_test import run_mcp_tool_llm_test

    connector = _get_owned(db, user.user_id, connector_id)

    async def _exec(tool_name: str, arguments: dict):
        return await call_connector_tool(
            db,
            connector,
            tool_name=tool_name,
            arguments=arguments or {},
        )

    return await run_mcp_tool_llm_test(
        db,
        tool_name=data.tool_name,
        instruction=data.instruction,
        model_service_id=data.model_service_id,
        input_schema=data.input_schema or {},
        execute_tool=_exec,
    )


@router.post("/{connector_id}/disconnect")
def disconnect_connector_route(
    connector_id: str,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    connector = _get_owned(db, user.user_id, connector_id)
    connector = disconnect_connector(db, connector)
    return serialize_connector(db, connector)


@router.post("/{connector_id}/oauth/start")
async def start_connector_oauth(
    connector_id: str,
    data: McpOAuthStartRequest,
    request: Request,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    connector = _get_owned(db, user.user_id, connector_id)
    server = db.query(McpServer).filter(McpServer.server_id == connector.mcp_server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="MCP Server 不存在")
    if server.transport == TRANSPORT_STDIO:
        raise HTTPException(
            status_code=400,
            detail="stdio 连接器请在本地完成 OAuth（如 lark-mcp login），然后执行同步",
        )
    if not server.url:
        raise HTTPException(status_code=400, detail="请先配置 MCP URL")

    settings = load_oauth_settings()
    redirect_uri = settings.get("redirect_uri") or str(request.base_url).rstrip("/") + "/api/v1/mcp/oauth/callback"
    try:
        discovered = await discover_authorization_server(server.url)
    except McpError as exc:
        raise HTTPException(status_code=400, detail=f"发现 OAuth 元数据失败: {exc}") from exc

    cred = db.query(McpOAuthCredential).filter(McpOAuthCredential.server_id == server.server_id).first()
    if not cred:
        cred = McpOAuthCredential(credential_id=gen_uuid(), server_id=server.server_id)
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
    import secrets

    verifier, challenge = generate_pkce()
    state = secrets.token_urlsafe(24)
    frontend = data.frontend_redirect or f"/connectors?oauth=ok&connector_id={connector.connector_id}"
    db.add(
        McpOAuthState(
            state=state,
            server_id=server.server_id,
            code_verifier=verifier,
            redirect_uri=redirect_uri,
            frontend_redirect=frontend,
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
