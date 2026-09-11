"""SelfOpt feature flags from vela.yaml. Default: disabled (zero impact)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_PATH = os.path.join(_BACKEND_DIR, "vela.yaml")


@dataclass
class SelfOptConfig:
    enabled: bool = False
    schedule_enabled: bool = False
    ab_enabled: bool = True
    # Empty = follow target Agent's model_service_id
    reflect_model_service_id: str = ""
    # Allowlist; empty = no agents (must opt-in explicitly)
    agent_ids: List[str] = field(default_factory=list)


def _load_yaml() -> Dict[str, Any]:
    if not os.path.isfile(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _save_yaml(config: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)


def _normalize_agent_ids(raw: Any) -> List[str]:
    if not isinstance(raw, list):
        return []
    out: List[str] = []
    seen = set()
    for item in raw:
        aid = str(item or "").strip()
        if not aid or aid in seen:
            continue
        seen.add(aid)
        out.append(aid)
    return out


def load_selfopt_config() -> SelfOptConfig:
    raw = (_load_yaml().get("selfopt") or {})
    return SelfOptConfig(
        enabled=bool(raw.get("enabled", False)),
        schedule_enabled=bool(raw.get("schedule_enabled", False)),
        ab_enabled=bool(raw.get("ab_enabled", True)),
        reflect_model_service_id=str(raw.get("reflect_model_service_id") or "").strip(),
        agent_ids=_normalize_agent_ids(raw.get("agent_ids")),
    )


def save_selfopt_config(cfg: SelfOptConfig) -> SelfOptConfig:
    config = _load_yaml()
    config["selfopt"] = {
        "enabled": bool(cfg.enabled),
        "schedule_enabled": bool(cfg.schedule_enabled),
        "ab_enabled": bool(cfg.ab_enabled),
        "reflect_model_service_id": str(cfg.reflect_model_service_id or "").strip(),
        "agent_ids": _normalize_agent_ids(cfg.agent_ids),
    }
    _save_yaml(config)
    return load_selfopt_config()


def is_globally_enabled(cfg: Optional[SelfOptConfig] = None) -> bool:
    c = cfg or load_selfopt_config()
    return bool(c.enabled)


def is_ab_enabled(cfg: Optional[SelfOptConfig] = None) -> bool:
    c = cfg or load_selfopt_config()
    return bool(c.enabled and c.ab_enabled)


def is_schedule_enabled(cfg: Optional[SelfOptConfig] = None) -> bool:
    c = cfg or load_selfopt_config()
    return bool(c.enabled and c.schedule_enabled)


def is_enabled_for_agent(agent, cfg: Optional[SelfOptConfig] = None) -> bool:
    """Global on + allowlist + per-agent veto (selfopt_enabled=False)."""
    c = cfg or load_selfopt_config()
    if not c.enabled:
        return False
    agent_id = getattr(agent, "agent_id", None) or str(agent or "")
    if not agent_id or agent_id not in (c.agent_ids or []):
        return False
    flag = getattr(agent, "selfopt_enabled", None)
    if flag is False:
        return False
    return True


def resolve_reflect_model_service_id(
    agent,
    override: Optional[str] = None,
    cfg: Optional[SelfOptConfig] = None,
) -> str:
    """Job override > global config > agent.model_service_id."""
    if override and str(override).strip():
        return str(override).strip()
    c = cfg or load_selfopt_config()
    if c.reflect_model_service_id:
        return c.reflect_model_service_id
    return str(getattr(agent, "model_service_id", "") or "").strip()
