import os
import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List
from sqlalchemy.orm import Session

from database import get_db
from models import Agent, AgentStatus
from schemas import (
    MemoryAgentMountUpdate,
    MemoryAgentMountResponse,
    QueryRewriteAgentMountUpdate,
    QueryRewriteAgentMountResponse,
    LettaConfigResponse,
    LettaConfigUpdate,
)

router = APIRouter(prefix="/api/v1/config", tags=["config"])

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "vela.yaml")


def _load_config() -> dict:
    if not os.path.isfile(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _save_config(config: dict):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)


class TavilyConfigUpdate(BaseModel):
    api_key: str = ""


class ToolConfigResponse(BaseModel):
    tavily: dict = {}


@router.get("/tools", response_model=ToolConfigResponse)
def get_tool_config():
    config = _load_config()
    tools = config.get("tools", {})
    tavily = tools.get("tavily", {})
    # 隐藏 api_key 中间部分
    masked = dict(tavily)
    key = masked.get("api_key", "")
    if key and len(key) > 8:
        masked["api_key"] = key[:4] + "*" * (len(key) - 8) + key[-4:]
    elif key:
        masked["api_key"] = "****"
    return ToolConfigResponse(tavily=masked)


@router.put("/tools/tavily")
def update_tavily_config(data: TavilyConfigUpdate):
    config = _load_config()
    if "tools" not in config:
        config["tools"] = {}
    if "tavily" not in config["tools"]:
        config["tools"]["tavily"] = {}
    config["tools"]["tavily"]["api_key"] = data.api_key
    _save_config(config)
    return {"message": "Tavily 配置已保存"}


@router.get("/tools/tavily/status")
def tavily_status():
    config = _load_config()
    api_key = (config.get("tools", {}).get("tavily", {}).get("api_key", "")) or ""
    return {"configured": bool(api_key), "api_key_set": bool(api_key)}


@router.get("/memory/agents", response_model=List[MemoryAgentMountResponse])
def list_memory_agent_mounts(db: Session = Depends(get_db)):
    agents = (
        db.query(Agent)
        .filter(Agent.status != AgentStatus.DELETED)
        .order_by(Agent.name.asc())
        .all()
    )
    return [
        MemoryAgentMountResponse(
            agent_id=a.agent_id,
            name=a.name,
            status=a.status.value if hasattr(a.status, "value") else str(a.status),
            memory_enabled=bool(getattr(a, "memory_enabled", False)),
        )
        for a in agents
    ]


@router.put("/memory/agents")
def update_memory_agent_mounts(data: MemoryAgentMountUpdate, db: Session = Depends(get_db)):
    if not data.items:
        return {"message": "无变更", "updated": 0}
    updated = 0
    for item in data.items:
        agent = db.query(Agent).filter(Agent.agent_id == item.agent_id).first()
        if not agent or agent.status == AgentStatus.DELETED:
            continue
        agent.memory_enabled = bool(item.memory_enabled)
        updated += 1
    db.commit()
    return {"message": "记忆模块挂载配置已保存", "updated": updated}


@router.get("/memory/letta", response_model=LettaConfigResponse)
def get_letta_config():
    from services.memory.letta_store import EMBEDDING_DIM, EMBEDDING_MODEL, load_letta_config

    cfg = load_letta_config()
    password = cfg.get("password") or ""
    masked = password
    if password and len(password) > 4:
        masked = password[:2] + "*" * (len(password) - 4) + password[-2:]
    elif password:
        masked = "****"
    token = cfg.get("gateway_token") or ""
    masked_token = token
    if token and len(token) > 4:
        masked_token = token[:2] + "*" * (len(token) - 4) + token[-2:]
    elif token:
        masked_token = "****"
    return LettaConfigResponse(
        enabled=bool(cfg.get("enabled", True)),
        base_url=cfg.get("base_url") or "",
        password=masked,
        gateway_base=cfg.get("gateway_base") or "",
        gateway_token=masked_token,
        distill_model_service_id=cfg.get("distill_model_service_id") or "",
        embedding_model=EMBEDDING_MODEL,
        embedding_dim=EMBEDDING_DIM,
    )


