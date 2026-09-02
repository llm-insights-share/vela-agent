from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from models import (
    AgentConnectorBinding,
    ConnectorStatus,
    McpOAuthCredential,
    McpOAuthState,
    McpServer,
    Tool,
    ToolStatus,
    UserConnector,
    gen_uuid,
    now_utc,
)
from services.connector_catalog import (
    ENC_PREFIX,
    build_mcp_server_payload,
    get_catalog_template,
    is_stored_secret,
    list_catalog_templates,
    store_secret,
)
from services.mcp.config import AUTH_BEARER, AUTH_NONE, AUTH_OAUTH, TRANSPORT_STDIO
from services.mcp.crypto import decrypt_secret
from services.mcp.jsonrpc import McpAuthError, McpError
from services.mcp.server_service import (
    connection_config_for_server,
    server_status_payload,
    server_to_config,
    sync_server_tools,
)
from services.mcp.oauth import ensure_access_token

_IMAP_ID_PATCH = Path(__file__).resolve().parent.parent / "mcp_wrappers" / "patch_imap_id.cjs"
PLATFORM_MCP_PREFIX = "mcp:"


def is_platform_mcp_binding(catalog_key: str) -> bool:
    return str(catalog_key or "").startswith(PLATFORM_MCP_PREFIX)


def platform_mcp_server_id(catalog_key: str) -> str:
    return str(catalog_key or "")[len(PLATFORM_MCP_PREFIX) :]


def make_platform_mcp_binding_key(server_id: str) -> str:
    return f"{PLATFORM_MCP_PREFIX}{server_id}"
_MCP_MAIL_RUNNER = Path(__file__).resolve().parent.parent / "mcp_wrappers" / "run_mcp_mail.mjs"
_MCP_LARK_RUNNER = Path(__file__).resolve().parent.parent / "mcp_wrappers" / "run_lark_mcp.mjs"


def rewrite_mcp_mail_launch(
    command: str = "",
    args: Optional[List[Any]] = None,
    env: Optional[Dict[str, Any]] = None,
) -> tuple[str, List[Any], Dict[str, Any]]:
    """Route mcp-mail-server through local runner that sends IMAP ID (163 Unsafe Login)."""
    args_list = [str(a) for a in (args or [])]
    joined = " ".join(args_list)
    uses_mail_mcp = "mcp-mail-server" in joined or (command or "").endswith("mcp-mail-server")
    uses_runner = "run_mcp_mail.mjs" in joined or (command == "node" and any("run_mcp_mail.mjs" in a for a in args_list))
    out_env = dict(env or {})
    if uses_runner and _MCP_MAIL_RUNNER.is_file():
        return command or "node", args_list, out_env
    if uses_mail_mcp and _MCP_MAIL_RUNNER.is_file():
        return "node", [str(_MCP_MAIL_RUNNER)], out_env
    # Fallback: NODE_OPTIONS require-hook for older installs
    if uses_mail_mcp and _IMAP_ID_PATCH.is_file():
        flag = f"--require {_IMAP_ID_PATCH}"
        existing = str(out_env.get("NODE_OPTIONS") or "")
        if str(_IMAP_ID_PATCH) not in existing:
            out_env["NODE_OPTIONS"] = f"{existing} {flag}".strip()
    return command or "", args_list, out_env


def rewrite_lark_mcp_launch(
    command: str = "",
    args: Optional[List[Any]] = None,
    env: Optional[Dict[str, Any]] = None,
) -> tuple[str, List[Any], Dict[str, Any]]:
    """Route @larksuiteoapi/lark-mcp through local runner (npx/keytar native build often fails)."""
    args_list = [str(a) for a in (args or [])]
    joined = " ".join(args_list)
    out_env = dict(env or {})
    uses_runner = "run_lark_mcp.mjs" in joined or (
        command == "node" and any("run_lark_mcp.mjs" in a for a in args_list)
    )
    uses_lark = "@larksuiteoapi/lark-mcp" in joined or "lark-mcp" in joined
    if uses_runner and _MCP_LARK_RUNNER.is_file():
        return command or "node", args_list, out_env
    if uses_lark and _MCP_LARK_RUNNER.is_file():
        # Drop npx/-y/package name; keep "mcp" and subsequent CLI flags
        rest: List[str] = []
        i = 0
        while i < len(args_list):
            a = args_list[i]
            if a in ("-y", "--yes", "@larksuiteoapi/lark-mcp", "lark-mcp"):
                i += 1
                continue
            if a.endswith("run_lark_mcp.mjs"):
                i += 1
                continue
            rest.append(a)
            i += 1
        if not rest or rest[0] != "mcp":
            rest = ["mcp", *rest]
        return "node", [str(_MCP_LARK_RUNNER), *rest], out_env
    return command or "", args_list, out_env


def rewrite_connector_mcp_launch(
    command: str = "",
    args: Optional[List[Any]] = None,
    env: Optional[Dict[str, Any]] = None,
) -> tuple[str, List[Any], Dict[str, Any]]:
    cmd, argv, out_env = rewrite_mcp_mail_launch(command, args, env)
    return rewrite_lark_mcp_launch(cmd, argv, out_env)

def decrypt_stored_value(value: Any) -> str:
    if not isinstance(value, str):
        return "" if value is None else str(value)
    if is_stored_secret(value):
        return decrypt_secret(value[len(ENC_PREFIX):])
    return value


