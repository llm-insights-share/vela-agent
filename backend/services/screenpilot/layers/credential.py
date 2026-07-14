import asyncio
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from models import ScreenCredential, ScreenSystem
from services.screenpilot.crypto_util import decrypt_secret


def _resolve_credential(db: Session, system_id: str) -> Optional[ScreenCredential]:
    return (
        db.query(ScreenCredential)
        .filter(ScreenCredential.system_id == system_id)
        .first()
    )


def _render_template(value_tpl: str, *, username: str, password: str, otp: str = "") -> str:
    return (
        value_tpl.replace("{{username}}", username)
        .replace("{{password}}", password)
        .replace("{{otp}}", otp)
    )


async def _execute_macro_steps(
    page,
    system: ScreenSystem,
    db: Session,
    steps: list,
    *,
    start_step: int,
    username: str,
    password: str,
    screen_session_id: str = "",
    vela_session_id: str = "",
    agent_id: str = "",
    credential_id: str = "",
) -> Dict[str, Any]:
    for i in range(start_step, len(steps)):
        step = steps[i]
        action = (step.get("action") or "").lower()
        selector = step.get("selector") or ""
        value_tpl = step.get("value") or ""
        value = _render_template(value_tpl, username=username, password=password)
        wait_ms = int(step.get("wait_ms") or 300)

        if action == "goto":
            await page.goto(
                value or system.entry_url,
                wait_until="domcontentloaded",
                timeout=60000,
            )
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
                    "credential_id": credential_id,
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

    cred = _resolve_credential(db, system.system_id)
    username = cred.username if cred else ""
    password = decrypt_secret(cred.secret_enc) if cred and cred.secret_enc else ""
    credential_id = cred.credential_id if cred else ""

    return await _execute_macro_steps(
        page,
        system,
        db,
        steps,
        start_step=start_step,
        username=username,
        password=password,
        screen_session_id=screen_session_id,
        vela_session_id=vela_session_id,
        agent_id=agent_id,
        credential_id=credential_id,
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

    cred = _resolve_credential(db, system.system_id)
    username = cred.username if cred else ""
    password = decrypt_secret(cred.secret_enc) if cred and cred.secret_enc else ""
    credential_id = cred.credential_id if cred else ""

    steps = resume.get("steps") or []
    next_index = int(resume.get("step_index") or 0) + 1

    return await _execute_macro_steps(
        page,
        system,
        db,
        steps,
        start_step=next_index,
        username=username,
        password=password,
        screen_session_id=screen_session_id,
        vela_session_id=vela_session_id,
        agent_id=agent_id,
        credential_id=credential_id,
    )
