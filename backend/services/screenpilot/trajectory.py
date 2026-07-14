"""轨迹录制与技能编译。"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from models import ScreenSession, UiSkill
from services.screenpilot.layers.ground import build_selector_fingerprint
from services.screenpilot.skill_store import skill_store


PARAM_PATTERN = re.compile(r"\{\{(\w+)\}\}")

# 编译去重：业务步骤序列相似度 / 名称语义相似度
_STEP_DUP_THRESHOLD = 0.75
_SEMANTIC_DUP_THRESHOLD = 0.88
_MIN_BUSINESS_STEPS = 1


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


def sanitize_trajectory_value(item: Dict[str, Any]) -> str:
    """Avoid persisting raw credentials into ui_skill_steps."""
    value = item.get("value") or ""
    if item.get("action") != "type":
        return value if isinstance(value, str) else str(value or "")
    tgt = item.get("target") or {}
    label = (item.get("target_label") or "") + " " + str(tgt.get("label") or "")
    low = label.lower()
    field_kind = (tgt.get("field_kind") or item.get("field_kind") or "").lower()
    input_type = (tgt.get("input_type") or item.get("input_type") or "").lower()
    if (
        field_kind == "password"
        or input_type == "password"
        or "密码" in label
        or "password" in low
    ):
        return "{{password}}"
    if (
        field_kind == "username"
        or any(k in label for k in ("用户", "账号", "帐号"))
        or "user" in low
        or "account" in low
    ):
        return "{{username}}"
    return value if isinstance(value, str) else str(value or "")


_NOISE_LABELS = frozenset({
    "登录", "用户登录", "login", "sign in", "log in",
    "english", "chinese", "简", "繁", "en", "中", "中 en",
})
_NOISE_SUBSTR = ("密码", "用户名", "请输入", "password", "username", "ai\\", "转向其他")


def redact_skill_hint(text: str) -> str:
    """Strip credentials and verbose prefixes from user messages used in naming."""
    s = (text or "").strip().replace("\n", " ")
    if not s:
        return ""
    s = re.sub(r"密码\s*[:：]\s*\S+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"password\s*[=:：]\s*\S+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"system_id\s*[=:：]\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"使用\S{0,32}用户登录", "登录", s)
    s = re.sub(r"[；;]{2,}", "；", s)
    s = re.sub(r"\s+", " ", s).strip(" ；;，,")
    return s[:80]


def _is_noise_label(label: str) -> bool:
    t = (label or "").strip()
    if not t or len(t) > 24:
        return True
    low = t.lower()
    if low in _NOISE_LABELS or t in _NOISE_LABELS:
        return True
    return any(n in t or n in low for n in _NOISE_SUBSTR)


def business_step_signature(steps: List[Dict[str, Any]]) -> List[str]:
    """Strip login/noise steps; keep action+label tokens that represent the business flow."""
    sig: List[str] = []
    for step in steps or []:
        action = (step.get("action") or "").strip().lower()
        label = (step.get("target_label") or "").strip()
        if not action:
            continue
        if action == "type" and _is_noise_label(label):
            continue
        if label and _is_noise_label(label):
            continue
        if action in ("type", "fill") and not label:
            sig.append(f"{action}:*")
            continue
        if not label:
            continue
        sig.append(f"{action}:{label.lower()}")
    return sig


def _signature_similarity(a: List[str], b: List[str]) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _is_subsequence(needle: List[str], haystack: List[str]) -> bool:
    if not needle:
        return False
    it = iter(haystack)
    return all(token in it for token in needle)


def find_duplicate_skill(
    db: Session,
    *,
    system_id: str,
    name: str,
    description: str,
    steps: List[Dict[str, Any]],
    scope: str = "default",
) -> Optional[Dict[str, Any]]:
    """Return an existing ACTIVE skill that is near-duplicate of the candidate, or None."""
    scope = scope or "default"
    new_sig = business_step_signature(steps)
    candidates = (
        db.query(UiSkill)
        .filter(
            UiSkill.system_id == system_id,
            UiSkill.status == "ACTIVE",
            UiSkill.scope == scope,
        )
        .all()
    )

    best: Optional[UiSkill] = None
    best_score = 0.0
    best_reason = ""

    for skill in candidates:
        raw_steps = skill_store.get_steps(db, skill.skill_id)
        old_dicts = [
            {"action": s.action, "target_label": s.target_label or ""}
            for s in raw_steps
        ]
        old_sig = business_step_signature(old_dicts)
        step_sim = _signature_similarity(new_sig, old_sig)
        subsumed = (
            _is_subsequence(new_sig, old_sig) or _is_subsequence(old_sig, new_sig)
        )
        score = step_sim
        reason = "step"
        if subsumed and new_sig and old_sig:
            score = max(score, 0.9)
            reason = "step_subsequence"
        if score > best_score:
            best_score = score
            best = skill
            best_reason = reason

    if best and best_score >= _STEP_DUP_THRESHOLD:
        return {
            "skill": best,
            "reason": best_reason,
            "score": best_score,
            "new_sig": new_sig,
        }

    # Semantic fallback on name+description (same system only).
    try:
        matches = skill_store.search(
            f"{name}\n{description or name}", scope=scope, top_k=5, db=db
        )
    except Exception:
        matches = []
    for skill_id, score in matches:
        if score < _SEMANTIC_DUP_THRESHOLD:
            continue
        skill = skill_store.get_skill(db, skill_id)
        if not skill or skill.status != "ACTIVE" or skill.system_id != system_id:
            continue
        old_dicts = [
            {"action": s.action, "target_label": s.target_label or ""}
            for s in skill_store.get_steps(db, skill.skill_id)
        ]
        old_sig = business_step_signature(old_dicts)
        step_sim = _signature_similarity(new_sig, old_sig)
        # High semantic alone is enough when both have little business signal;
        # otherwise require mild step overlap to avoid false merges.
        if score >= 0.95 or step_sim >= 0.4 or (
            len(new_sig) <= 1 and len(old_sig) <= 1
        ):
            return {
                "skill": skill,
                "reason": "semantic",
                "score": float(score),
                "new_sig": new_sig,
                "step_sim": step_sim,
            }
    return None


def summarize_skill_name(
    system_name: str,
    trajectory: List[Dict[str, Any]],
    user_hint: str = "",
) -> tuple:
    """Deterministic short skill name + description (no secrets)."""
    sys_name = (system_name or "目标系统").strip() or "目标系统"
    if sys_name.endswith("系统"):
        title_sys = sys_name
    else:
        title_sys = f"{sys_name}系统"

    meaningful: List[str] = []
    for step in trajectory or []:
        label = (step.get("target_label") or "").strip()
        action = (step.get("action") or "").lower()
        if action in ("type",) and _is_noise_label(label):
            continue
        if _is_noise_label(label):
            continue
        if label and label not in meaningful:
            meaningful.append(label[:12])
        if len(meaningful) >= 3:
            break

    verb = "操作"
    hint = redact_skill_hint(user_hint)
    hint_low = hint.lower()
    if any(k in hint for k in ("查询", "搜索", "查找")) or "search" in hint_low:
        verb = "查询"
    elif any(k in hint for k in ("提交", "创建", "新建", "办理")):
        verb = "办理"
    elif any(k in hint for k in ("打开", "进入", "访问")):
        verb = "打开"
    elif meaningful:
        verb = "操作"

    # Prefer a single primary object (e.g. 通讯录) for short readable titles.
    obj = meaningful[0] if meaningful else "常用操作"
    name = f"{title_sys}{verb}{obj}"
    if len(name) > 32:
        name = name[:32]

    step_bits = []
    for step in (trajectory or [])[:8]:
        lab = (step.get("target_label") or step.get("action") or "").strip()
        if lab and not _is_noise_label(lab):
            step_bits.append(lab[:16])
    desc = f"{title_sys}自动编译技能"
    if step_bits:
        desc += "；步骤: " + " → ".join(step_bits[:5])
    return name, desc[:200]


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
        value = sanitize_trajectory_value(item)
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

    biz_sig = business_step_signature(compiled_steps)
    if len(biz_sig) < _MIN_BUSINESS_STEPS:
        return {
            "success": False,
            "error": "有效业务步骤不足（多为登录噪声），跳过生成技能",
            "skipped": True,
            "reason": "insufficient_business_steps",
        }

    dup = find_duplicate_skill(
        db,
        system_id=row.system_id or "",
        name=name,
        description=description or name,
        steps=compiled_steps,
        scope=scope,
    )
    if dup and dup.get("skill"):
        existing = dup["skill"]
        existing_steps = skill_store.get_steps(db, existing.skill_id)
        return {
            "success": True,
            "skill_id": existing.skill_id,
            "name": existing.name,
            "step_count": len(existing_steps),
            "param_schema": existing.param_schema or {},
            "deduplicated": True,
            "duplicate_reason": dup.get("reason"),
            "duplicate_score": dup.get("score"),
            "message": f"已存在相似技能「{existing.name}」，复用未新建",
        }

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
        "deduplicated": False,
    }


def auto_compile_pending_trajectories(
    db: Session,
    *,
    vela_session_id: str,
    name_hint: str = "",
    min_steps: int = 2,
    screen_session_ids: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """After a successful agent run: compile unconverted ScreenPilot trajectories into UI skills."""
    from models import UiSkill

    by_id: Dict[str, ScreenSession] = {}
    if screen_session_ids:
        for row in (
            db.query(ScreenSession)
            .filter(ScreenSession.screen_session_id.in_(list(screen_session_ids)))
            .all()
        ):
            by_id[row.screen_session_id] = row
    if (vela_session_id or "").strip():
        for row in (
            db.query(ScreenSession)
            .filter(ScreenSession.vela_session_id == vela_session_id)
            .order_by(ScreenSession.created_at.desc())
            .all()
        ):
            by_id[row.screen_session_id] = row


    if not by_id:
        return []

    results: List[Dict[str, Any]] = []
    from models import ScreenSystem

    for row in by_id.values():
        meta = dict(row.meta or {})
        if meta.get("compiled_skill_id"):
            continue
        trajectory = list(meta.get("trajectory") or [])
        if len(trajectory) < min_steps:
            continue
        existing = (
            db.query(UiSkill)
            .filter(
                UiSkill.source_session_id == row.screen_session_id,
                UiSkill.status == "ACTIVE",
            )
            .first()
        )
        if existing:
            meta["compiled_skill_id"] = existing.skill_id
            row.meta = meta
            db.commit()
            continue

        sys = db.query(ScreenSystem).filter(ScreenSystem.system_id == row.system_id).first()
        sys_name = (sys.name if sys else "") or "目标"
        name, description = summarize_skill_name(sys_name, trajectory, name_hint)
        compiled = compile_trajectory_to_skill(
            db,
            screen_session_id=row.screen_session_id,
            name=name,
            description=description,
            scope="default",
        )
        if compiled.get("skipped"):
            meta["compiled_skipped"] = compiled.get("reason") or "skipped"
            row.meta = meta
            db.commit()
            continue
        if compiled.get("success") and compiled.get("skill_id"):
            meta["compiled_skill_id"] = compiled["skill_id"]
            row.meta = meta
            db.commit()
            results.append(compiled)
    return results



def resolve_template(value_template: str, params: Dict[str, Any]) -> str:
    if not value_template:
        return ""

    def repl(m):
        key = m.group(1)
        return str(params.get(key, m.group(0)))

    return PARAM_PATTERN.sub(repl, value_template)
