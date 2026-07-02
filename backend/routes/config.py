import os
import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

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
