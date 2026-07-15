import asyncio
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from models import ScreenCredential, ScreenSystem
from services.screenpilot.crypto_util import decrypt_secret


def load_credential_map(db: Session, system_id: str) -> Dict[str, str]:
    """Decrypt all non-internal credential KV rows for a system."""
    rows = (
        db.query(ScreenCredential)
        .filter(ScreenCredential.system_id == system_id)
        .all()
    )
    out: Dict[str, str] = {}
    _dbg_names = []
    _dbg_decrypt_ok = []
    for row in rows:
        name = (row.name or "").strip()
        if not name or name.startswith("__"):
            continue
        plain = decrypt_secret(row.value_enc or "")
        _dbg_names.append(name)
        _dbg_decrypt_ok.append(bool(plain))
        if plain:
            out[name] = plain
    return out


def merge_params_with_credentials(
    cred_map: Dict[str, str], params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Merge vault credentials; empty-string params do not override vault values."""
    merged: Dict[str, Any] = dict(cred_map or {})
    for k, v in (params or {}).items():
        if v is None:
            continue
        if isinstance(v, str) and not v.strip() and k in merged:
            continue
        merged[k] = v
    return merged


def resolve_value_with_credentials(
    value: Optional[str],
    cred_map: Dict[str, str],
    *,
    target_el: Optional[Dict[str, Any]] = None,
    target_label: str = "",
) -> str:
    """Resolve {{key}} templates; for username/password fields prefer vault when applicable."""
    text = "" if value is None else str(value)
    if cred_map and "{{" in text:
        for key, val in cred_map.items():
            text = text.replace("{{" + key + "}}", val)
    tgt = target_el or {}
    label = (target_label or "") + " " + str(tgt.get("label") or "")
    low = label.lower()
    field_kind = (tgt.get("field_kind") or "").lower()
    input_type = (tgt.get("input_type") or "").lower()
    is_password = (
        field_kind == "password"
        or input_type == "password"
        or "密码" in label
        or "password" in low
    )
    is_username = (
        field_kind == "username"
        or any(k in label for k in ("用户", "账号", "帐号"))
        or "user" in low
        or "account" in low
    ) and not is_password
    if is_password and cred_map.get("password"):
        # Prefer vault over chat plaintext for login password fields.
        if (not text.strip()) or text.strip() in ("{{password}}", "***") or "{{" in (value or ""):
            return cred_map["password"]
        # Also prefer vault when agent typed a value — user asked vault to drive login.
        return cred_map["password"]
    if is_username and cred_map.get("username"):
        if (not text.strip()) or text.strip() in ("{{username}}",) or "{{" in (value or ""):
            return cred_map["username"]
        return cred_map["username"]
    return text


async def auto_fill_login_from_credentials(
    page,
    db: Session,
    *,
    system_id: str,
    elements: list,
) -> Dict[str, Any]:
    """When login_macro is empty: fill SoM username/password from vault and click submit."""
    from services.screenpilot.layers.act import execute_action
    from services.screenpilot.layers.perceive import build_login_form_hint, enrich_field_kinds

    cred_map = load_credential_map(db, system_id)
    if not cred_map.get("username") and not cred_map.get("password"):
        return {"success": False, "skipped": True, "reason": "no_credentials"}

    els = enrich_field_kinds(list(elements or []))
    for i, e in enumerate(els):
        e = dict(e)
        e["ref"] = e.get("ref") or f"[{i + 1}]"
        els[i] = e
    hint = build_login_form_hint(els) or {}
    user_refs = hint.get("username_refs") or []
    pass_refs = hint.get("password_refs") or []
    submit_refs = hint.get("submit_refs") or []

    if not pass_refs and not user_refs:
        # Fallback: scan labels
        for e in els:
            lab = e.get("label") or ""
            if "密码" in lab and (e.get("role") or "") == "textbox":
                pass_refs.append(e.get("ref"))
            elif any(k in lab for k in ("用户", "账号")) and (e.get("role") or "") == "textbox":
                user_refs.append(e.get("ref"))
            elif (e.get("label") or "").strip() == "登录" and (e.get("role") or "") == "button":
                submit_refs.append(e.get("ref"))


    if user_refs and cred_map.get("username"):
        r = await execute_action(
            page, "type", els, target_ref=user_refs[0], value=cred_map["username"]
        )
        if not r.get("success"):
            return {"success": False, "error": r.get("error") or "fill username failed"}
    if pass_refs and cred_map.get("password"):
        r = await execute_action(
            page, "type", els, target_ref=pass_refs[0], value=cred_map["password"]
        )
        if not r.get("success"):
            return {"success": False, "error": r.get("error") or "fill password failed"}
    if submit_refs:
        r = await execute_action(page, "click", els, target_ref=submit_refs[0])
        if not r.get("success"):
            return {"success": False, "error": r.get("error") or "click login failed"}
    elif cred_map.get("password"):
        # fallback: exact button text 登录
        from services.screenpilot.layers.act import _click_by_value

        r = await _click_by_value(page, "text=登录")
        if not r.get("success"):
            return {"success": False, "error": r.get("error") or "click login failed"}

    return {"success": True, "filled": True}


def _render_template(value_tpl: str, values: Dict[str, str], otp: str = "") -> str:
    text = value_tpl or ""
    merged = dict(values or {})
    if otp:
        merged["otp"] = otp
    for key, val in merged.items():
        text = text.replace("{{" + key + "}}", val)
    return text


async def _execute_macro_steps(
    page,
    system: ScreenSystem,
    db: Session,
    steps: list,
    *,
    start_step: int,
    cred_map: Dict[str, str],
    screen_session_id: str = "",
    vela_session_id: str = "",
    agent_id: str = "",
) -> Dict[str, Any]:
    for i in range(start_step, len(steps)):
        step = steps[i]
        action = (step.get("action") or "").lower()
        selector = step.get("selector") or ""
        value_tpl = step.get("value") or ""
        value = _render_template(value_tpl, cred_map)
        wait_ms = int(step.get("wait_ms") or 300)

        if action == "goto":
            await page.goto(
                value or system.entry_url,
                wait_until="domcontentloaded",
                timeout=60000,
            )
            from services.screenpilot.layers.act import wait_for_page_settle

            await wait_for_page_settle(page, timeout_ms=12000)
        elif action == "fill" and selector:
            await page.fill(selector, value)
        elif action == "click" and selector:
            await page.click(selector)
        elif action == "wait":
            await asyncio.sleep(wait_ms / 1000.0)
        elif action == "wait_for_otp":
            from services.screenpilot.service import create_hitl_for_login_otp

            prompt = step.get("prompt") or "请输入短信验证码"
            preview = {
                "flow_kind": "otp_wait",
                "prompt": prompt,
                "selector": selector,
                "submit_selector": step.get("submit_selector") or "",
                "url": page.url,
            }
            try:
                shot = await page.screenshot(type="png", full_page=False)
                import base64

                preview["screenshot_b64"] = base64.b64encode(shot).decode()
            except Exception:
                pass

            approval = create_hitl_for_login_otp(
                db,
                screen_session_id=screen_session_id,
                vela_session_id=vela_session_id,
                agent_id=agent_id,
                prompt=prompt,
                preview_payload=preview,
                login_macro_resume={
                    "system_id": system.system_id,
                    "step_index": i,
                    "step": step,
                    "steps": steps,
                },
            )
            return {
                "success": True,
                "hitl_pending": True,
                "approval_id": approval.approval_id,
                "otp_required": True,
                "message": prompt,
                "preview_payload": preview,
            }
        else:
            return {"success": False, "error": f"未知登录宏步骤: {action}"}
        await asyncio.sleep(wait_ms / 1000.0)

    return {"success": True, "message": "登录宏执行完成", "url": page.url}


async def run_login_macro(
    page,
    system: ScreenSystem,
    db: Session,
    *,
    start_step: int = 0,
    screen_session_id: str = "",
    vela_session_id: str = "",
    agent_id: str = "",
) -> Dict[str, Any]:
    """确定性登录宏（非 LLM）。支持 wait_for_otp 步骤触发 HITL 验证码输入。"""
    macro = system.login_macro or {}
    steps = macro.get("steps") or []
    if not steps:
        entry = system.entry_url
        if entry:
            await page.goto(entry, wait_until="domcontentloaded", timeout=60000)
        return {"success": True, "message": "无登录宏，已导航至入口 URL"}

    cred_map = load_credential_map(db, system.system_id)

    return await _execute_macro_steps(
        page,
        system,
        db,
        steps,
        start_step=start_step,
        cred_map=cred_map,
        screen_session_id=screen_session_id,
        vela_session_id=vela_session_id,
        agent_id=agent_id,
    )


async def resume_login_macro_after_otp(
    page,
    system: ScreenSystem,
    db: Session,
    *,
    otp_code: str,
    resume: Dict[str, Any],
    screen_session_id: str = "",
    vela_session_id: str = "",
    agent_id: str = "",
) -> Dict[str, Any]:
    """OTP 审批通过后：填入验证码并继续执行剩余登录宏。"""
    step = resume.get("step") or {}
    selector = step.get("selector") or ""
    submit_selector = step.get("submit_selector") or ""
    wait_ms = int(step.get("wait_ms") or 300)

    if selector:
        await page.fill(selector, otp_code)
    if submit_selector:
        await page.click(submit_selector)
    await asyncio.sleep(wait_ms / 1000.0)

    cred_map = load_credential_map(db, system.system_id)
    steps = resume.get("steps") or []
    next_index = int(resume.get("step_index") or 0) + 1

    return await _execute_macro_steps(
        page,
        system,
        db,
        steps,
        start_step=next_index,
        cred_map=cred_map,
        screen_session_id=screen_session_id,
        vela_session_id=vela_session_id,
        agent_id=agent_id,
    )
