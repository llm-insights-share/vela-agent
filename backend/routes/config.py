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
    CodeExecConfigResponse,
    CodeExecConfigUpdate,
    ContextualRetrievalConfigResponse,
    ContextualRetrievalConfigUpdate,
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


class WebSearchProviderUpdate(BaseModel):
    provider: str


class ToolConfigResponse(BaseModel):
    tavily: dict = {}
    web_search: dict = {}


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
    web_search = tools.get("web_search") or {}
    provider = str(web_search.get("provider") or "tavily").strip().lower()
    if provider not in ("tavily", "duckduckgo"):
        provider = "tavily"
    return ToolConfigResponse(
        tavily=masked,
        web_search={"provider": provider},
    )


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


@router.get("/tools/web-search")
def get_web_search_config():
    from services.builtin_tools import get_web_search_provider, is_duckduckgo_available

    config = _load_config()
    api_key = (config.get("tools", {}).get("tavily", {}).get("api_key", "")) or ""
    return {
        "provider": get_web_search_provider(),
        "tavily": {"configured": bool(api_key)},
        "duckduckgo": {"available": is_duckduckgo_available()},
    }


@router.put("/tools/web-search")
def update_web_search_config(data: WebSearchProviderUpdate):
    provider = (data.provider or "").strip().lower()
    if provider not in ("tavily", "duckduckgo"):
        raise HTTPException(status_code=400, detail="provider 须为 tavily 或 duckduckgo")
    config = _load_config()
    if "tools" not in config:
        config["tools"] = {}
    if "web_search" not in config["tools"]:
        config["tools"]["web_search"] = {}
    config["tools"]["web_search"]["provider"] = provider
    _save_config(config)
    return {"message": "Web Search 提供方已保存", "provider": provider}


class ToolSearchConfigUpdate(BaseModel):
    enabled: bool = False
    mode: str = "eager"
    search_backend: str = "bm25"
    max_results: int = 5
    max_loaded_per_session: int = 12
    always_loaded: List[str] = []


@router.get("/tools/tool-search")
def get_tool_search_config():
    from services.tool_search.config import load_tool_search_config
    from services.builtin_tools import get_active_web_search_tool_name

    cfg = load_tool_search_config()
    return {
        "enabled": cfg.enabled,
        "mode": cfg.mode,
        "search_backend": cfg.search_backend,
        "max_results": cfg.max_results,
        "max_loaded_per_session": cfg.max_loaded_per_session,
        "always_loaded": cfg.always_loaded,
        "active_web_search": get_active_web_search_tool_name(),
    }


@router.put("/tools/tool-search")
def update_tool_search_config(data: ToolSearchConfigUpdate):
    mode = (data.mode or "eager").strip().lower()
    if mode not in ("eager", "deferred"):
        raise HTTPException(status_code=400, detail="mode 须为 eager 或 deferred")
    backend = (data.search_backend or "bm25").strip().lower()
    if backend not in ("bm25", "keyword"):
        raise HTTPException(status_code=400, detail="search_backend 须为 bm25 或 keyword")

    config = _load_config()
    if "tools" not in config:
        config["tools"] = {}
    config["tools"]["tool_search"] = {
        "enabled": bool(data.enabled),
        "mode": mode,
        "search_backend": backend,
        "max_results": max(1, min(int(data.max_results or 5), 20)),
        "max_loaded_per_session": max(1, min(int(data.max_loaded_per_session or 12), 50)),
        "always_loaded": list(data.always_loaded or []),
    }
    _save_config(config)
    return {"message": "Tool Search 配置已保存", **config["tools"]["tool_search"]}


@router.get("/code-exec", response_model=CodeExecConfigResponse)
def get_code_exec_config():
    from services.code_exec.config import load_code_exec_config

    cfg = load_code_exec_config()
    return CodeExecConfigResponse(
        enabled=cfg.enabled,
        venv_path=cfg.venv_path,
        wall_timeout=cfg.wall_timeout,
        cpu_seconds=cfg.cpu_seconds,
        memory_mb=cfg.memory_mb,
        max_output_bytes=cfg.max_output_bytes,
        max_artifact_mb=cfg.max_artifact_mb,
        allow_network=cfg.allow_network,
        allow_install=cfg.allow_install,
        package_allowlist=cfg.package_allowlist,
        state_persist=cfg.state_persist,
    )


@router.put("/code-exec")
def update_code_exec_config(data: CodeExecConfigUpdate):
    from services.code_exec.config import CodeExecConfig, load_code_exec_config, save_code_exec_config

    cfg = load_code_exec_config()
    updates = data.model_dump(exclude_unset=True)
    for key, value in updates.items():
        if hasattr(cfg, key):
            setattr(cfg, key, value)
    save_code_exec_config(cfg)
    return {"message": "代码执行沙箱配置已保存"}


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


@router.get("/knowledge/contextual-retrieval", response_model=ContextualRetrievalConfigResponse)
def get_contextual_retrieval_config():
    from services.knowledge.config import load_contextual_retrieval_config

    cfg = load_contextual_retrieval_config()
    return ContextualRetrievalConfigResponse(
        enabled=cfg.enabled,
        model_service_id=cfg.model_service_id,
        max_concurrency=cfg.max_concurrency,
        chunk_timeout_seconds=cfg.chunk_timeout_seconds,
        prefix_max_tokens=cfg.prefix_max_tokens,
        temperature=cfg.temperature,
        min_chunk_length=cfg.min_chunk_length,
        document_excerpt_max_chars=cfg.document_excerpt_max_chars,
    )


@router.put("/knowledge/contextual-retrieval", response_model=ContextualRetrievalConfigResponse)
def update_contextual_retrieval_config(data: ContextualRetrievalConfigUpdate):
    from services.knowledge.config import (
        ContextualRetrievalConfig,
        load_contextual_retrieval_config,
        save_contextual_retrieval_config,
    )

    cfg = load_contextual_retrieval_config()
    updates = data.model_dump(exclude_unset=True)
    merged = ContextualRetrievalConfig(
        enabled=updates.get("enabled", cfg.enabled),
        model_service_id=updates.get("model_service_id", cfg.model_service_id),
        max_concurrency=updates.get("max_concurrency", cfg.max_concurrency),
        chunk_timeout_seconds=updates.get("chunk_timeout_seconds", cfg.chunk_timeout_seconds),
        prefix_max_tokens=updates.get("prefix_max_tokens", cfg.prefix_max_tokens),
        temperature=updates.get("temperature", cfg.temperature),
        min_chunk_length=updates.get("min_chunk_length", cfg.min_chunk_length),
        document_excerpt_max_chars=updates.get(
            "document_excerpt_max_chars", cfg.document_excerpt_max_chars
        ),
    )
    save_contextual_retrieval_config(merged)
    return ContextualRetrievalConfigResponse(
        enabled=merged.enabled,
        model_service_id=merged.model_service_id,
        max_concurrency=merged.max_concurrency,
        chunk_timeout_seconds=merged.chunk_timeout_seconds,
        prefix_max_tokens=merged.prefix_max_tokens,
        temperature=merged.temperature,
        min_chunk_length=merged.min_chunk_length,
        document_excerpt_max_chars=merged.document_excerpt_max_chars,
    )