def prepare_server_secrets(server: McpServer) -> McpServer:
    """Return a shallow copy of server fields with decrypted env/headers for MCP runtime."""
    env = {}
    for key, val in (server.env or {}).items():
        env[key] = decrypt_stored_value(val)
    headers = {}
    for key, val in (server.headers or {}).items():
        if key.lower() == "authorization" and isinstance(val, str):
            if val.startswith("Bearer "):
                token_part = val[7:]
                if is_stored_secret(token_part):
                    headers[key] = f"Bearer {decrypt_stored_value(token_part)}"
                else:
                    headers[key] = val
            elif is_stored_secret(val):
                headers[key] = decrypt_stored_value(val)
            else:
                headers[key] = val
        elif is_stored_secret(val):
            headers[key] = decrypt_stored_value(val)
        else:
            headers[key] = val
    server_copy = McpServer(
        server_id=server.server_id,
        owner_user_id=server.owner_user_id,
        name=server.name,
        display_name=server.display_name,
        description=server.description,
        transport=server.transport,
        command=server.command,
        args=server.args or [],
        env=env,
        url=server.url,
        headers=headers,
        auth_type=server.auth_type,
        status=server.status,
        last_synced_at=server.last_synced_at,
        last_error=server.last_error,
    )
    return server_copy


async def connection_config_for_user_server(db: Session, server: McpServer) -> Dict[str, Any]:
    server = _normalize_feishu_stdio_auth(db, server)
    prepared = prepare_server_secrets(server)
    patched_cmd, patched_args, patched_env = rewrite_connector_mcp_launch(
        command=prepared.command or "",
        args=prepared.args or [],
        env=prepared.env or {},
    )
    if prepared.auth_type == AUTH_BEARER:
        auth_header = (prepared.headers or {}).get("Authorization") or ""
        token = auth_header[7:] if auth_header.startswith("Bearer ") else ""
        return {
            "transport": prepared.transport,
            "mcp_command": patched_cmd,
            "mcp_args": patched_args,
            "mcp_env": patched_env,
            "mcp_url": prepared.url or "",
            "mcp_headers": prepared.headers or {},
            "auth_type": AUTH_BEARER,
            "auth_token": token,
            "mcp_server_id": prepared.server_id,
        }

    cfg = server_to_config(prepared)
    cfg["mcp_command"] = patched_cmd
    cfg["mcp_args"] = patched_args
    cfg["mcp_env"] = patched_env
    # stdio app-credential MCPs (e.g. Feishu) must not use platform MCP OAuth tokens
    if server.auth_type == AUTH_OAUTH and server.transport != TRANSPORT_STDIO:
        token = await ensure_access_token(db, server)
        cfg["auth_type"] = "bearer"
        cfg["auth_token"] = token
    return cfg


def _is_lark_mcp_args(args: List[Any]) -> bool:
    joined = " ".join(str(a) for a in (args or []))
    return "@larksuiteoapi/lark-mcp" in joined or "lark-mcp" in joined


def _normalize_feishu_stdio_auth(db: Session, server: McpServer) -> McpServer:
    """Feishu catalog uses App ID/Secret; strip mistaken platform OAuth on stdio lark-mcp."""
    if (server.transport or "") != TRANSPORT_STDIO:
        return server
    args = list(server.args or [])
    if not _is_lark_mcp_args(args):
        return server

    changed = False
    if "--oauth" in args:
        args = [a for a in args if a != "--oauth"]
        changed = True

    if "--token-mode" in args:
        i = args.index("--token-mode")
        if i + 1 < len(args) and args[i + 1] != "tenant_access_token":
            args[i + 1] = "tenant_access_token"
            changed = True
    else:
        args.extend(["--token-mode", "tenant_access_token"])
        changed = True

    if "-d" not in args and "--domain" not in args:
        args.extend(["-d", "https://open.feishu.cn"])
        changed = True

    if server.auth_type == AUTH_OAUTH:
        server.auth_type = AUTH_NONE
        changed = True

    if not changed:
        return server

    server.args = args
    server.updated_at = now_utc()
    db.add(server)
    db.commit()
    db.refresh(server)
    return server


def _slug_name(raw: str, fallback: str = "connector") -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", (raw or "").strip()).strip("_").lower()
    return (s[:64] or fallback)


