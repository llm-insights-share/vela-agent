import os
import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List
from sqlalchemy.orm import Session

from database import get_db
from models import Agent, AgentStatus
from schemas import MemoryAgentMountUpdate, MemoryAgentMountResponse

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
