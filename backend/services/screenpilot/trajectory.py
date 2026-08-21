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

_CREDENTIAL_PARAM_KEYS = frozenset({
    "password", "username", "otp", "token", "secret", "passwd", "user",
})

# 编译去重：业务步骤序列相似度 / 名称语义相似度
_STEP_DUP_THRESHOLD = 0.75
_SEMANTIC_DUP_THRESHOLD = 0.88
_MIN_BUSINESS_STEPS = 1


def format_step_note(
    action: str,
    target_label: str = "",
    value: Optional[str] = None,
) -> str:
    """Generate a short Chinese step description for UI skill recording."""
    act = (action or "").strip().lower()
    label = (target_label or "").strip()
    val = "" if value is None else str(value).strip()
    quoted = f"「{label}」" if label else ""

    if act == "click":
        return f"点击{quoted}" if quoted else "点击目标元素"
    if act in ("type", "fill"):
        if quoted and val:
            return f"在{quoted}输入「{val[:40]}」"
        if quoted:
            return f"在{quoted}输入内容"
        if val:
            return f"输入「{val[:40]}」"
        return "输入文本"
    if act == "select":
        if quoted and val:
            return f"在{quoted}选择「{val[:40]}」"
        if quoted:
            return f"在{quoted}选择选项"
        return "选择选项"
    if act == "navigate":
        return f"导航至 {val}" if val else "导航到目标页面"
    if act == "press":
        return f"按下按键 {val}" if val else "按下按键"
    if act == "scroll":
        return f"滚动页面{(' ' + val) if val else ''}".strip()
    if act == "wait":
        return f"等待{(' ' + val) if val else ''}".strip() or "等待"
    if quoted:
        return f"执行 {act or '操作'}{quoted}"
    return f"执行 {act or '操作'}"


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
    if not (step.get("note") or "").strip():
        step["note"] = format_step_note(
            step.get("action") or "",
            step.get("target_label") or "",
            step.get("value"),
        )
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


