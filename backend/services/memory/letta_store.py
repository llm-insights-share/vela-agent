"""Letta-backed memory store: client factory, agent mapping, blocks & passages.

All public methods fail-open: Letta unavailability never breaks the chat loop.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import yaml
from sqlalchemy.orm import Session

from models import (
    Agent,
    LettaMemoryAgent,
    ModelProvider,
    ModelService,
    ModelServiceStatus,
    User,
    gen_uuid,
)

logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "vela.yaml")
EMBEDDING_DIM = 1024  # BAAI/bge-large-zh-v1.5
EMBEDDING_MODEL = "vela-embedding"

_client_cache = None
_client_cfg_key = None

BLOCK_LABELS = ("user_pref", "task_context", "tool_profile")

DISTILL_PROMPT = """你是长期记忆管理助手。请根据以下会话转录，更新核心记忆；仅在有可复用模式时写入归档。

分层（必须遵守）：
- user_pref：用户稳定偏好与个人事实（生日、每日开场习惯、输出格式、沟通风格）。这些内容只写这里，禁止再写入归档。
- task_context：尚未完成的近期任务目标与进展。已完成的「记住 XX」不要留在这里，应删除或留空。
- archival（archival_memory_insert）：短、可检索的经验模式（如何处理某类请求），不含偏好正文、不含操作说明书、不含流水账。

要求：
1. 用 memory_replace / memory_insert 更新 user_pref / task_context
2. 归档仅在出现可复用模式时写入 1 条以内，tags 含 experience 或 task_summary，以及 session:{session_id}
3. 不要记录一次性指令；不要把 user_pref 已有内容复制进归档
4. 若无明显可记内容，可不调用工具，直接简短确认即可

会话 ID: {session_id}

