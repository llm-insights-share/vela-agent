from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.mcp.config import AUTH_BEARER, AUTH_NONE, AUTH_OAUTH, TRANSPORT_STDIO, TRANSPORT_STREAMABLE_HTTP
from services.mcp.crypto import encrypt_secret

ENC_PREFIX = "enc:"

SECRET_ENV_KEYS = {
    "EMAIL_PASS",
    "DINGTALK_Client_Secret",
    "DINGTALK_APP_SECRET",
}


def store_secret(value: str) -> str:
    if not value:
        return ""
    return f"{ENC_PREFIX}{encrypt_secret(value)}"


def is_stored_secret(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(ENC_PREFIX)


EMAIL_PROVIDER_PRESETS: Dict[str, Dict[str, Any]] = {
    "163": {
        "label": "网易 163",
        "imap_host": "imap.163.com",
        "imap_port": 993,
        "imap_secure": True,
        "smtp_host": "smtp.163.com",
        "smtp_port": 465,
        "smtp_secure": True,
        "auth_hint": "请使用邮箱设置里开启 IMAP 后生成的「客户端授权码」，不要填网页登录密码。",
    },
    "qq": {
        "label": "腾讯 QQ 邮箱",
        "imap_host": "imap.qq.com",
        "imap_port": 993,
        "imap_secure": True,
        "smtp_host": "smtp.qq.com",
        "smtp_port": 465,
        "smtp_secure": True,
    },
    "outlook": {
        "label": "Outlook / Office365",
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
        "imap_secure": True,
        "smtp_host": "smtp.office365.com",
        "smtp_port": 587,
        "smtp_secure": True,
    },
    "custom": {
        "label": "自定义",
        "imap_host": "",
        "imap_port": 993,
        "imap_secure": True,
        "smtp_host": "",
        "smtp_port": 465,
        "smtp_secure": True,
    },
}


CATALOG_TEMPLATES: List[Dict[str, Any]] = [
    {
        "catalog_key": "github",
        "display_name": "GitHub",
        "description": "仓库、Issue、Pull Request 与 Actions",
        "icon": "github",
        "help_url": "https://github.com/github/github-mcp-server",
        "auth_mode": "pat",
        "required_fields": [
            {"key": "access_token", "label": "Personal Access Token", "type": "password", "required": True},
        ],
        "optional_config_fields": [
            {"key": "readonly", "label": "只读模式", "type": "boolean", "default": True},
        ],
        "default_tools": [
            {"name": "create_or_update_file", "description": "创建或更新文件"},
            {"name": "search_repositories", "description": "搜索仓库"},
            {"name": "create_repository", "description": "创建仓库"},
            {"name": "get_file_contents", "description": "读取文件内容"},
            {"name": "push_files", "description": "推送多个文件"},
            {"name": "create_issue", "description": "创建 Issue"},
            {"name": "create_pull_request", "description": "创建 Pull Request"},
            {"name": "fork_repository", "description": "Fork 仓库"},
            {"name": "create_branch", "description": "创建分支"},
            {"name": "list_commits", "description": "列出提交"},
            {"name": "list_issues", "description": "列出 Issues"},
            {"name": "update_issue", "description": "更新 Issue"},
            {"name": "add_issue_comment", "description": "添加 Issue 评论"},
            {"name": "search_code", "description": "搜索代码"},
            {"name": "search_issues", "description": "搜索 Issues"},
            {"name": "search_users", "description": "搜索用户"},
            {"name": "get_issue", "description": "获取 Issue"},
            {"name": "get_pull_request", "description": "获取 Pull Request"},
            {"name": "list_pull_requests", "description": "列出 Pull Requests"},
            {"name": "create_pull_request_review", "description": "创建 PR Review"},
            {"name": "merge_pull_request", "description": "合并 Pull Request"},
            {"name": "get_pull_request_files", "description": "获取 PR 文件"},
            {"name": "get_pull_request_status", "description": "获取 PR 状态"},
            {"name": "update_pull_request_branch", "description": "更新 PR 分支"},
            {"name": "get_pull_request_comments", "description": "获取 PR 评论"},
            {"name": "get_pull_request_reviews", "description": "获取 PR Reviews"},
        ],
    },
    {
        "catalog_key": "email",
        "display_name": "Email",
        "description": "标准 IMAP/SMTP 邮件服务器（企业邮、163、QQ 等）",
        "icon": "mail",
        "help_url": "https://github.com/yunfeizhu/mcp-mail-server",
        "auth_mode": "credentials",
        "provider_presets": EMAIL_PROVIDER_PRESETS,
        "required_fields": [
            {"key": "email_address", "label": "邮箱地址", "type": "text", "required": True},
            {
                "key": "password",
                "label": "客户端授权码 / 应用专用密码",
                "type": "password",
                "required": True,
                "help": "163/QQ 等需使用客户端授权码，不是网页登录密码",
            },
            {"key": "imap_host", "label": "IMAP 主机", "type": "text", "required": True},
            {"key": "imap_port", "label": "IMAP 端口", "type": "number", "default": 993},
            {"key": "imap_secure", "label": "IMAP TLS", "type": "boolean", "default": True},
            {"key": "smtp_host", "label": "SMTP 主机", "type": "text", "required": True},
            {"key": "smtp_port", "label": "SMTP 端口", "type": "number", "default": 465},
            {"key": "smtp_secure", "label": "SMTP TLS", "type": "boolean", "default": True},
        ],
        "optional_config_fields": [
            {"key": "provider_hint", "label": "服务商", "type": "select", "options": list(EMAIL_PROVIDER_PRESETS.keys())},
            {"key": "use_same_host", "label": "SMTP 与 IMAP 同主机", "type": "boolean", "default": False},
        ],
        "default_tools": [
            {"name": "check_connection", "description": "检查 IMAP/SMTP 连接"},
            {"name": "list_mailboxes", "description": "列出邮箱文件夹"},
            {"name": "search_messages", "description": "搜索邮件"},
            {"name": "find_unreplied_messages", "description": "查找未回复邮件"},
            {"name": "get_message", "description": "获取单封邮件"},
            {"name": "get_messages", "description": "批量获取邮件"},
            {"name": "send_email", "description": "发送邮件"},
            {"name": "reply_to_email", "description": "回复邮件"},
            {"name": "continue_email_thread", "description": "继续邮件线程"},
            {"name": "move_message", "description": "移动邮件"},
            {"name": "delete_message", "description": "删除邮件"},
            {"name": "save_attachment", "description": "保存附件"},
        ],
    },
    {
        "catalog_key": "feishu_group",
        "display_name": "飞书群会话",
        "description": "飞书群消息发送与会话管理",
        "icon": "feishu",
        "help_url": "https://github.com/larksuite/lark-openapi-mcp",
        "auth_mode": "app_credentials",
        "required_fields": [
            {"key": "app_id", "label": "App ID", "type": "text", "required": True},
            {"key": "app_secret", "label": "App Secret", "type": "password", "required": True},
        ],
        "optional_config_fields": [
            {"key": "default_chat_id", "label": "默认群 chat_id", "type": "text", "required": False},
        ],
        "default_tools": [
            {"name": "im.v1.message.create", "description": "发送消息"},
            {"name": "im.v1.chat.list", "description": "列出群聊"},
            {"name": "im.v1.chatMembers.get", "description": "获取群成员"},
        ],
    },
    {
        "catalog_key": "dingtalk_group",
        "display_name": "钉钉群会话",
        "description": "钉钉群机器人消息与工作通知",
        "icon": "dingtalk",
        "help_url": "https://open.dingtalk.com/document/ai-dev/dingtalk-server-api-mcp-overview.md",
        "auth_mode": "app_credentials",
        "required_fields": [
            {"key": "app_key", "label": "AppKey", "type": "text", "required": True},
            {"key": "app_secret", "label": "AppSecret", "type": "password", "required": True},
        ],
        "optional_config_fields": [
            {"key": "default_open_conversation_id", "label": "默认群 openConversationId", "type": "text", "required": False},
        ],
        "default_tools": [
            {"name": "send_message", "description": "发送群消息"},
            {"name": "send_work_notification", "description": "发送工作通知"},
        ],
    },
    {
        "catalog_key": "custom",
        "display_name": "自定义 MCP",
        "description": "手动配置任意 MCP Server（stdio / HTTP）",
        "icon": "api",
        "help_url": "",
        "auth_mode": "custom",
        "required_fields": [],
        "default_tools": [],
    },
]


def list_catalog_templates() -> List[Dict[str, Any]]:
    return [dict(t) for t in CATALOG_TEMPLATES if t["catalog_key"] != "custom"] + [
        next(t for t in CATALOG_TEMPLATES if t["catalog_key"] == "custom")
    ]


def get_catalog_template(catalog_key: str) -> Optional[Dict[str, Any]]:
    for item in CATALOG_TEMPLATES:
        if item["catalog_key"] == catalog_key:
            return dict(item)
    return None


def _slug_name(raw: str, fallback: str = "connector") -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", (raw or "").strip()).strip("_").lower()
    return (s[:64] or fallback)


def _bool_str(value: Any, default: bool = True) -> str:
    if value is None:
        return "true" if default else "false"
    if isinstance(value, bool):
        return "true" if value else "false"
    return "true" if str(value).lower() in ("1", "true", "yes", "on") else "false"


def build_mcp_server_payload(
    *,
    catalog_key: str,
    credentials: Dict[str, Any],
    connector_config: Optional[Dict[str, Any]] = None,
    user_id: str,
    name: str,
    display_name: str = "",
    description: str = "",
) -> Dict[str, Any]:
    cfg = dict(connector_config or {})
    slug = _slug_name(name, catalog_key)
    server_name = f"uc_{user_id[:8]}_{catalog_key}_{slug}"

    if catalog_key == "github":
        token = str(credentials.get("access_token") or "").strip()
        if not token:
            raise ValueError("缺少 access_token")
        readonly = cfg.get("readonly", True)
        headers = {"Authorization": f"Bearer {store_secret(token)}"}
        if readonly:
            headers["X-MCP-Readonly"] = "true"
        return {
            "name": server_name,
            "display_name": display_name or "GitHub",
            "description": description or "GitHub MCP 连接器",
            "transport": TRANSPORT_STREAMABLE_HTTP,
            "url": "https://api.githubcopilot.com/mcp/",
            "headers": headers,
            "auth_type": AUTH_BEARER,
            "command": "",
            "args": [],
            "env": {},
        }

    if catalog_key == "email":
        email = str(credentials.get("email_address") or "").strip()
        password = str(credentials.get("password") or "")
        imap_host = str(credentials.get("imap_host") or "").strip()
        smtp_host = str(credentials.get("smtp_host") or "").strip()
        if cfg.get("use_same_host") and imap_host and not smtp_host:
            smtp_host = imap_host
        if not email or not password or not imap_host or not smtp_host:
            raise ValueError("Email 连接器缺少邮箱地址、密码或服务器配置")
        runner = Path(__file__).resolve().parent.parent / "mcp_wrappers" / "run_mcp_mail.mjs"
        return {
            "name": server_name,
            "display_name": display_name or email,
            "description": description or f"Email: {email}",
            "transport": TRANSPORT_STDIO,
            "command": "node",
            "args": [str(runner)] if runner.is_file() else ["-y", "mcp-mail-server"],
            "env": {
                "EMAIL_USER": email,
                "EMAIL_ADDRESS": email,
                "EMAIL_PASS": store_secret(password),
                "IMAP_HOST": imap_host,
                "IMAP_PORT": str(credentials.get("imap_port") or 993),
                "IMAP_SECURE": _bool_str(credentials.get("imap_secure"), True),
                "SMTP_HOST": smtp_host,
                "SMTP_PORT": str(credentials.get("smtp_port") or 465),
                "SMTP_SECURE": _bool_str(credentials.get("smtp_secure"), True),
            },
            "url": "",
            "headers": {},
            "auth_type": AUTH_NONE,
        }

    if catalog_key == "feishu_group":
        app_id = str(credentials.get("app_id") or "").strip()
        app_secret = str(credentials.get("app_secret") or "").strip()
        if not app_id or not app_secret:
            raise ValueError("飞书连接器缺少 App ID 或 App Secret")
        from pathlib import Path

        runner = Path(__file__).resolve().parent.parent / "mcp_wrappers" / "run_lark_mcp.mjs"
        if runner.is_file():
            command = "node"
            args = [
                str(runner),
                "mcp",
                "-a",
                app_id,
                "-s",
                app_secret,
                "-d",
                "https://open.feishu.cn",
                "--token-mode",
                "tenant_access_token",
            ]
        else:
            command = "npx"
            args = [
                "-y",
                "@larksuiteoapi/lark-mcp",
                "mcp",
                "-a",
                app_id,
                "-s",
                app_secret,
                "-d",
                "https://open.feishu.cn",
                "--token-mode",
                "tenant_access_token",
            ]
        return {
            "name": server_name,
            "display_name": display_name or "飞书群会话",
            "description": description or "飞书 OpenAPI MCP",
            "transport": TRANSPORT_STDIO,
            "command": command,
            "args": args,
            "env": {},
            "url": "",
            "headers": {},
            "auth_type": AUTH_NONE,
        }

    if catalog_key == "dingtalk_group":
        app_key = str(credentials.get("app_key") or "").strip()
        app_secret = str(credentials.get("app_secret") or "").strip()
        if not app_key or not app_secret:
            raise ValueError("钉钉连接器缺少 AppKey 或 AppSecret")
        return {
            "name": server_name,
            "display_name": display_name or "钉钉群会话",
            "description": description or "钉钉 OpenAPI MCP",
            "transport": TRANSPORT_STDIO,
            "command": "npx",
            "args": ["-y", "dingtalk-mcp@latest"],
            "env": {
                "DINGTALK_Client_ID": app_key,
                "DINGTALK_Client_Secret": store_secret(app_secret),
                "ACTIVE_PROFILES": "dingtalk-robot,dingtalk-contacts",
            },
            "url": "",
            "headers": {},
            "auth_type": AUTH_NONE,
        }

    raise ValueError(f"未知目录模板: {catalog_key}")
