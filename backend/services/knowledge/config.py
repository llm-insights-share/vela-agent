"""Load knowledge-base contextual retrieval settings from vela.yaml."""

import os
from dataclasses import dataclass
from typing import Optional

import yaml

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
CONFIG_PATH = os.path.join(_BACKEND_DIR, "vela.yaml")


@dataclass
class ContextualRetrievalConfig:
    enabled: bool = False
    model_service_id: str = ""
    max_concurrency: int = 12
    chunk_timeout_seconds: int = 30
    prefix_max_tokens: int = 128
    temperature: float = 0.0
    min_chunk_length: int = 50
    document_excerpt_max_chars: int = 2000


def _load_yaml() -> dict:
    if not os.path.isfile(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_contextual_retrieval_config() -> ContextualRetrievalConfig:
    raw = ((_load_yaml().get("knowledge") or {}).get("contextual_retrieval") or {})
    return ContextualRetrievalConfig(
        enabled=bool(raw.get("enabled", False)),
        model_service_id=str(raw.get("model_service_id") or ""),
        max_concurrency=max(1, int(raw.get("max_concurrency", 12))),
        chunk_timeout_seconds=max(5, int(raw.get("chunk_timeout_seconds", 30))),
        prefix_max_tokens=max(32, int(raw.get("prefix_max_tokens", 128))),
        temperature=float(raw.get("temperature", 0.0)),
        min_chunk_length=max(1, int(raw.get("min_chunk_length", 50))),
        document_excerpt_max_chars=max(200, int(raw.get("document_excerpt_max_chars", 2000))),
    )


def save_contextual_retrieval_config(cfg: ContextualRetrievalConfig) -> None:
    config = _load_yaml()
    knowledge = dict(config.get("knowledge") or {})
    knowledge["contextual_retrieval"] = {
        "enabled": cfg.enabled,
        "model_service_id": cfg.model_service_id,
        "max_concurrency": cfg.max_concurrency,
        "chunk_timeout_seconds": cfg.chunk_timeout_seconds,
        "prefix_max_tokens": cfg.prefix_max_tokens,
        "temperature": cfg.temperature,
        "min_chunk_length": cfg.min_chunk_length,
        "document_excerpt_max_chars": cfg.document_excerpt_max_chars,
    }
    config["knowledge"] = knowledge
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)


def is_contextual_retrieval_enabled_for_kb(
    kb_override: Optional[bool],
    global_cfg: Optional[ContextualRetrievalConfig] = None,
) -> bool:
    """Resolve effective contextual retrieval flag for a knowledge base."""
    if kb_override is not None:
        return bool(kb_override)
    cfg = global_cfg or load_contextual_retrieval_config()
    return bool(cfg.enabled)