def replace_trajectory(
    db: Session,
    screen_session_id: str,
    steps: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Replace the full trajectory (e.g. after deleting/editing steps in recorder UI)."""
    row = (
        db.query(ScreenSession)
        .filter(ScreenSession.screen_session_id == screen_session_id)
        .first()
    )
    if not row:
        return []
    normalized: List[Dict[str, Any]] = []
    for i, raw in enumerate(steps or []):
        step = dict(raw)
        step["step_order"] = i + 1
        if not (step.get("note") or "").strip():
            step["note"] = format_step_note(
                step.get("action") or "",
                step.get("target_label") or "",
                step.get("value"),
            )
        normalized.append(step)
    meta = dict(row.meta or {})
    meta["trajectory"] = normalized
    row.meta = meta
    db.commit()
    return normalized


def infer_param_schema(steps: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build JSON Schema for {{placeholders}}; include descriptions from labels/notes."""
    properties: Dict[str, Dict[str, Any]] = {}
    required: List[str] = []
    for step in steps:
        val = step.get("value_template") or step.get("value") or ""
        if not isinstance(val, str):
            continue
        label = (step.get("target_label") or "").strip()
        note = ""
        meta = step.get("meta")
        if isinstance(meta, dict):
            note = (meta.get("note") or "").strip()
        note = note or (step.get("note") or "").strip()
        for m in PARAM_PATTERN.finditer(val):
            key = m.group(1)
            if key in properties:
                continue
            desc = note or (f"填写「{label}」" if label else key)
            properties[key] = {"type": "string", "description": desc}
            if key.lower() not in _CREDENTIAL_PARAM_KEYS:
                required.append(key)
    schema: Dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def normalize_param_key(raw: str) -> str:
    """Sanitize a user-provided param name to \\w+ for {{placeholders}}."""
    s = re.sub(r"[^\w]", "_", (raw or "").strip())
    s = re.sub(r"_+", "_", s).strip("_")
    if not s:
        return ""
    if s[0].isdigit():
        s = "p_" + s
    return s[:64]


def suggest_param_key(label: str = "", action: str = "") -> str:
    """Heuristic default param name from field label."""
    lab = (label or "").strip()
    low = lab.lower()
    act = (action or "").strip().lower()
    if any(k in lab for k in ("搜索", "检索", "关键词", "关键字")) or any(
        k in low for k in ("search", "query", "keyword")
    ):
        return "query"
    if "部门" in lab or "dept" in low or "department" in low:
        return "dept"
    if any(k in lab for k in ("姓名", "人名")) or low in ("name", "full name"):
        return "name"
    if any(k in lab for k in ("标题", "主题")) or "title" in low or "subject" in low:
        return "title"
    if "日期" in lab or "date" in low:
        return "date"
    if act in ("type", "fill", "select") and lab:
        key = normalize_param_key(lab)
        return key or "value"
    return "value"


def sanitize_trajectory_value(item: Dict[str, Any]) -> str:
    """Avoid persisting raw credentials; honor explicit param_key as placeholder."""
    pk = normalize_param_key(str(item.get("param_key") or ""))
    if pk:
        return f"{{{{{pk}}}}}"
    existing_tpl = item.get("value_template")
    if isinstance(existing_tpl, str) and PARAM_PATTERN.search(existing_tpl):
        return existing_tpl
    value = item.get("value") or ""
    if item.get("action") not in ("type", "fill", "select"):
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
        # Empty business signatures (e.g. pure login) must not merge via name alone.
        if not new_sig:
            continue
        # High semantic alone is enough when both have little business signal;
        # otherwise require mild step overlap to avoid false merges.
        if score >= 0.95 or step_sim >= 0.4 or (
            len(new_sig) <= 1 and len(old_sig) <= 1 and step_sim >= 0.2
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
    require_business_steps: bool = True,
    force_create: bool = False,
    on_duplicate: str = "reuse",
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
        if (
            parametrize_values
            and (item.get("action") or "").lower() in ("type", "fill", "select")
            and not PARAM_PATTERN.search(value or "")
        ):
            pk = normalize_param_key(str(item.get("param_key") or "")) or suggest_param_key(
                item.get("target_label") or "",
                item.get("action") or "",
            )
            if pk and pk.lower() not in _CREDENTIAL_PARAM_KEYS:
                value = f"{{{{{pk}}}}}"
        note = (item.get("note") or "").strip() or format_step_note(
            item.get("action") or "",
            item.get("target_label") or "",
            value,
        )
        compiled_steps.append(
            {
                "system_id": row.system_id,
                "action": item.get("action"),
                "target_label": item.get("target_label") or "",
                "value_template": value,
                "fingerprints": item.get("fingerprints") or build_selector_fingerprint(
                    item.get("target") or {"label": item.get("target_label", ""), "role": item.get("role", "")}
                ),
                "meta": {
                    "url": item.get("url", ""),
                    "target_ref": item.get("target_ref"),
                    "note": note,
                    "param_key": normalize_param_key(str(item.get("param_key") or "")) or None,
                    "example_value": item.get("value") if item.get("param_key") else None,
                },
            }
        )

    biz_sig = business_step_signature(compiled_steps)
    # Auto-compile only: skip pure login/noise trajectories.
    # Explicit SkillRecorder save must allow login skills (username/password/登录).
    if require_business_steps and len(biz_sig) < _MIN_BUSINESS_STEPS:
        return {
            "success": False,
            "error": "有效业务步骤不足（多为登录噪声），跳过生成技能",
            "skipped": True,
            "reason": "insufficient_business_steps",
        }

    dup = None
    if not force_create:
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
        if (on_duplicate or "reuse").lower() == "suggest":
            return {
                "success": False,
                "duplicate_found": True,
                "skill_id": existing.skill_id,
                "name": existing.name,
                "step_count": len(existing_steps),
                "param_schema": existing.param_schema or {},
                "duplicate_reason": dup.get("reason"),
                "duplicate_score": dup.get("score"),
                "error": (
                    f"已存在相似技能「{existing.name}」。"
                    "请选择复用该技能，或强制新建。"
                ),
                "message": f"已存在相似技能「{existing.name}」",
            }
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


def extract_search_query_hint(text: str) -> str:
    """
    Pull a likely search keyword from a natural-language goal / user utterance.
    Prefers quoted text, then「搜索 X」, then a lone Latin token.
    """
    text = (text or "").strip()
    if not text:
        return ""
    m = re.search(r"[「\"'『]([^」\"'』]+)[」\"'』]", text)
    if m and m.group(1).strip():
        return m.group(1).strip()
    m = re.search(r"搜索\s*([A-Za-z][A-Za-z0-9_\-\.+]{1,64})", text)
    if m:
        return m.group(1)
    m = re.search(r"搜索\s*([^\s，。,；;：:]+?)(?:相关|论文|文档|的|$)", text)
    if m:
        cand = (m.group(1) or "").strip()
        if cand and cand not in ("一下",):
            return cand
    latin = re.findall(r"[A-Za-z][A-Za-z0-9_\-\.+]{1,64}", text)
    if len(latin) == 1:
        return latin[0]
    return ""


def collect_template_keys(steps: Any) -> List[str]:
    """Collect unique {{param}} names from skill steps (order preserved)."""
    seen = set()
    ordered: List[str] = []
    for step in steps or []:
        if hasattr(step, "value_template"):
            tpl = step.value_template or ""
        elif isinstance(step, dict):
            tpl = step.get("value_template") or step.get("value") or ""
        else:
            tpl = ""
        if not isinstance(tpl, str):
            continue
        for m in PARAM_PATTERN.finditer(tpl):
            key = m.group(1)
            if key not in seen:
                seen.add(key)
                ordered.append(key)
    return ordered


def fill_missing_skill_params(
    params: Optional[Dict[str, Any]],
    steps: Any,
    *,
    goal: str = "",
) -> Dict[str, Any]:
    """
    Fill missing {{placeholders}} when the agent only passed goal / partial params.
    Never invent credential fields (username/password/otp/...).
    """
    out = dict(params or {})
    keys = collect_template_keys(steps)
    if not keys:
        return out

    goal_val = str(out.get("goal") or goal or "").strip()
    fill_hint = extract_search_query_hint(goal_val) or goal_val
    if "query" in keys and not str(out.get("query") or "").strip() and fill_hint:
        out["query"] = fill_hint

    missing = [k for k in keys if not str(out.get(k) or "").strip()]
    non_cred_missing = [k for k in missing if k.lower() not in _CREDENTIAL_PARAM_KEYS]
    if fill_hint and len(non_cred_missing) == 1:
        only = non_cred_missing[0]
        if not str(out.get(only) or "").strip():
            out[only] = fill_hint
    return out


def resolve_template(value_template: str, params: Dict[str, Any]) -> str:
    if not value_template:
        return ""

    def repl(m):
        key = m.group(1)
        return str(params.get(key, m.group(0)))

    return PARAM_PATTERN.sub(repl, value_template)


def unresolved_template_keys(value_template: str, params: Dict[str, Any]) -> List[str]:
    resolved = resolve_template(value_template or "", params or {})
    return [m.group(1) for m in PARAM_PATTERN.finditer(resolved)]
