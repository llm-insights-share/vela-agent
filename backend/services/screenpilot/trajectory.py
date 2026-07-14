"""轨迹录制与技能编译。"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from models import ScreenSession
from services.screenpilot.layers.ground import build_selector_fingerprint
from services.screenpilot.skill_store import skill_store


PARAM_PATTERN = re.compile(r"\{\{(\w+)\}\}")


def append_trajectory_step(
    db: Session,
    screen_session_id: str,
    step: Dict[str, Any],
) -> None:
    row = (
        db.query(ScreenSession)
        .filter(ScreenSession.screen_session_id == screen_session_id)
        .first()
    )
    if not row:
        return
    meta = dict(row.meta or {})
    trajectory: List[Dict[str, Any]] = list(meta.get("trajectory") or [])
    step["step_order"] = len(trajectory) + 1
    trajectory.append(step)
    meta["trajectory"] = trajectory
    row.meta = meta
    row.updated_at = step.get("recorded_at") or row.updated_at
    db.commit()


def get_trajectory(db: Session, screen_session_id: str) -> List[Dict[str, Any]]:
    row = (
        db.query(ScreenSession)
        .filter(ScreenSession.screen_session_id == screen_session_id)
        .first()
    )
    if not row:
        return []
    return list((row.meta or {}).get("trajectory") or [])


def clear_trajectory(db: Session, screen_session_id: str) -> None:
    row = (
        db.query(ScreenSession)
        .filter(ScreenSession.screen_session_id == screen_session_id)
        .first()
    )
    if not row:
        return
    meta = dict(row.meta or {})
    meta["trajectory"] = []
    row.meta = meta
    db.commit()


def infer_param_schema(steps: List[Dict[str, Any]]) -> Dict[str, Any]:
    params: Dict[str, str] = {}
    for step in steps:
        val = step.get("value") or step.get("value_template") or ""
        if not isinstance(val, str):
            continue
        for m in PARAM_PATTERN.finditer(val):
            params[m.group(1)] = "string"
    return {"type": "object", "properties": {k: {"type": v} for k, v in params.items()}}


def compile_trajectory_to_skill(
    db: Session,
    *,
    screen_session_id: str,
    name: str,
    description: str,
    scope: str = "default",
    parametrize_values: bool = False,
) -> Dict[str, Any]:
    row = (
        db.query(ScreenSession)
        .filter(ScreenSession.screen_session_id == screen_session_id)
        .first()
    )
    if not row:
        return {"success": False, "error": "会话不存在"}

    trajectory = get_trajectory(db, screen_session_id)
    if not trajectory:
        return {"success": False, "error": "轨迹为空，请先通过 cu_act 执行若干步骤"}

    compiled_steps = []
    for item in trajectory:
        value = item.get("value") or ""
        compiled_steps.append(
            {
                "system_id": row.system_id,
                "action": item.get("action"),
                "target_label": item.get("target_label") or "",
                "value_template": value if not parametrize_values else value,
                "fingerprints": item.get("fingerprints") or build_selector_fingerprint(
                    item.get("target") or {"label": item.get("target_label", ""), "role": item.get("role", "")}
                ),
                "meta": {"url": item.get("url", ""), "target_ref": item.get("target_ref")},
            }
        )

    param_schema = infer_param_schema(compiled_steps)
    skill = skill_store.create_skill(
        db,
        name=name,
        description=description or name,
        system_id=row.system_id,
        steps=compiled_steps,
        scope=scope,
        param_schema=param_schema,
        source_session_id=screen_session_id,
    )
    return {
        "success": True,
        "skill_id": skill.skill_id,
        "name": skill.name,
        "step_count": len(compiled_steps),
        "param_schema": param_schema,
    }


def resolve_template(value_template: str, params: Dict[str, Any]) -> str:
    if not value_template:
        return ""

    def repl(m):
        key = m.group(1)
        return str(params.get(key, m.group(0)))

    return PARAM_PATTERN.sub(repl, value_template)
