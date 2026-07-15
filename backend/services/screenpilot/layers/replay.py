"""技能确定性重放 + 选择器指纹自愈。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from services.screenpilot.layers.govern import verify_action


async def try_locate_by_fingerprints(page, fingerprints: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """按优先级尝试定位元素，返回 {method, box?}。"""
    role = (fingerprints.get("role") or "").lower()
    label = fingerprints.get("label") or ""
    box = fingerprints.get("box") or {}

    if role and label:
        try:
            locator = page.get_by_role(role, name=label, exact=False)
            if await locator.count() > 0:
                bb = await locator.first.bounding_box()
                if bb:
                    return {"method": "role", "box": bb, "role": role, "label": label}
        except Exception:
            pass

    css = fingerprints.get("css")
    if css:
        try:
            locator = page.locator(css)
            if await locator.count() > 0:
                bb = await locator.first.bounding_box()
                if bb:
                    return {"method": "css", "box": bb}
        except Exception:
            pass

    if box.get("width") and box.get("height"):
        return {"method": "box", "box": box}

    return None


async def execute_by_fingerprints(
    page,
    action: str,
    fingerprints: Dict[str, Any],
    value: Optional[str] = None,
) -> Dict[str, Any]:
    action = (action or "").lower()
    before_url = page.url
    before_shot = await page.screenshot(type="png", full_page=False)

    located = await try_locate_by_fingerprints(page, fingerprints)
    if not located and action not in ("navigate", "wait", "scroll"):
        return {"success": False, "error": "所有指纹定位方式均失效", "needs_replan": True}

    try:
        if action == "navigate":
            if not value:
                return {"success": False, "error": "navigate 需要 URL"}
            await page.goto(value, wait_until="domcontentloaded", timeout=60000)
            from services.screenpilot.layers.act import wait_for_page_settle

            await wait_for_page_settle(page, timeout_ms=12000)
        elif action == "wait":
            import asyncio
            await asyncio.sleep(int(value or 1000) / 1000.0)
        elif action == "scroll":
            delta = int(value or 400)
            await page.mouse.wheel(0, delta)
        elif action in ("click", "type", "select"):
            bb = located["box"]
            cx = bb["x"] + bb["width"] / 2
            cy = bb["y"] + bb["height"] / 2
            if action == "click":
                await page.mouse.click(cx, cy)
            else:
                await page.mouse.click(cx, cy)
                if action == "type":
                    await page.keyboard.press("Control+A")
                await page.keyboard.type(str(value or ""))
        else:
            return {"success": False, "error": f"重放不支持动作: {action}"}

        verification = await verify_action(page, action, before_url, before_shot)
        return {
            "success": True,
            "verification": verification,
            "locate_method": located.get("method") if located else None,
        }
    except Exception as e:
        return {"success": False, "error": str(e), "needs_replan": True}


async def enrich_fingerprints_from_page(page, element: Dict[str, Any]) -> Dict[str, Any]:
    """执行成功后补充/更新指纹。"""
    fp = {
        "ref": element.get("ref"),
        "role": element.get("role"),
        "label": element.get("label"),
        "box": element.get("box"),
        "path": element.get("path"),
        "url": page.url,
    }
    located = await try_locate_by_fingerprints(page, fp)
    if located:
        fp["box"] = located.get("box") or fp.get("box")
        fp["last_method"] = located.get("method")
    return fp
