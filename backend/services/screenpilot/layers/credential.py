import asyncio
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from models import ScreenCredential, ScreenSystem
from services.screenpilot.crypto_util import decrypt_secret
from services.screenpilot.layers.act import execute_action


async def run_login_macro(page, system: ScreenSystem, db: Session) -> Dict[str, Any]:
    """确定性登录宏（非 LLM）。"""
    macro = system.login_macro or {}
    steps = macro.get("steps") or []
    if not steps:
        entry = system.entry_url
        if entry:
            await page.goto(entry, wait_until="domcontentloaded", timeout=60000)
        return {"success": True, "message": "无登录宏，已导航至入口 URL"}

    cred = (
        db.query(ScreenCredential)
        .filter(ScreenCredential.system_id == system.system_id)
        .first()
    )
    username = cred.username if cred else ""
    password = decrypt_secret(cred.secret_enc) if cred and cred.secret_enc else ""

    for step in steps:
        action = (step.get("action") or "").lower()
        selector = step.get("selector") or ""
        value_tpl = step.get("value") or ""
        value = (
            value_tpl.replace("{{username}}", username).replace("{{password}}", password)
        )
        wait_ms = int(step.get("wait_ms") or 300)

        if action == "goto":
            await page.goto(value or system.entry_url, wait_until="domcontentloaded", timeout=60000)
        elif action == "fill" and selector:
            await page.fill(selector, value)
        elif action == "click" and selector:
            await page.click(selector)
        elif action == "wait":
            await asyncio.sleep(wait_ms / 1000.0)
        else:
            return {"success": False, "error": f"未知登录宏步骤: {action}"}
        await asyncio.sleep(wait_ms / 1000.0)

    return {"success": True, "message": "登录宏执行完成", "url": page.url}
