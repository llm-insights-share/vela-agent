"""技能确定性重放 + 选择器指纹自愈。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from services.screenpilot.layers.act import clear_and_type, wait_for_page_settle
from services.screenpilot.layers.govern import verify_action


def _host(url: str) -> str:
    try:
        return (urlparse(url or "").netloc or "").lower()
    except Exception:
        return ""


async def try_locate_by_fingerprints(page, fingerprints: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """按优先级尝试定位元素，返回 {method, box?}。

    有 role/label/css 等语义指纹时，语义失败不得回退到录制绝对坐标 box
    （页面不同时 box 会点到错误控件，并被误判为 effect_ok）。
    """
    fingerprints = fingerprints or {}
    role = (fingerprints.get("role") or "").lower()
    label = (fingerprints.get("label") or "").strip()
    box = fingerprints.get("box") or {}
    recorded_url = fingerprints.get("url") or ""
    page_url = ""
    try:
        page_url = page.url or ""
    except Exception:
        page_url = ""

    semantic_hit = False
    semantic_attempted = False

    if role and label:
        semantic_attempted = True
        try:
            locator = page.get_by_role(role, name=label, exact=False)
            if await locator.count() > 0:
                bb = await locator.first.bounding_box()
                if bb:
                    semantic_hit = True
                    return {"method": "role", "box": bb, "role": role, "label": label}
        except Exception:
            pass

    # role without accessible name (e.g. unlabeled body editor)
    if role and not label:
        semantic_attempted = True
        try:
            locator = page.get_by_role(role)
            n = await locator.count()
            if n > 0:
                # Prefer a visible large textbox when multiple
                chosen = locator.first
                if role in ("textbox", "searchbox") and n > 1:
                    best = None
                    best_area = 0
                    for i in range(min(n, 8)):
                        loc = locator.nth(i)
                        try:
                            if not await loc.is_visible():
                                continue
                            bb = await loc.bounding_box()
                        except Exception:
                            continue
                        if not bb:
                            continue
                        area = float(bb.get("width") or 0) * float(bb.get("height") or 0)
                        if area > best_area:
                            best_area = area
                            best = bb
                    if best:
                        semantic_hit = True
                        return {"method": "role", "box": best, "role": role, "label": ""}
                bb = await chosen.bounding_box()
                if bb:
                    semantic_hit = True
                    return {"method": "role", "box": bb, "role": role, "label": ""}
        except Exception:
            pass

    css = fingerprints.get("css")
    if css:
        semantic_attempted = True
        try:
            locator = page.locator(css)
            if await locator.count() > 0:
                bb = await locator.first.bounding_box()
                if bb:
                    semantic_hit = True
                    return {"method": "css", "box": bb}
        except Exception:
            pass

    # Absolute box is only safe on the same recorded host.
    if box.get("width") and box.get("height"):
        if recorded_url and page_url and _host(recorded_url) != _host(page_url):
            return None
        if semantic_attempted and not semantic_hit:
            # Semantic fingerprint existed but missed — do not click stale coordinates.
            return None
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
        recorded = (fingerprints or {}).get("url") or ""
        hint = ""
        if recorded and _host(recorded) != _host(before_url):
            hint = f"；当前页 {before_url[:120]} 与录制页 {_host(recorded)} 不一致，请先导航到录制站点"
        return {
            "success": False,
            "error": f"所有指纹定位方式均失效{hint}",
            "needs_replan": True,
            "page_url": before_url,
            "recorded_url": recorded,
        }

    try:
        if action == "navigate":
            if not value:
                return {"success": False, "error": "navigate 需要 URL"}
            await page.goto(value, wait_until="domcontentloaded", timeout=60000)
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
            elif action == "type":
                await page.mouse.click(cx, cy)
                await clear_and_type(page, value)
            else:
                await page.mouse.click(cx, cy)
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
