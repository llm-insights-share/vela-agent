import asyncio
from typing import Any, Dict, List, Optional

from services.screenpilot.layers.govern import check_domain_allowed, verify_action
from services.screenpilot.layers.ground import find_element_by_ref


async def navigate(page, url: str, allowed_domains: List[str]) -> Dict[str, Any]:
    if not check_domain_allowed(url, allowed_domains):
        return {"success": False, "error": f"URL 不在域名白名单内: {url}"}
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    return {"success": True, "url": page.url}


async def execute_action(
    page,
    action: str,
    elements: List[Dict[str, Any]],
    target_ref: Optional[str] = None,
    value: Optional[str] = None,
    allowed_domains: Optional[List[str]] = None,
) -> Dict[str, Any]:
    action = (action or "").lower()
    allowed_domains = allowed_domains or []
    before_url = page.url
    before_shot = await page.screenshot(type="png", full_page=False)

    try:
        if action == "navigate":
            if not value:
                return {"success": False, "error": "navigate 需要 value 为 URL"}
            return await navigate(page, value, allowed_domains)

        if action == "wait":
            ms = int(value or 1000)
            await asyncio.sleep(ms / 1000.0)
            verification = {"ok": True, "waited_ms": ms}
            return {"success": True, "verification": verification}

        if action == "scroll":
            delta = int(value or 400)
            await page.mouse.wheel(0, delta)
            verification = await verify_action(page, action, before_url, before_shot)
            return {"success": True, "verification": verification}

        if action in ("click", "type", "select"):
            el = find_element_by_ref(elements, target_ref or "")
            if not el:
                return {"success": False, "error": f"未找到元素引用 {target_ref}"}
            box = el["box"]
            cx = box["x"] + box["width"] / 2
            cy = box["y"] + box["height"] / 2

            if action == "click":
                await page.mouse.click(cx, cy)
            elif action == "type":
                await page.mouse.click(cx, cy)
                await page.keyboard.press("Control+A")
                await page.keyboard.type(str(value or ""))
            elif action == "select":
                await page.mouse.click(cx, cy)
                await page.keyboard.type(str(value or ""))

            verification = await verify_action(page, action, before_url, before_shot)
            return {"success": True, "verification": verification, "target": el}

        if action == "extract":
            text = await page.inner_text("body")
            return {"success": True, "text": text[:8000]}

        if action == "screenshot":
            shot = await page.screenshot(type="png")
            return {"success": True, "screenshot_len": len(shot)}

        return {"success": False, "error": f"不支持的动作: {action}"}
    except Exception as e:
        return {"success": False, "error": str(e)}