@router.put("/memory/letta")
def update_letta_config(data: LettaConfigUpdate):
    config = _load_config()
    if "memory" not in config:
        config["memory"] = {}
    if "letta" not in config["memory"]:
        config["memory"]["letta"] = {}
    letta = config["memory"]["letta"]
    payload = data.model_dump(exclude_unset=True)
    for key, value in payload.items():
        if value is None:
            continue
        # 跳过掩码密码/token（前端未改时可能回传掩码）
        if key in ("password", "gateway_token") and "*" in str(value):
            continue
        letta[key] = value
    _save_config(config)
    # 清掉客户端缓存，下次用新配置
    try:
        from services.memory import letta_store
        letta_store._client_cache = None
        letta_store._client_cfg_key = None
    except Exception:
        pass
    return {"message": "Letta 记忆服务配置已保存"}


@router.get("/query-rewrite/agents", response_model=List[QueryRewriteAgentMountResponse])
def list_query_rewrite_agent_mounts(db: Session = Depends(get_db)):
    agents = (
        db.query(Agent)
        .filter(Agent.status != AgentStatus.DELETED)
        .order_by(Agent.name.asc())
        .all()
    )
    return [
        QueryRewriteAgentMountResponse(
            agent_id=a.agent_id,
            name=a.name,
            status=a.status.value if hasattr(a.status, "value") else str(a.status),
            query_rewrite_enabled=bool(getattr(a, "query_rewrite_enabled", False)),
        )
        for a in agents
    ]


@router.put("/query-rewrite/agents")
def update_query_rewrite_agent_mounts(
    data: QueryRewriteAgentMountUpdate, db: Session = Depends(get_db)
):
    if not data.items:
        return {"message": "无变更", "updated": 0}
    updated = 0
    for item in data.items:
        agent = db.query(Agent).filter(Agent.agent_id == item.agent_id).first()
        if not agent or agent.status == AgentStatus.DELETED:
            continue
        agent.query_rewrite_enabled = bool(item.query_rewrite_enabled)
        updated += 1
    db.commit()
    return {"message": "Query改写引擎挂载配置已保存", "updated": updated}


class ScreenpilotToggle(BaseModel):
    enabled: bool


@router.get("/screenpilot")
def get_screenpilot_config(db: Session = Depends(get_db)):
    from services.screenpilot.config import CU_TOOL_NAMES, is_screenpilot_enabled
    from services.screenpilot.mcp_tools import list_registered_cu_tools, register_cu_mcp_tools

    enabled = is_screenpilot_enabled()
    tools = list_registered_cu_tools(db)
    # 已打开但工具缺失（例如新增 cu_vision）时自动补齐并同步 Agent 绑定
    if enabled and len(tools) < len(CU_TOOL_NAMES):
        from services.screenpilot.mcp_tools import ensure_cu_tools_registered_and_bound

        ensure_cu_tools_registered_and_bound(db)
        tools = list_registered_cu_tools(db)
    return {
        "enabled": enabled,
        "mcp_registered": len(tools) >= len(CU_TOOL_NAMES),
        "expected_tools": list(CU_TOOL_NAMES),
        "tools": tools,
    }


@router.put("/screenpilot")
def update_screenpilot_config(data: ScreenpilotToggle, db: Session = Depends(get_db)):
    """打开驭屏系统：注册 cu_* MCP；关闭：移除相关 MCP。"""
    from services.screenpilot.config import set_screenpilot_enabled
    from services.screenpilot.mcp_tools import (
        list_registered_cu_tools,
        register_cu_mcp_tools,
        unregister_cu_mcp_tools,
    )

    if data.enabled:
        set_screenpilot_enabled(True)
        result = register_cu_mcp_tools(db)
        tools = list_registered_cu_tools(db)
        return {
            "enabled": True,
            "message": f"驭屏系统已打开，已注册 {len(tools)} 个 cu_* MCP 工具",
            "register": result,
            "tools": tools,
        }

    result = unregister_cu_mcp_tools(db)
    set_screenpilot_enabled(False)
    return {
        "enabled": False,
        "message": f"驭屏系统已关闭，已移除 {len(result.get('removed') or [])} 个 MCP 工具",
        "unregister": result,
        "tools": [],
    }
