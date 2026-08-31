"""Tool Search / deferred tool loading configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

import yaml

from services.builtin_tools import get_active_web_search_tool_name

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "vela.yaml")

DEFAULT_ALWAYS_LOADED = (
    "tool_search",
    "web_extract",
    "execute_code",
)


@dataclass
class ToolSearchConfig:
    enabled: bool = False
    mode: str = "eager"  # eager | deferred
    search_backend: str = "bm25"  # bm25 | keyword
    max_results: int = 5
    max_loaded_per_session: int = 12
    always_loaded: List[str] = field(default_factory=list)

    def is_deferred(self) -> bool:
        return self.enabled and self.mode == "deferred"


def _normalize_always_loaded(names: List[str]) -> List[str]:
    out: List[str] = []
    seen: Set[str] = set()
    active_web = get_active_web_search_tool_name()
    for raw in names:
        name = str(raw or "").strip()
        if not name or name in seen:
            continue
        if name in ("tavily_web_search", "duckduckgo_web_search"):
            name = active_web
        seen.add(name)
        out.append(name)
    if active_web not in seen:
        # Ensure one web search tool in core when defaults used
        pass
    return out


def load_tool_search_config() -> ToolSearchConfig:
    if not os.path.isfile(CONFIG_PATH):
        return ToolSearchConfig()
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:
        return ToolSearchConfig()

    ts = (cfg.get("tools") or {}).get("tool_search") or {}
    active_web = get_active_web_search_tool_name()
    default_core = list(DEFAULT_ALWAYS_LOADED)
    if active_web not in default_core:
        default_core.insert(1, active_web)

    always = ts.get("always_loaded")
    if not isinstance(always, list) or not always:
        always = default_core
    else:
        always = _normalize_always_loaded(always)

    mode = str(ts.get("mode") or "eager").strip().lower()
    if mode not in ("eager", "deferred"):
        mode = "eager"

    backend = str(ts.get("search_backend") or "bm25").strip().lower()
    if backend not in ("bm25", "keyword"):
        backend = "bm25"

    return ToolSearchConfig(
        enabled=bool(ts.get("enabled", False)),
        mode=mode,
        search_backend=backend,
        max_results=max(1, min(int(ts.get("max_results", 5) or 5), 20)),
        max_loaded_per_session=max(1, min(int(ts.get("max_loaded_per_session", 12) or 12), 50)),
        always_loaded=always,
    )


def resolve_tool_loading_for_agent(agent: Any, base: Optional[ToolSearchConfig] = None) -> ToolSearchConfig:
    """Merge system config with agent.composition_config.tool_loading overrides."""
    cfg = base or load_tool_search_config()
    comp = getattr(agent, "composition_config", None) or {}
    tl = comp.get("tool_loading") if isinstance(comp, dict) else None
    if not isinstance(tl, dict):
        return cfg

    mode = tl.get("mode")
    if mode is not None:
        mode_s = str(mode).strip().lower()
        if mode_s in ("eager", "deferred"):
            cfg.mode = mode_s

    if tl.get("enabled") is not None:
        cfg.enabled = bool(tl.get("enabled"))

    always = tl.get("always_loaded")
    if isinstance(always, list) and always:
        cfg.always_loaded = _normalize_always_loaded(always)

    if tl.get("search_backend") is not None:
        b = str(tl.get("search_backend")).strip().lower()
        if b in ("bm25", "keyword"):
            cfg.search_backend = b

    return cfg


def resolve_core_tool_names(
    cfg: ToolSearchConfig,
    *,
    memory_enabled: bool = False,
    has_kb: bool = False,
    available_tool_names: Optional[Set[str]] = None,
) -> Set[str]:
    """Core tools always exposed to LLM in deferred mode."""
    names = set(_normalize_always_loaded(list(cfg.always_loaded)))
    if "tool_search" not in names and cfg.enabled:
        names.add("tool_search")

    avail = available_tool_names or set()
    if memory_enabled and "memory" in avail:
        names.add("memory")
    if has_kb and "kb_search" in avail:
        names.add("kb_search")
    if "cu_search_skills" in avail:
        names.add("cu_search_skills")
    if "ui_search_skills" in avail:
        names.add("ui_search_skills")
    return names
