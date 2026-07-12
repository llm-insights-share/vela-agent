"""UI 技能商店 — 跨 scope 发布与复用。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from models import UiSkill, UiSkillStep, gen_uuid, now_utc
from services.screenpilot.skill_store import skill_store


def list_shop_skills(
    db: Session,
    *,
    scope: Optional[str] = None,
    visibility: Optional[str] = None,
    query: Optional[str] = None,
    top_k: int = 20,
) -> List[Dict[str, Any]]:
    """列出已发布技能（DEPARTMENT / PUBLIC）。"""
    q = db.query(UiSkill).filter(
        UiSkill.status == "ACTIVE",
        UiSkill.visibility.in_(["DEPARTMENT", "PUBLIC"]),
    )
    if scope:
        q = q.filter(UiSkill.scope == scope)
    if visibility:
        q = q.filter(UiSkill.visibility == visibility)

    skills = q.order_by(UiSkill.published_at.desc()).limit(top_k * 2).all()

    if query and query.strip():
        scored = skill_store.search_cross_scopes(db, query, top_k=top_k)
        id_set = {s["skill_id"] for s in scored}
        skills = [s for s in skills if s.skill_id in id_set]
        score_map = {s["skill_id"]: s["score"] for s in scored}
    else:
        score_map = {}

    out = []
    for s in skills[:top_k]:
        step_count = db.query(UiSkillStep).filter(UiSkillStep.skill_id == s.skill_id).count()
        out.append({
            "skill_id": s.skill_id,
            "name": s.name,
            "description": s.description,
            "system_id": s.system_id,
            "scope": s.scope,
            "visibility": s.visibility,
            "publisher_id": s.publisher_id,
            "step_count": step_count,
            "score": score_map.get(s.skill_id),
            "published_at": s.published_at.isoformat() if s.published_at else None,
        })
    return out


def publish_skill(
    db: Session,
    skill_id: str,
    *,
    visibility: str = "DEPARTMENT",
    publisher_id: str = "",
) -> Optional[UiSkill]:
    if visibility not in ("DEPARTMENT", "PUBLIC"):
        visibility = "DEPARTMENT"

    skill = skill_store.get_skill(db, skill_id)
    if not skill:
        return None

    skill.visibility = visibility
    skill.publisher_id = publisher_id or skill.publisher_id or "system"
    skill.published_at = now_utc()
    skill.updated_at = now_utc()
    db.commit()
    db.refresh(skill)

    skill_store.index_skill(skill.skill_id, f"{skill.name}\n{skill.description}", skill.scope)
    return skill


def unpublish_skill(db: Session, skill_id: str) -> Optional[UiSkill]:
    skill = skill_store.get_skill(db, skill_id)
    if not skill:
        return None
    skill.visibility = "PRIVATE"
    skill.updated_at = now_utc()
    db.commit()
    db.refresh(skill)
    return skill


def import_skill_to_scope(
    db: Session,
    skill_id: str,
    target_scope: str,
    *,
    new_name: Optional[str] = None,
) -> Optional[UiSkill]:
    """将商店技能复制到本地 scope 以便复用。"""
    source = skill_store.get_skill(db, skill_id)
    if not source:
        return None
    if source.visibility == "PRIVATE" and source.scope != target_scope:
        return None

    steps = skill_store.get_steps(db, skill_id)
    step_dicts = [
        {
            "system_id": st.system_id,
            "action": st.action,
            "target_label": st.target_label,
            "value_template": st.value_template,
            "fingerprints": st.fingerprints or {},
            "meta": st.meta or {},
        }
        for st in steps
    ]

    return skill_store.create_skill(
        db,
        name=new_name or f"{source.name} (imported)",
        description=source.description,
        system_id=source.system_id,
        steps=step_dicts,
        scope=target_scope,
        param_schema=source.param_schema or {},
        source_session_id=source.source_session_id or "",
    )
