"""ScreenPilot MCP 工具注册 / 注销（cu_*）。"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Tuple

from sqlalchemy.orm import Session

from models import AgentToolBinding, Tool, ToolStatus, ToolType, gen_uuid, now_utc
from services.screenpilot.config import CU_TOOL_NAMES, LEGACY_UI_TOOL_NAMES
from services.screenpilot.mcp_server import TOOLS as SP_TOOLS

DISPLAY_NAMES = {
    "cu_navigate": "驭屏·导航",
    "cu_observe": "驭屏·观测",
    "cu_act": "驭屏·动作",
    "cu_extract": "驭屏·提取",
    "cu_replay_skill": "驭屏·技能重放",
    "cu_compile_skill": "驭屏·技能编译",
    "cu_search_skills": "驭屏·技能搜索",
    "cu_run_task": "驭屏·任务执行",
    "cu_wait_for_otp": "驭屏·等待验证码",
    "cu_vision": "驭屏·视觉问答",
}


def mcp_runtime_config() -> dict:
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return {
        "adapter": "screenpilot",
        "mcp_pool": True,
        "mcp_command": sys.executable,
        "mcp_args": ["-m", "services.screenpilot.mcp_server"],
        "mcp_env": {"SCREENPILOT_ENABLED": "true", "PYTHONPATH": backend_dir},
        "description": "驭屏引擎 ScreenPilot — adapter=screenpilot 进程内直调",
    }


def _delete_tools_by_names(db: Session, names: Tuple[str, ...]) -> List[str]:
    removed: List[str] = []
    if not names:
        return removed
    rows = db.query(Tool).filter(Tool.name.in_(list(names))).all()
    for row in rows:
        db.query(AgentToolBinding).filter(AgentToolBinding.tool_id == row.tool_id).delete(
            synchronize_session=False
        )
        removed.append(row.name)
        db.delete(row)
    return removed


def register_cu_mcp_tools(db: Session) -> Dict[str, Any]:
    """创建或刷新 cu_* MCP 工具；顺带清理历史 ui_*。"""
    legacy_removed = _delete_tools_by_names(db, LEGACY_UI_TOOL_NAMES)
    runtime = mcp_runtime_config()
    created, updated = [], []
    tools_out: List[dict] = []

    for spec in SP_TOOLS:
        name = spec["name"]
        if name not in CU_TOOL_NAMES:
            continue
        display = DISPLAY_NAMES.get(name, name)
        description = spec.get("description") or f"ScreenPilot MCP: {name}"
        params_schema = spec.get("inputSchema") or {"type": "object", "properties": {}}
        config = {**runtime, "mcp_tool_name": name}

        existing = db.query(Tool).filter(Tool.name == name).first()
        if existing:
            existing.display_name = display
            existing.description = description
            existing.tool_type = ToolType.MCP
            existing.config = config
            existing.parameters_schema = params_schema
            existing.status = ToolStatus.ACTIVE
            existing.updated_at = now_utc()
            updated.append(name)
            tools_out.append(
                {
                    "tool_id": existing.tool_id,
                    "name": existing.name,
                    "display_name": existing.display_name,
                    "status": "updated",
                }
            )
        else:
            tool = Tool(
                tool_id=gen_uuid(),
                name=name,
                display_name=display,
                description=description,
                tool_type=ToolType.MCP,
                config=config,
                parameters_schema=params_schema,
                status=ToolStatus.ACTIVE,
                created_at=now_utc(),
                updated_at=now_utc(),
            )
            db.add(tool)
            db.flush()
            created.append(name)
            tools_out.append(
                {
                    "tool_id": tool.tool_id,
                    "name": tool.name,
                    "display_name": tool.display_name,
                    "status": "created",
                }
            )

    db.commit()
    return {
        "created": created,
        "updated": updated,
        "removed_legacy": legacy_removed,
        "tools": tools_out,
        "binding_sync": sync_cu_tool_bindings_for_existing_agents(db),
    }


def unregister_cu_mcp_tools(db: Session) -> Dict[str, Any]:
    """删除 cu_* 及历史 ui_* ScreenPilot MCP 工具，并解除 Agent 绑定。"""
    removed = _delete_tools_by_names(db, CU_TOOL_NAMES + LEGACY_UI_TOOL_NAMES)
    # 兜底：adapter=screenpilot 的残留工具
    extras = (
        db.query(Tool)
        .filter(Tool.tool_type == ToolType.MCP)
        .all()
    )
    for row in extras:
        cfg = row.config or {}
        if cfg.get("adapter") == "screenpilot" and row.name not in removed:
            db.query(AgentToolBinding).filter(AgentToolBinding.tool_id == row.tool_id).delete(
                synchronize_session=False
            )
            removed.append(row.name)
            db.delete(row)
    db.commit()
    return {"removed": removed}


def list_registered_cu_tools(db: Session) -> List[dict]:
    rows = (
        db.query(Tool)
        .filter(Tool.name.in_(list(CU_TOOL_NAMES)))
        .order_by(Tool.name.asc())
        .all()
    )
    return [
        {
            "tool_id": r.tool_id,
            "name": r.name,
            "display_name": r.display_name,
            "status": r.status.value if hasattr(r.status, "value") else str(r.status),
        }
        for r in rows
    ]


def sync_cu_tool_bindings_for_existing_agents(db: Session) -> Dict[str, Any]:
    """Agents that already bind any cu_* tool get newly registered cu_* tools auto-bound."""
    cu_tools = (
        db.query(Tool)
        .filter(Tool.name.in_(list(CU_TOOL_NAMES)), Tool.status == ToolStatus.ACTIVE)
        .all()
    )
    by_name = {t.name: t for t in cu_tools}
    if not by_name:
        return {"agents": [], "bound": []}

    # Find agents that already have ≥1 cu_* binding
    existing = (
        db.query(AgentToolBinding, Tool)
        .join(Tool, Tool.tool_id == AgentToolBinding.tool_id)
        .filter(Tool.name.in_(list(CU_TOOL_NAMES)))
        .all()
    )
    agent_ids = {b.agent_id for b, _t in existing}
    bound: List[str] = []
    for agent_id in agent_ids:
        have = {
            t.name
            for b, t in existing
            if b.agent_id == agent_id
        }
        for name, tool in by_name.items():
            if name in have:
                continue
            db.add(
                AgentToolBinding(
                    agent_id=agent_id,
                    tool_id=tool.tool_id,
                    permission="allowed",
                    require_approval=False,
                )
            )
            bound.append(f"{agent_id}:{name}")
            have.add(name)
    if bound:
        db.commit()
    return {"agents": list(agent_ids), "bound": bound}


def ensure_cu_tools_registered_and_bound(db: Session) -> Dict[str, Any]:
    """Idempotent: refresh cu_* tool defs/schemas and bind them onto existing ScreenPilot agents."""
    before = {t["name"] for t in list_registered_cu_tools(db)}
    missing = [n for n in CU_TOOL_NAMES if n not in before]
    # Always re-register so description / parameters_schema stay in sync with mcp_server.TOOLS.
    reg = register_cu_mcp_tools(db)
    sync = sync_cu_tool_bindings_for_existing_agents(db)
    after = {t["name"] for t in list_registered_cu_tools(db)}
    return {"missing_before": missing, "register": reg, "sync": sync, "tools": sorted(after)}