def _redact_env(env: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    out = {}
    for key, val in (env or {}).items():
        if is_stored_secret(val) or key in {"EMAIL_PASS", "DINGTALK_Client_Secret"}:
            out[key] = "***"
        else:
            out[key] = val
    return out


def _redact_headers(headers: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    out = {}
    for key, val in (headers or {}).items():
        if key.lower() == "authorization":
            out[key] = "Bearer ***"
        else:
            out[key] = val
    return out


def _oauth_status(db: Session, server: McpServer) -> str:
    cred = db.query(McpOAuthCredential).filter(McpOAuthCredential.server_id == server.server_id).first()
    payload = server_status_payload(server, cred)
    return payload.get("oauth_status") or "not_required"


def serialize_connector(db: Session, connector: UserConnector) -> Dict[str, Any]:
    server = connector.mcp_server or db.query(McpServer).filter(
        McpServer.server_id == connector.mcp_server_id
    ).first()
    return {
        "connector_id": connector.connector_id,
        "user_id": connector.user_id,
        "catalog_key": connector.catalog_key,
        "name": connector.name,
        "display_name": connector.display_name or connector.name,
        "description": connector.description or "",
        "mcp_server_id": connector.mcp_server_id,
        "connector_config": connector.connector_config or {},
        "editable_credentials": _editable_credentials_from_server(connector.catalog_key, server),
        "status": connector.status.value if hasattr(connector.status, "value") else connector.status,
        "last_error": connector.last_error or "",
        "tool_count": connector.tool_count or 0,
        "oauth_status": _oauth_status(db, server) if server else "not_required",
        "source": server_status_payload(server).get("source", "") if server else "",
        "transport": server.transport if server else "",
        "created_at": connector.created_at,
        "updated_at": connector.updated_at,
    }


def _secret_credential_keys(catalog_key: Optional[str]) -> set:
    tmpl = get_catalog_template(catalog_key or "") or {}
    keys = set()
    for field in tmpl.get("required_fields") or []:
        if field.get("type") == "password":
            keys.add(field.get("key"))
    return {k for k in keys if k}


def _editable_credentials_from_server(catalog_key: Optional[str], server: Optional[McpServer]) -> Dict[str, Any]:
    """Public credential fields for edit form; password-type values always empty."""
    if not catalog_key or not server:
        return {}
    env = server.env or {}
    secret_keys = _secret_credential_keys(catalog_key)

    if catalog_key == "email":
        out = {
            "email_address": env.get("EMAIL_ADDRESS") or env.get("EMAIL_USER") or "",
            "password": "",
            "imap_host": env.get("IMAP_HOST") or "",
            "imap_port": int(env["IMAP_PORT"]) if str(env.get("IMAP_PORT") or "").isdigit() else 993,
            "imap_secure": str(env.get("IMAP_SECURE") or "true").lower() in ("1", "true", "yes", "on"),
            "smtp_host": env.get("SMTP_HOST") or "",
            "smtp_port": int(env["SMTP_PORT"]) if str(env.get("SMTP_PORT") or "").isdigit() else 465,
            "smtp_secure": str(env.get("SMTP_SECURE") or "true").lower() in ("1", "true", "yes", "on"),
        }
        return out

    if catalog_key == "github":
        return {"access_token": ""}

    if catalog_key == "feishu_group":
        args = list(server.args or [])
        app_id = ""
        # args: -y @larksuiteoapi/lark-mcp mcp -a APP_ID -s APP_SECRET
        if "-a" in args:
            i = args.index("-a")
            if i + 1 < len(args):
                app_id = args[i + 1]
        return {"app_id": app_id, "app_secret": ""}

    if catalog_key == "dingtalk_group":
        return {
            "app_key": env.get("DINGTALK_Client_ID") or env.get("DINGTALK_APP_KEY") or "",
            "app_secret": "",
        }

    # Generic: expose non-secret required fields as empty/prefilled when possible
    tmpl = get_catalog_template(catalog_key) or {}
    out = {}
    for field in tmpl.get("required_fields") or []:
        key = field.get("key")
        if not key:
            continue
        out[key] = "" if key in secret_keys else ""
    return out


def _merge_credentials_preserving_secrets(
    catalog_key: Optional[str],
    incoming: Dict[str, Any],
    server: McpServer,
) -> Dict[str, Any]:
    """Fill blank password-type fields from currently stored secrets."""
    secret_keys = _secret_credential_keys(catalog_key)
    current = _current_secret_credentials(catalog_key, server)
    merged = dict(incoming or {})
    for key in secret_keys:
        val = merged.get(key)
        if val is None or str(val).strip() == "":
            if current.get(key):
                merged[key] = current[key]
    return merged


def _current_secret_credentials(catalog_key: Optional[str], server: McpServer) -> Dict[str, str]:
    env = server.env or {}
    headers = server.headers or {}
    if catalog_key == "email":
        return {"password": decrypt_stored_value(env.get("EMAIL_PASS") or "")}
    if catalog_key == "github":
        auth = headers.get("Authorization") or ""
        token = auth[7:] if auth.startswith("Bearer ") else auth
        return {"access_token": decrypt_stored_value(token)}
    if catalog_key == "feishu_group":
        args = list(server.args or [])
        secret = ""
        if "-s" in args:
            i = args.index("-s")
            if i + 1 < len(args):
                secret = args[i + 1]
        return {"app_secret": secret}
    if catalog_key == "dingtalk_group":
        return {
            "app_secret": decrypt_stored_value(
                env.get("DINGTALK_Client_Secret") or env.get("DINGTALK_APP_SECRET") or ""
            )
        }
    return {}


def get_user_connector(db: Session, user_id: str, connector_id: str) -> Optional[UserConnector]:
    return (
        db.query(UserConnector)
        .filter(UserConnector.connector_id == connector_id, UserConnector.user_id == user_id)
        .first()
    )


def list_user_connectors(db: Session, user_id: str) -> List[Dict[str, Any]]:
    rows = (
        db.query(UserConnector)
        .filter(UserConnector.user_id == user_id)
        .order_by(UserConnector.created_at.desc())
        .all()
    )
    return [serialize_connector(db, row) for row in rows]


def _ensure_unique_name(db: Session, user_id: str, name: str, exclude_id: Optional[str] = None) -> str:
    base = _slug_name(name)
    candidate = base
    n = 2
    while True:
        q = db.query(UserConnector).filter(UserConnector.user_id == user_id, UserConnector.name == candidate)
        if exclude_id:
            q = q.filter(UserConnector.connector_id != exclude_id)
        if not q.first():
            return candidate
        candidate = f"{base}_{n}"
        n += 1


def create_connector_from_catalog(
    db: Session,
    *,
    user_id: str,
    catalog_key: str,
    credentials: Dict[str, Any],
    name: str,
    display_name: str = "",
    description: str = "",
    connector_config: Optional[Dict[str, Any]] = None,
) -> UserConnector:
    if not get_catalog_template(catalog_key) or catalog_key == "custom":
        raise ValueError("无效的 catalog_key")

    slug = _ensure_unique_name(db, user_id, name or catalog_key)
    payload = build_mcp_server_payload(
        catalog_key=catalog_key,
        credentials=credentials,
        connector_config=connector_config,
        user_id=user_id,
        name=slug,
        display_name=display_name,
        description=description,
    )

    existing_server = db.query(McpServer).filter(McpServer.name == payload["name"]).first()
    if existing_server:
        raise ValueError("连接器名称冲突，请更换名称")

    server = McpServer(
        server_id=gen_uuid(),
        owner_user_id=user_id,
        name=payload["name"],
        display_name=payload.get("display_name") or slug,
        description=payload.get("description") or "",
        transport=payload["transport"],
        command=payload.get("command") or "",
        args=payload.get("args") or [],
        env=payload.get("env") or {},
        url=payload.get("url") or "",
        headers=payload.get("headers") or {},
        auth_type=payload.get("auth_type") or "none",
    )
    db.add(server)
    db.flush()

    connector = UserConnector(
        connector_id=gen_uuid(),
        user_id=user_id,
        catalog_key=catalog_key,
        name=slug,
        display_name=display_name or server.display_name,
        description=description,
        mcp_server_id=server.server_id,
        connector_config=connector_config or {},
        status=ConnectorStatus.DISCONNECTED,
    )
    db.add(connector)
    db.commit()
    db.refresh(connector)
    return connector


def create_custom_connector(
    db: Session,
    *,
    user_id: str,
    name: str,
    display_name: str = "",
    description: str = "",
    transport: str = TRANSPORT_STDIO,
    command: str = "",
    args: Optional[List[str]] = None,
    env: Optional[Dict[str, str]] = None,
    url: str = "",
    headers: Optional[Dict[str, str]] = None,
    auth_type: str = "none",
) -> UserConnector:
    slug = _ensure_unique_name(db, user_id, name)
    server_name = f"uc_{user_id[:8]}_custom_{slug}"
    if db.query(McpServer).filter(McpServer.name == server_name).first():
        raise ValueError("连接器名称冲突")

    safe_env = {}
    for key, val in (env or {}).items():
        if key.upper().endswith(("SECRET", "PASS", "PASSWORD", "TOKEN")) or "SECRET" in key.upper():
            safe_env[key] = store_secret(str(val))
        else:
            safe_env[key] = str(val)

    server = McpServer(
        server_id=gen_uuid(),
        owner_user_id=user_id,
        name=server_name,
        display_name=display_name or slug,
        description=description,
        transport=transport,
        command=command,
        args=args or [],
        env=safe_env,
        url=url,
        headers=headers or {},
        auth_type=auth_type,
    )
    db.add(server)
    db.flush()

    connector = UserConnector(
        connector_id=gen_uuid(),
        user_id=user_id,
        catalog_key=None,
        name=slug,
        display_name=display_name or slug,
        description=description,
        mcp_server_id=server.server_id,
        connector_config={},
        status=ConnectorStatus.DISCONNECTED,
    )
    db.add(connector)
    db.commit()
    db.refresh(connector)
    return connector


def update_connector(
    db: Session,
    connector: UserConnector,
    *,
    display_name: Optional[str] = None,
    description: Optional[str] = None,
    connector_config: Optional[Dict[str, Any]] = None,
    credentials: Optional[Dict[str, Any]] = None,
) -> UserConnector:
    server = db.query(McpServer).filter(McpServer.server_id == connector.mcp_server_id).first()
    if not server:
        raise ValueError("MCP Server 不存在")

    if display_name is not None:
        connector.display_name = display_name
        server.display_name = display_name
    if description is not None:
        connector.description = description
        server.description = description
    if connector_config is not None:
        connector.connector_config = connector_config

    if credentials and connector.catalog_key:
        merged = _merge_credentials_preserving_secrets(
            connector.catalog_key, credentials, server
        )
        payload = build_mcp_server_payload(
            catalog_key=connector.catalog_key,
            credentials=merged,
            connector_config=connector.connector_config or {},
            user_id=connector.user_id,
            name=connector.name,
            display_name=connector.display_name,
            description=connector.description,
        )
        server.transport = payload["transport"]
        server.command = payload.get("command") or ""
        server.args = payload.get("args") or []
        server.env = payload.get("env") or {}
        server.url = payload.get("url") or ""
        server.headers = payload.get("headers") or {}
        server.auth_type = payload.get("auth_type") or "none"
        connector.status = ConnectorStatus.DISCONNECTED

    connector.updated_at = now_utc()
    server.updated_at = now_utc()
    db.commit()
    db.refresh(connector)
    return connector


def delete_connector(db: Session, connector: UserConnector) -> None:
    delete_mcp_server_cascade(db, connector.mcp_server_id)
    db.delete(connector)
    db.commit()


def delete_mcp_server_cascade(db: Session, server_id: str) -> None:
    """Remove tools, OAuth state, and MCP server row."""
    if not server_id:
        return
    tools = db.query(Tool).filter(Tool.mcp_server_id == server_id).all()
    for tool in tools:
        db.delete(tool)
    db.query(McpOAuthState).filter(McpOAuthState.server_id == server_id).delete()
    db.query(McpOAuthCredential).filter(McpOAuthCredential.server_id == server_id).delete()
    server = db.query(McpServer).filter(McpServer.server_id == server_id).first()
    if server:
        db.delete(server)


def purge_user_owned_resources(db: Session, user_id: str) -> dict:
    """Delete connectors and user-owned MCP servers before removing the user account."""
    stats = {"connectors": 0, "mcp_servers": 0}
    connectors = db.query(UserConnector).filter(UserConnector.user_id == user_id).all()
    for connector in list(connectors):
        delete_mcp_server_cascade(db, connector.mcp_server_id)
        db.delete(connector)
        stats["connectors"] += 1
    db.flush()
    orphan_servers = db.query(McpServer).filter(McpServer.owner_user_id == user_id).all()
    for server in list(orphan_servers):
        delete_mcp_server_cascade(db, server.server_id)
        stats["mcp_servers"] += 1
    db.commit()
    return stats


def verify_email_imap_credentials(env: Dict[str, Any]) -> Optional[str]:
    """Return error message if IMAP login fails; None if OK or not an email env."""
    import imaplib
    import ssl

    host = str(env.get("IMAP_HOST") or "").strip()
    password = str(env.get("EMAIL_PASS") or "")
    user = str(env.get("EMAIL_USER") or env.get("EMAIL_ADDRESS") or "").strip()
    if not host or not password or not user:
        return None
    port = int(env.get("IMAP_PORT") or 993)
    secure = str(env.get("IMAP_SECURE") or "true").lower() not in ("0", "false", "no")
    try:
        if secure:
            ctx = ssl.create_default_context()
            client = imaplib.IMAP4_SSL(host, port, ssl_context=ctx)
        else:
            client = imaplib.IMAP4(host, port)
        typ, _ = client.login(user, password)
        if typ != "OK":
            err = f"IMAP 登录失败（{typ}）"
        else:
            err = None
            # NetEase and similar providers may require IMAP ID after LOGIN.
            if "163.com" in host or "126.com" in host or "yeah.net" in host:
                try:
                    imaplib.Commands["ID"] = ("AUTH",)
                    id_args = '("name" "vela-agent" "version" "1.0" "vendor" "vela")'
                    client._simple_command("ID", id_args)
                except Exception:
                    pass
            styp, sdat = client.select("INBOX")
            if styp != "OK":
                detail = sdat[0].decode("utf-8", errors="replace") if sdat and sdat[0] else styp
                err = f"IMAP 登录成功但无法打开收件箱: {detail}"
        try:
            client.logout()
        except Exception:
            pass
    except Exception as exc:
        msg = str(exc)
        if "Login error" in msg or "password error" in msg.lower() or "AUTHENTICATIONFAILED" in msg.upper():
            hint = ""
            if "163.com" in host or "126.com" in host:
                hint = "（163/126 请使用「客户端授权码」，不是网页登录密码）"
            err = f"IMAP 账号或授权码错误{hint}"
        elif "Unsafe Login" in msg or "ID required" in msg:
            err = f"IMAP 需要客户端标识（ID）: {msg[:200]}"
        else:
            err = f"IMAP 校验失败: {msg[:240]}"
    return err


async def discover_connector(db: Session, connector: UserConnector) -> Dict[str, Any]:
    from services.mcp.client import discover_mcp_tools

    server = db.query(McpServer).filter(McpServer.server_id == connector.mcp_server_id).first()
    if not server:
        raise ValueError("MCP Server 不存在")
    cfg = await connection_config_for_user_server(db, server)
    return await discover_mcp_tools(cfg, timeout_seconds=45)


async def sync_connector(db: Session, connector: UserConnector) -> Dict[str, Any]:
    server = db.query(McpServer).filter(McpServer.server_id == connector.mcp_server_id).first()
    if not server:
        raise ValueError("MCP Server 不存在")
    try:
        cfg = await connection_config_for_user_server(db, server)
        imap_err = verify_email_imap_credentials(cfg.get("mcp_env") or cfg.get("env") or {})
        if imap_err:
            connector.status = ConnectorStatus.ERROR
            connector.last_error = imap_err
            connector.updated_at = now_utc()
            db.commit()
            return {"success": False, "error": imap_err}

        from services.mcp.client import discover_mcp_tools

        discovered = await discover_mcp_tools(cfg, timeout_seconds=45)
        if not discovered.get("success"):
            connector.status = ConnectorStatus.ERROR
            connector.last_error = discovered.get("error") or "同步失败"
            connector.updated_at = now_utc()
            db.commit()
            return {"success": False, "error": connector.last_error}

        result = await sync_server_tools(db, server)
    except (McpAuthError, McpError) as exc:
        connector.status = ConnectorStatus.ERROR
        connector.last_error = str(exc)
        connector.updated_at = now_utc()
        db.commit()
        return {"success": False, "error": str(exc)}

    if result.get("success"):
        connector.status = ConnectorStatus.CONNECTED
        connector.tool_count = int(result.get("total") or 0)
        connector.last_error = ""
    else:
        connector.status = ConnectorStatus.ERROR
        connector.last_error = result.get("error") or "同步失败"
    connector.updated_at = now_utc()
    db.commit()
    db.refresh(connector)
    result["connector"] = serialize_connector(db, connector)
    return result


async def test_connector(db: Session, connector: UserConnector) -> Dict[str, Any]:
    server = db.query(McpServer).filter(McpServer.server_id == connector.mcp_server_id).first()
    if not server:
        return {"success": False, "error": "MCP Server 不存在"}
    cfg = await connection_config_for_user_server(db, server)
    imap_err = verify_email_imap_credentials(cfg.get("mcp_env") or cfg.get("env") or {})
    if imap_err:
        return {"success": False, "error": imap_err}
    result = await discover_connector(db, connector)
    if result.get("success"):
        tools = result.get("tools") or []
        return {
            "success": True,
            "tool_count": len(tools),
            "tools": tools,
            "message": "连接成功",
        }
    return {"success": False, "error": result.get("error") or "连接失败"}


async def call_connector_tool(
    db: Session,
    connector: UserConnector,
    *,
    tool_name: str,
    arguments: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    from services.mcp.client import call_mcp_tool

    server = db.query(McpServer).filter(McpServer.server_id == connector.mcp_server_id).first()
    if not server:
        return {"success": False, "error": "MCP Server 不存在"}
    if not (tool_name or "").strip():
        return {"success": False, "error": "tool_name 必填"}
    cfg = await connection_config_for_user_server(db, server)
    imap_err = verify_email_imap_credentials(cfg.get("mcp_env") or cfg.get("env") or {})
    if imap_err:
        return {"success": False, "error": imap_err}
    return await call_mcp_tool(cfg, tool_name.strip(), arguments or {}, timeout_seconds=60)


def disconnect_connector(db: Session, connector: UserConnector) -> UserConnector:
    server_id = connector.mcp_server_id
    db.query(McpOAuthCredential).filter(McpOAuthCredential.server_id == server_id).delete()
    db.query(McpOAuthState).filter(McpOAuthState.server_id == server_id).delete()
    connector.status = ConnectorStatus.DISCONNECTED
    connector.tool_count = 0
    connector.last_error = ""
    connector.updated_at = now_utc()
    tools = db.query(Tool).filter(Tool.mcp_server_id == server_id).all()
    for tool in tools:
        tool.status = ToolStatus.INACTIVE
        tool.updated_at = now_utc()
    db.commit()
    db.refresh(connector)
    return connector


def get_active_connector_ids(session) -> List[str]:
    pending = dict(getattr(session, "pending_context", None) or {})
    ids = pending.get("active_connector_ids") or []
    return [str(x) for x in ids if x]


def set_active_connector_ids(db: Session, session, connector_ids: List[str], user_id: str) -> List[str]:
    owned = {
        c.connector_id
        for c in db.query(UserConnector)
        .filter(UserConnector.user_id == user_id, UserConnector.status == ConnectorStatus.CONNECTED)
        .all()
    }
    cleaned = []
    for cid in connector_ids or []:
        cid = str(cid).strip()
        if cid and cid in owned:
            cleaned.append(cid)
    pending = dict(session.pending_context or {})
    pending["active_connector_ids"] = cleaned
    session.pending_context = pending
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(session, "pending_context")
    db.commit()
    return cleaned


def load_session_connector_tools(
    db: Session,
    *,
    user_id: str,
    connector_ids: Optional[List[str]] = None,
) -> List[Tool]:
    if not user_id:
        return []
    q = db.query(UserConnector).filter(
        UserConnector.user_id == user_id,
        UserConnector.status == ConnectorStatus.CONNECTED,
    )
    if connector_ids is not None:
        if not connector_ids:
            return []
        q = q.filter(UserConnector.connector_id.in_(connector_ids))
    connectors = q.all()
    if not connectors:
        return []
    server_ids = [c.mcp_server_id for c in connectors]
    tools = (
        db.query(Tool)
        .filter(Tool.mcp_server_id.in_(server_ids), Tool.status == ToolStatus.ACTIVE)
        .all()
    )
    return tools


def list_session_connectors(db: Session, session, user_id: str) -> Dict[str, Any]:
    active_ids = set(get_active_connector_ids(session))
    items = list_user_connectors(db, user_id)
    for item in items:
        item["active_in_session"] = item["connector_id"] in active_ids
    return {"items": items, "active_connector_ids": list(active_ids)}


def _policies_from_binding_item(item: Any) -> Dict[str, Any]:
    policies: Dict[str, Any] = {}
    tools = getattr(item, "tools", None)
    if tools is None and isinstance(item, dict):
        tools = item.get("tools") or []
    for t in tools or []:
        if hasattr(t, "mcp_tool_name"):
            name = (t.mcp_tool_name or "").strip()
            enabled = bool(getattr(t, "enabled", True))
            require_approval = bool(getattr(t, "require_approval", False))
        else:
            name = str((t or {}).get("mcp_tool_name") or "").strip()
            enabled = bool((t or {}).get("enabled", True))
            require_approval = bool((t or {}).get("require_approval", False))
        if not name:
            continue
        policies[name] = {"enabled": enabled, "require_approval": require_approval}
    return policies


def serialize_agent_connector_bindings(db: Session, agent_id: str) -> List[Dict[str, Any]]:
    rows = (
        db.query(AgentConnectorBinding)
        .filter(AgentConnectorBinding.agent_id == agent_id)
        .order_by(AgentConnectorBinding.catalog_key.asc())
        .all()
    )
    out: List[Dict[str, Any]] = []
    for row in rows:
        policies = row.tool_policies or {}
        tools = []
        for name, pol in policies.items():
            if not isinstance(pol, dict):
                pol = {}
            tools.append(
                {
                    "mcp_tool_name": name,
                    "enabled": bool(pol.get("enabled", True)),
                    "require_approval": bool(pol.get("require_approval", False)),
                }
            )
        tools.sort(key=lambda x: x["mcp_tool_name"])
        display_name = row.catalog_key
        kind = "connector"
        mcp_server_id = None
        if is_platform_mcp_binding(row.catalog_key):
            kind = "platform_mcp"
            mcp_server_id = platform_mcp_server_id(row.catalog_key)
            server = db.query(McpServer).filter(McpServer.server_id == mcp_server_id).first()
            display_name = (server.display_name or server.name) if server else mcp_server_id
        else:
            tmpl = get_catalog_template(row.catalog_key) or {}
            display_name = tmpl.get("display_name") or row.catalog_key
        out.append(
            {
                "catalog_key": row.catalog_key,
                "display_name": display_name,
                "kind": kind,
                "mcp_server_id": mcp_server_id,
                "tools": tools,
            }
        )
    return out


def set_agent_connector_bindings(db: Session, agent_id: str, bindings: Optional[List[Any]]) -> None:
    db.query(AgentConnectorBinding).filter(AgentConnectorBinding.agent_id == agent_id).delete()
    if not bindings:
        return
    seen = set()
    for item in bindings:
        catalog_key = (
            getattr(item, "catalog_key", None)
            if not isinstance(item, dict)
            else item.get("catalog_key")
        )
        catalog_key = str(catalog_key or "").strip()
        if not catalog_key or catalog_key == "custom" or catalog_key in seen:
            continue
        if is_platform_mcp_binding(catalog_key):
            server_id = platform_mcp_server_id(catalog_key)
            server = (
                db.query(McpServer)
                .filter(McpServer.server_id == server_id, McpServer.owner_user_id.is_(None))
                .first()
            )
            if not server:
                continue
        elif not get_catalog_template(catalog_key):
            continue
        seen.add(catalog_key)
        db.add(
            AgentConnectorBinding(
                agent_id=agent_id,
                catalog_key=catalog_key,
                tool_policies=_policies_from_binding_item(item),
            )
        )
    db.flush()


def _mcp_remote_name(tool: Tool) -> str:
    cfg = tool.config or {}
    remote = cfg.get("mcp_tool_name") if isinstance(cfg, dict) else None
    if remote:
        return str(remote)
    # Fallback: strip server name prefix "uc_..._catalog_tool"
    name = tool.name or ""
    if "_" in name:
        # Prefer last segment after common prefixes when remote name stored in display_name
        if tool.display_name and tool.display_name != name:
            return tool.display_name
    return name


def _tool_enabled_by_policy(policies: Dict[str, Any], remote_name: str) -> bool:
    if not policies:
        return True
    pol = policies.get(remote_name)
    if pol is None:
        return True
    if not isinstance(pol, dict):
        return True
    return bool(pol.get("enabled", True))


def _tool_requires_approval(policies: Dict[str, Any], remote_name: str) -> bool:
    if not policies:
        return False
    pol = policies.get(remote_name)
    if not isinstance(pol, dict):
        return False
    return bool(pol.get("require_approval", False))


def resolve_runtime_connectors(
    db: Session,
    *,
    agent_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """Resolve agent bindings: catalog types ∩ user connectors, plus platform MCP servers."""
    bindings = (
        db.query(AgentConnectorBinding)
        .filter(AgentConnectorBinding.agent_id == agent_id)
        .all()
    )
    allowed_keys = {b.catalog_key for b in bindings}
    policies_by_key = {b.catalog_key: (b.tool_policies or {}) for b in bindings}

    catalog_keys = {k for k in allowed_keys if not is_platform_mcp_binding(k)}
    platform_keys = {k for k in allowed_keys if is_platform_mcp_binding(k)}
    configured_keys = sorted(allowed_keys)

    tools: List[Tool] = []
    approval_by_tool_id: Dict[str, bool] = {}
    connectors: List[UserConnector] = []
    platform_servers: List[McpServer] = []
    missing: List[str] = []

    if catalog_keys and user_id:
        connectors = (
            db.query(UserConnector)
            .filter(
                UserConnector.user_id == user_id,
                UserConnector.status == ConnectorStatus.CONNECTED,
                UserConnector.catalog_key.in_(list(catalog_keys)),
            )
            .all()
        )
        connected_keys = {c.catalog_key for c in connectors}
        missing.extend(sorted(catalog_keys - connected_keys))

        if connectors:
            server_ids = [c.mcp_server_id for c in connectors]
            catalog_by_server = {c.mcp_server_id: c.catalog_key for c in connectors}
            raw_tools = (
                db.query(Tool)
                .filter(Tool.mcp_server_id.in_(server_ids), Tool.status == ToolStatus.ACTIVE)
                .all()
            )
            for tool in raw_tools:
                catalog_key = catalog_by_server.get(tool.mcp_server_id) or ""
                policies = policies_by_key.get(catalog_key) or {}
                remote = _mcp_remote_name(tool)
                if not _tool_enabled_by_policy(policies, remote):
                    continue
                tools.append(tool)
                if _tool_requires_approval(policies, remote):
                    approval_by_tool_id[tool.tool_id] = True
    elif catalog_keys:
        missing.extend(sorted(catalog_keys))

    for key in sorted(platform_keys):
        server_id = platform_mcp_server_id(key)
        server = (
            db.query(McpServer)
            .filter(McpServer.server_id == server_id, McpServer.owner_user_id.is_(None))
            .first()
        )
        if not server:
            missing.append(key)
            continue
        platform_servers.append(server)
        policies = policies_by_key.get(key) or {}
        raw_tools = (
            db.query(Tool)
            .filter(Tool.mcp_server_id == server_id, Tool.status == ToolStatus.ACTIVE)
            .all()
        )
        for tool in raw_tools:
            remote = _mcp_remote_name(tool)
            if not _tool_enabled_by_policy(policies, remote):
                continue
            tools.append(tool)
            if _tool_requires_approval(policies, remote):
                approval_by_tool_id[tool.tool_id] = True

    if not allowed_keys:
        return {
            "configured_catalog_keys": [],
            "connectors": [],
            "platform_servers": [],
            "tools": [],
            "approval_by_tool_id": {},
            "missing_catalog_keys": [],
        }

    return {
        "configured_catalog_keys": configured_keys,
        "connectors": connectors,
        "platform_servers": platform_servers,
        "tools": tools,
        "approval_by_tool_id": approval_by_tool_id,
        "missing_catalog_keys": missing,
    }


def connector_context_for_agent(
    db: Session,
    *,
    connectors: List[UserConnector],
    tools: List[Tool],
    configured_catalog_keys: Optional[List[str]] = None,
    missing_catalog_keys: Optional[List[str]] = None,
    platform_servers: Optional[List[McpServer]] = None,
) -> str:
    lines: List[str] = []
    tools_by_server: Dict[str, List[Tool]] = {}
    for t in tools or []:
        sid = t.mcp_server_id or ""
        tools_by_server.setdefault(sid, []).append(t)

    for row in connectors or []:
        cfg = row.connector_config or {}
        server_tools = tools_by_server.get(row.mcp_server_id) or []
        tool_names = [t.name for t in server_tools if t.name]
        tools_part = (
            f"可用 MCP 工具: {', '.join(tool_names)}"
            if tool_names
            else "尚未同步到可用工具"
        )
        if row.catalog_key == "feishu_group" and cfg.get("default_chat_id"):
            lines.append(
                f"- 飞书连接器 [{row.display_name}] 默认群 chat_id: {cfg['default_chat_id']}；{tools_part}"
            )
        elif row.catalog_key == "dingtalk_group" and cfg.get("default_open_conversation_id"):
            lines.append(
                f"- 钉钉连接器 [{row.display_name}] 默认群 openConversationId: "
                f"{cfg['default_open_conversation_id']}；{tools_part}"
            )
        elif row.catalog_key == "email":
            lines.append(
                f"- Email 连接器 [{row.display_name}] 已启用；{tools_part}。"
                "必须直接调用上述 MCP 工具读写邮件，禁止用 execute_code 虚构 email_connector / list_emails 等 API。"
            )
        elif row.catalog_key == "github":
            lines.append(f"- GitHub 连接器 [{row.display_name}] 已启用；{tools_part}")
        else:
            lines.append(f"- 连接器 [{row.display_name}]（{row.catalog_key}）已启用；{tools_part}")

    for server in platform_servers or []:
        server_tools = tools_by_server.get(server.server_id) or []
        tool_names = [t.name for t in server_tools if t.name]
        tools_part = (
            f"可用 MCP 工具: {', '.join(tool_names)}"
            if tool_names
            else "尚未同步到可用工具"
        )
        label = server.display_name or server.name
        lines.append(f"- MCP Server [{label}] 已启用；{tools_part}")

    missing_lines = []
    for key in missing_catalog_keys or []:
        if is_platform_mcp_binding(key):
            sid = platform_mcp_server_id(key)
            missing_lines.append(f"- Agent 已配置平台 MCP Server（{sid}），但该 Server 不存在或不可用")
            continue
        tmpl = get_catalog_template(key) or {}
        label = tmpl.get("display_name") or key
        missing_lines.append(f"- Agent 已配置「{label}」({key})，但当前用户尚未连接该类连接器")

    if not lines and not missing_lines:
        if configured_catalog_keys:
            return (
                "Agent 已配置连接器/MCP，但当前没有可用实例。"
                "请先到连接器页完成连接与同步。"
            )
        return ""

    parts = []
    if lines:
        parts.append(
            "当前可用连接器（工具已直接可用，无需再 tool_search）：\n" + "\n".join(lines)
        )
    if missing_lines:
        parts.append("以下连接器尚未就绪：\n" + "\n".join(missing_lines))
    return "\n".join(parts)
