"""Agent × mode context-block overrides: merge, materialize, restore, preview."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from models import Agent, AgentContextBlock, gen_uuid, now_utc
from services.context_block_defaults import (
    BUILTIN_BLOCK_KEYS,
    get_system_default_specs,
    validate_execution_mode,
)


def _row_to_dict(row: AgentContextBlock) -> Dict[str, Any]:
    return {
        "block_id": row.block_id,
        "agent_id": row.agent_id,
        "execution_mode": row.execution_mode,
        "block_key": row.block_key,
        "title": row.title or "",
        "placement": row.placement or "system",
        "source": row.source or "static",
        "content": row.content or "",
        "enabled": bool(row.enabled),
        "sort_order": int(row.sort_order or 0),
        "deletable": bool(row.deletable),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _spec_to_dict(spec: Dict[str, Any], agent_id: str = "", mode: str = "") -> Dict[str, Any]:
    return {
        "block_id": spec.get("block_id") or "",
        "agent_id": agent_id,
        "execution_mode": mode,
        "block_key": spec["block_key"],
        "title": spec.get("title") or "",
        "placement": spec.get("placement") or "system",
        "source": spec.get("source") or "static",
        "content": spec.get("content") or "",
        "enabled": bool(spec.get("enabled", True)),
        "sort_order": int(spec.get("sort_order") or 0),
        "deletable": bool(spec.get("deletable", False)),
        "created_at": None,
        "updated_at": None,
    }


def list_system_defaults(execution_mode: str, system_prompt: str = "") -> List[Dict[str, Any]]:
    mode = validate_execution_mode(execution_mode)
    return [
        _spec_to_dict(s, mode=mode)
        for s in get_system_default_specs(mode, system_prompt=system_prompt)
    ]


def _query_overrides(db: Session, agent_id: str, mode: str) -> List[AgentContextBlock]:
    return (
        db.query(AgentContextBlock)
        .filter(
            AgentContextBlock.agent_id == agent_id,
            AgentContextBlock.execution_mode == mode,
        )
        .order_by(AgentContextBlock.sort_order.asc(), AgentContextBlock.block_key.asc())
        .all()
    )


def merge_effective(
    defaults: List[Dict[str, Any]],
    overrides: List[Any],
    agent_id: str = "",
    mode: str = "",
) -> List[Dict[str, Any]]:
    """Merge system defaults with agent override rows/dicts. Overrides win by block_key."""
    by_key: Dict[str, Dict[str, Any]] = {
        d["block_key"]: dict(d) for d in defaults
    }
    customs: List[Dict[str, Any]] = []
    for o in overrides:
        if hasattr(o, "block_key"):
            d = _row_to_dict(o)
        else:
            d = dict(o)
            d.setdefault("agent_id", agent_id)
            d.setdefault("execution_mode", mode)
        key = d.get("block_key") or ""
        if key.startswith("custom_") or (
            key and key not in BUILTIN_BLOCK_KEYS and d.get("deletable")
        ):
            customs.append(d)
        elif key:
            by_key[key] = d
    merged = list(by_key.values()) + customs
    merged.sort(key=lambda x: (int(x.get("sort_order") or 0), x.get("block_key") or ""))
    return merged


def get_effective_blocks_for_runtime(
    db: Session,
    agent_id: str,
    execution_mode: str,
    system_prompt: str = "",
) -> List[Dict[str, Any]]:
    """In-memory merge for AgentLoop (does not write DB)."""
    mode = validate_execution_mode(execution_mode)
    defaults = [
        _spec_to_dict(s, agent_id=agent_id, mode=mode)
        for s in get_system_default_specs(mode, system_prompt=system_prompt)
    ]
    overrides = _query_overrides(db, agent_id, mode)
    if not overrides:
        return defaults
    return merge_effective(defaults, overrides, agent_id=agent_id, mode=mode)


def _materialize_from_specs(
    db: Session,
    agent: Agent,
    mode: str,
    specs: List[Dict[str, Any]],
) -> List[AgentContextBlock]:
    rows: List[AgentContextBlock] = []
    for s in specs:
        row = AgentContextBlock(
            block_id=gen_uuid(),
            agent_id=agent.agent_id,
            execution_mode=mode,
            block_key=s["block_key"],
            title=s.get("title") or "",
            placement=s.get("placement") or "system",
            source=s.get("source") or "static",
            content=s.get("content") or "",
            enabled=bool(s.get("enabled", True)),
            sort_order=int(s.get("sort_order") or 0),
            deletable=bool(s.get("deletable", False)),
        )
        db.add(row)
        rows.append(row)
    db.commit()
    for r in rows:
        db.refresh(r)
    return rows


def ensure_materialized(
    db: Session,
    agent: Agent,
    execution_mode: str,
) -> List[Dict[str, Any]]:
    """Lazy-materialize defaults on first GET; return effective rows as dicts."""
    mode = validate_execution_mode(execution_mode)
    existing = _query_overrides(db, agent.agent_id, mode)
    if not existing:
        specs = get_system_default_specs(mode, system_prompt=agent.system_prompt or "")
        existing = _materialize_from_specs(db, agent, mode, specs)
    return [_row_to_dict(r) for r in existing]


def restore_defaults(
    db: Session,
    agent: Agent,
    execution_mode: str,
) -> List[Dict[str, Any]]:
    mode = validate_execution_mode(execution_mode)
    db.query(AgentContextBlock).filter(
        AgentContextBlock.agent_id == agent.agent_id,
        AgentContextBlock.execution_mode == mode,
    ).delete(synchronize_session=False)
    db.commit()
    specs = get_system_default_specs(mode, system_prompt=agent.system_prompt or "")
    rows = _materialize_from_specs(db, agent, mode, specs)
    return [_row_to_dict(r) for r in rows]


def replace_blocks(
    db: Session,
    agent: Agent,
    execution_mode: str,
    items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    mode = validate_execution_mode(execution_mode)
    db.query(AgentContextBlock).filter(
        AgentContextBlock.agent_id == agent.agent_id,
        AgentContextBlock.execution_mode == mode,
    ).delete(synchronize_session=False)
    db.flush()

    system_base_content: Optional[str] = None
    rows: List[AgentContextBlock] = []
    for i, raw in enumerate(items):
        key = (raw.get("block_key") or "").strip()
        if not key:
            key = f"custom_{uuid.uuid4().hex[:12]}"
        deletable = bool(raw.get("deletable", key.startswith("custom_")))
        if key in BUILTIN_BLOCK_KEYS:
            deletable = False
        content = raw.get("content") if raw.get("content") is not None else ""
        if key == "system_base":
            system_base_content = str(content)
        row = AgentContextBlock(
            block_id=raw.get("block_id") or gen_uuid(),
            agent_id=agent.agent_id,
            execution_mode=mode,
            block_key=key,
            title=(raw.get("title") or "").strip() or key,
            placement=(raw.get("placement") or "system").strip() or "system",
            source=(raw.get("source") or "static").strip() or "static",
            content=str(content),
            enabled=bool(raw.get("enabled", True)),
            sort_order=int(raw.get("sort_order") if raw.get("sort_order") is not None else (i + 1) * 10),
            deletable=deletable,
            updated_at=now_utc(),
        )
        db.add(row)
        rows.append(row)

    if system_base_content is not None:
        agent.system_prompt = system_base_content
        agent.updated_at = now_utc()

    db.commit()
    for r in rows:
        db.refresh(r)
    return [_row_to_dict(r) for r in sorted(rows, key=lambda x: (x.sort_order or 0, x.block_key))]


def preview_assembled(
    blocks: List[Dict[str, Any]],
    *,
    connector_context: str = "",
    knowledge_context: str = "",
    project_context: str = "",
    systems_text: str = "(运行时填充)",
    workspace: str = "workspaces/<session_id>/",
    memory_body: str = "(运行时记忆正文)",
    skill_body: str = "(运行时 Skill 正文)",
    today: str = "YYYY-MM-DD",
    weekday: str = "X",
) -> Dict[str, Any]:
    """Build a read-only preview of system / user_suffix / mode_inject text."""
    system_parts: List[str] = []
    user_parts: List[str] = []
    mode_parts: List[str] = []

    for b in sorted(blocks, key=lambda x: (int(x.get("sort_order") or 0), x.get("block_key") or "")):
        if not b.get("enabled", True):
            continue
        key = b.get("block_key") or ""
        placement = b.get("placement") or "system"
        content = b.get("content") or ""
        text = ""
        if key == "system_base":
            text = content
        elif key == "connector":
            body = (connector_context or "").strip() or "(无连接器上下文)"
            text = content.replace("{body}", body) if "{body}" in content else f"## 连接器\n{body}"
        elif key == "cu_norms":
            text = content.replace("{systems}", systems_text)
        elif key == "code_norms":
            text = content.replace("{workspace}", workspace)
        elif key == "tool_search_norms":
            text = content
        elif key == "knowledge":
            body = (knowledge_context or "").strip() or "(无知识库上下文)"
            text = content.replace("{body}", body) if "{body}" in content else body
        elif key == "project":
            body = (project_context or "").strip() or "(无项目上下文)"
            text = content.replace("{body}", body) if "{body}" in content else body
        elif key == "date":
            text = (
                content.replace("{today}", today).replace("{weekday}", weekday)
            )
        elif key == "memory_suffix":
            text = content.replace("{body}", memory_body)
        elif key == "skill_suffix":
            text = content.replace("{body}", skill_body)
        elif key == "plan_prompt" or placement == "mode_inject":
            text = content
        else:
            # custom / unknown static
            text = content.replace("{body}", "") if "{body}" in content else content

        if not (text or "").strip():
            continue
        if placement == "user_suffix":
            user_parts.append(text.strip())
        elif placement == "mode_inject":
            mode_parts.append(text.strip())
        else:
            system_parts.append(text.strip())

    return {
        "system": "\n\n".join(system_parts),
        "user_suffix": "\n\n".join(user_parts),
        "mode_inject": "\n\n".join(mode_parts),
        "blocks": blocks,
    }


def block_enabled(blocks: List[Dict[str, Any]], block_key: str, default: bool = True) -> bool:
    for b in blocks:
        if b.get("block_key") == block_key:
            return bool(b.get("enabled", True))
    return default


def get_block(blocks: List[Dict[str, Any]], block_key: str) -> Optional[Dict[str, Any]]:
    for b in blocks:
        if b.get("block_key") == block_key:
            return b
    return None