会话转录：
{transcript}
"""


def load_letta_config() -> dict:
    cfg: dict = {}
    if os.path.isfile(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            root = yaml.safe_load(f) or {}
        cfg = dict((root.get("memory") or {}).get("letta") or {})
    # Env overrides
    if os.getenv("LETTA_BASE_URL"):
        cfg["base_url"] = os.getenv("LETTA_BASE_URL")
    if os.getenv("LETTA_SERVER_PASSWORD"):
        cfg["password"] = os.getenv("LETTA_SERVER_PASSWORD")
    if os.getenv("VELA_LLM_GATEWAY_TOKEN"):
        cfg["gateway_token"] = os.getenv("VELA_LLM_GATEWAY_TOKEN")
    cfg.setdefault("enabled", True)
    cfg.setdefault("base_url", "http://127.0.0.1:8283")
    cfg.setdefault("password", "vela-letta-dev")
    cfg.setdefault("gateway_base", "http://127.0.0.1:8000")
    cfg.setdefault("gateway_token", "vela-local-gateway")
    cfg.setdefault("distill_model_service_id", "")
    return cfg


def is_letta_enabled() -> bool:
    return bool(load_letta_config().get("enabled", True))


def get_client():
    """Lazy cached Letta client. Returns None if disabled or SDK missing."""
    global _client_cache, _client_cfg_key
    if not is_letta_enabled():
        return None
    cfg = load_letta_config()
    key = (cfg.get("base_url"), cfg.get("password"), 60.0)
    if _client_cache is not None and _client_cfg_key == key:
        return _client_cache
    try:
        from letta_client import Letta
    except ImportError:
        logger.warning("[letta_store] letta-client not installed")
        return None
    try:
        client = Letta(
            base_url=cfg["base_url"],
            api_key=cfg.get("password") or None,
            timeout=60.0,
            max_retries=1,
        )
        _client_cache = client
        _client_cfg_key = key
        return client
    except Exception as e:
        logger.warning(f"[letta_store] client init failed: {e}")
        return None


def health() -> Dict[str, Any]:
    cfg = load_letta_config()
    result = {
        "enabled": bool(cfg.get("enabled", True)),
        "healthy": False,
        "base_url": cfg.get("base_url", ""),
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dim": EMBEDDING_DIM,
        "error": None,
        "version": None,
    }
    if not result["enabled"]:
        result["error"] = "disabled"
        return result
    client = get_client()
    if client is None:
        result["error"] = "client_unavailable"
        return result
    try:
        # Prefer health endpoint if present; otherwise list agents as connectivity probe
        if hasattr(client, "health") and callable(getattr(client, "health", None)):
            try:
                h = client.health.check() if hasattr(client.health, "check") else client.health()
                result["version"] = getattr(h, "version", None) or str(h)
            except Exception:
                # Fallback probe
                list(client.agents.list(limit=1))
        else:
            list(client.agents.list(limit=1))
        result["healthy"] = True
    except Exception as e:
        result["error"] = str(e)
        logger.warning(f"[letta_store] health check failed: {e}")
    return result


def _pick_model_service(db: Session, agent: Agent) -> Optional[ModelService]:
    cfg = load_letta_config()
    distill_id = (cfg.get("distill_model_service_id") or "").strip()
    if distill_id:
        svc = db.query(ModelService).filter(ModelService.model_service_id == distill_id).first()
        if svc:
            return svc
    if agent.model_service_id:
        svc = (
            db.query(ModelService)
            .filter(ModelService.model_service_id == agent.model_service_id)
            .first()
        )
        if svc:
            return svc
    return (
        db.query(ModelService)
        .filter(ModelService.status == ModelServiceStatus.ACTIVE)
        .first()
    )


def ensure_memory_agent(db: Session, agent_id: str, user_id: str = "") -> Optional[str]:
    """Return Letta agent id for (agent_id, user_id), creating if needed."""
    user_id = user_id or ""
    existing = (
        db.query(LettaMemoryAgent)
        .filter(
            LettaMemoryAgent.agent_id == agent_id,
            LettaMemoryAgent.user_id == user_id,
        )
        .first()
    )
    if existing:
        return existing.letta_agent_id

    client = get_client()
    if client is None:
        return None

    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if not agent:
        logger.warning(f"[letta_store] agent not found: {agent_id}")
        return None

    model_svc = _pick_model_service(db, agent)
    if not model_svc:
        logger.warning("[letta_store] no ModelService available for memory agent")
        return None

    cfg = load_letta_config()
    gateway_base = (cfg.get("gateway_base") or "http://127.0.0.1:8000").rstrip("/")
    endpoint = f"{gateway_base}/llm-gateway/v1"

    name = f"vela-mem-{agent_id[:8]}-{(user_id[:8] if user_id else 'anon')}"
    try:
        created = client.agents.create(
            name=name,
            llm_config={
                "model": model_svc.model_name,
                "model_endpoint_type": "openai",
                "model_endpoint": endpoint,
                "context_window": 32768,
            },
            embedding_config={
                "embedding_model": EMBEDDING_MODEL,
                "embedding_endpoint_type": "openai",
                "embedding_endpoint": endpoint,
                "embedding_dim": EMBEDDING_DIM,
                "embedding_chunk_size": 300,
            },
            memory_blocks=[
                {
                    "label": "user_pref",
                    "value": "",
                    "limit": 2000,
                    "description": "用户稳定偏好：时间安排、输出格式、沟通风格",
                },
                {
                    "label": "task_context",
                    "value": "",
                    "limit": 2000,
                    "description": "近期任务目标与进展",
                },
                {
                    "label": "tool_profile",
                    "value": "",
                    "limit": 1500,
                    "description": "工具调用画像（由 vela 统计写入）",
                    "read_only": True,
                },
            ],
            tools=[
                "memory_replace",
                "memory_insert",
                "archival_memory_insert",
                "archival_memory_search",
            ],
            include_base_tools=False,
        )
        letta_id = getattr(created, "id", None) or (created.get("id") if isinstance(created, dict) else None)
        if not letta_id:
            logger.warning(f"[letta_store] create returned no id: {created}")
            return None

        mapping = LettaMemoryAgent(
            mapping_id=gen_uuid(),
            agent_id=agent_id,
            user_id=user_id,
            letta_agent_id=letta_id,
        )
        db.add(mapping)
        db.commit()
        db.refresh(mapping)
        logger.info(f"[letta_store] created memory agent {letta_id} for {agent_id}/{user_id}")
        return letta_id
    except Exception as e:
        logger.warning(f"[letta_store] ensure_memory_agent failed: {e}")
        try:
            db.rollback()
        except Exception:
            pass
        return None


def _block_to_dict(b) -> Dict[str, Any]:
    if isinstance(b, dict):
        return {
            "label": b.get("label", ""),
            "value": b.get("value", "") or "",
            "limit": b.get("limit") or 2000,
            "description": b.get("description") or "",
            "read_only": bool(b.get("read_only", False)),
            "id": b.get("id"),
        }
    return {
        "label": getattr(b, "label", "") or "",
        "value": getattr(b, "value", "") or "",
        "limit": getattr(b, "limit", None) or 2000,
        "description": getattr(b, "description", "") or "",
        "read_only": bool(getattr(b, "read_only", False)),
        "id": getattr(b, "id", None),
    }


def read_blocks(db: Session, agent_id: str, user_id: str = "") -> List[Dict[str, Any]]:
    try:
        letta_id = ensure_memory_agent(db, agent_id, user_id)
        if not letta_id:
            return []
        client = get_client()
        if client is None:
            return []
        blocks = client.agents.blocks.list(agent_id=letta_id)
        items = list(blocks) if not isinstance(blocks, list) else blocks
        # SyncArrayPage may wrap items
        if hasattr(blocks, "items"):
            items = list(blocks.items)
        out = [_block_to_dict(b) for b in items]
        order = {lab: i for i, lab in enumerate(BLOCK_LABELS)}
        out.sort(key=lambda b: order.get(b.get("label") or "", 99))
        return out
    except Exception as e:
        logger.warning(f"[letta_store] read_blocks failed: {e}")
        return []


def update_block(
    db: Session,
    agent_id: str,
    label: str,
    value: str,
    user_id: str = "",
) -> Optional[Dict[str, Any]]:
    try:
        letta_id = ensure_memory_agent(db, agent_id, user_id)
        if not letta_id:
            return None
        client = get_client()
        if client is None:
            return None
        updated = client.agents.blocks.update(
            label,
            agent_id=letta_id,
            value=value,
        )
        return _block_to_dict(updated)
    except Exception as e:
        logger.warning(f"[letta_store] update_block failed: {e}")
        return None


def _passage_to_dict(p, rank: Optional[int] = None) -> Dict[str, Any]:
    if isinstance(p, dict):
        d = {
            "id": p.get("id") or p.get("passage_id") or "",
            "content": p.get("content") or p.get("text") or "",
            "tags": p.get("tags") or [],
            "created_at": p.get("created_at") or p.get("timestamp"),
            "metadata": p.get("metadata") or {},
        }
    else:
        d = {
            "id": getattr(p, "id", None) or "",
            "content": getattr(p, "content", None) or getattr(p, "text", "") or "",
            "tags": getattr(p, "tags", None) or [],
            "created_at": getattr(p, "created_at", None) or getattr(p, "timestamp", None),
            "metadata": getattr(p, "metadata", None) or {},
        }
    if rank is not None:
        d["rank"] = rank
    return d


def search_passages(
    db: Session,
    agent_id: str,
    query: str,
    user_id: str = "",
    tags: Optional[List[str]] = None,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    try:
        letta_id = ensure_memory_agent(db, agent_id, user_id)
        if not letta_id or not (query or "").strip():
            return []
        client = get_client()
        if client is None:
            return []
        kwargs: Dict[str, Any] = {"query": query, "top_k": top_k}
        if tags:
            kwargs["tags"] = tags
        resp = client.agents.passages.search(letta_id, **kwargs)
        results = getattr(resp, "results", None)
        if results is None and isinstance(resp, dict):
            results = resp.get("results") or []
        if results is None:
            results = list(resp) if resp else []
        out = []
        for i, r in enumerate(results):
            if isinstance(r, dict):
                out.append(
                    {
                        "id": r.get("id", ""),
                        "content": r.get("content") or r.get("text") or "",
                        "tags": r.get("tags") or [],
                        "created_at": r.get("timestamp") or r.get("created_at"),
                        "rank": i + 1,
                    }
                )
            else:
                out.append(
                    {
                        "id": getattr(r, "id", "") or "",
                        "content": getattr(r, "content", None) or getattr(r, "text", "") or "",
                        "tags": getattr(r, "tags", None) or [],
                        "created_at": getattr(r, "timestamp", None) or getattr(r, "created_at", None),
                        "rank": i + 1,
                    }
                )
        return out
    except Exception as e:
        logger.warning(f"[letta_store] search_passages failed: {e}")
        return []


def list_passages(
    db: Session,
    agent_id: str,
    user_id: str = "",
    limit: int = 50,
    after: Optional[str] = None,
) -> List[Dict[str, Any]]:
    try:
        letta_id = ensure_memory_agent(db, agent_id, user_id)
        if not letta_id:
            return []
        client = get_client()
        if client is None:
            return []
        kwargs: Dict[str, Any] = {"limit": limit, "ascending": False}
        if after:
            kwargs["after"] = after
        resp = client.agents.passages.list(letta_id, **kwargs)
        items = list(resp) if not isinstance(resp, list) else resp
        if hasattr(resp, "items"):
            items = list(resp.items)
        return [_passage_to_dict(p) for p in items]
    except Exception as e:
        logger.warning(f"[letta_store] list_passages failed: {e}")
        return []


def insert_passage(
    db: Session,
    agent_id: str,
    text: str,
    user_id: str = "",
    tags: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    try:
        letta_id = ensure_memory_agent(db, agent_id, user_id)
        if not letta_id:
            logger.warning(
                "[letta_store] insert_passage: no memory agent for %s/%s",
                agent_id[:12], (user_id or "")[:12] or "anon",
            )
            return None
        client = get_client()
        if client is None:
            logger.warning("[letta_store] insert_passage: client unavailable")
            return None
        kwargs: Dict[str, Any] = {"text": text}
        if tags:
            kwargs["tags"] = tags
        created = client.agents.passages.create(letta_id, **kwargs)
        # API may return a list
        if isinstance(created, list) and created:
            return _passage_to_dict(created[0])
        if hasattr(created, "__iter__") and not isinstance(created, (str, dict)):
            items = list(created)
            if items:
                return _passage_to_dict(items[0])
        return _passage_to_dict(created)
    except Exception as e:
        logger.warning(f"[letta_store] insert_passage failed: {e}")
        return None


def delete_passage(
    db: Session,
    agent_id: str,
    passage_id: str,
    user_id: str = "",
) -> bool:
    try:
        letta_id = ensure_memory_agent(db, agent_id, user_id)
        if not letta_id:
            return False
        client = get_client()
        if client is None:
            return False
        client.agents.passages.delete(passage_id, agent_id=letta_id)
        return True
    except Exception as e:
        logger.warning(f"[letta_store] delete_passage failed: {e}")
        return False


def distill_session(
    db: Session,
    agent_id: str,
    user_id: str,
    session_id: str,
    transcript: str,
) -> Dict[str, Any]:
    """Ask the Letta memory agent to update blocks / archival from a transcript."""
    try:
        letta_id = ensure_memory_agent(db, agent_id, user_id)
        if not letta_id:
            return {"ok": False, "error": "no_memory_agent"}
        client = get_client()
        if client is None:
            return {"ok": False, "error": "client_unavailable"}
        content = DISTILL_PROMPT.format(
            session_id=session_id,
            transcript=(transcript or "")[:12000],
        )
        resp = client.agents.messages.create(
            agent_id=letta_id,
            messages=[{"role": "user", "content": content}],
        )
        return {"ok": True, "response": str(resp)[:500]}
    except Exception as e:
        logger.warning(f"[letta_store] distill_session failed: {e}")
        return {"ok": False, "error": str(e)}


def list_scopes(db: Session) -> List[Dict[str, Any]]:
    rows = db.query(LettaMemoryAgent).order_by(LettaMemoryAgent.created_at.desc()).all()
    user_ids = {r.user_id for r in rows if (r.user_id or "").strip()}
    username_by_id: Dict[str, str] = {}
    if user_ids:
        for u in db.query(User).filter(User.user_id.in_(user_ids)).all():
            username_by_id[u.user_id] = u.username or ""
    return [
        {
            "mapping_id": r.mapping_id,
            "agent_id": r.agent_id,
            "user_id": r.user_id or "",
            "username": username_by_id.get(r.user_id or "", "") or (r.user_id or ""),
            "letta_agent_id": r.letta_agent_id,
            "created_at": r.created_at,
        }
        for r in rows
    ]
