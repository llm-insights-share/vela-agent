import asyncio
import time
from typing import Any, Dict, List, Optional

from services.screenpilot.layers.govern import (
    check_navigation_allowed,
    snapshot_target_state,
    verify_action,
)
from services.screenpilot.layers.ground import find_element_by_ref


async def _page_readiness(page) -> Dict[str, Any]:
    try:
        return await page.evaluate(
            """() => ({
              readyState: document.readyState,
              title: (document.title || '').slice(0, 80),
              scripts: document.scripts.length,
              imgsIncomplete: [...document.images].filter(i => !i.complete).length,
              bodyTextLen: ((document.body && (document.body.innerText || '').trim()) || '').length,
              interactive: document.querySelectorAll(
                'a,button,input,textarea,select,[role=button],[role=link],[role=textbox],[role=searchbox]'
              ).length
            })"""
        )
    except Exception as e:
        return {"eval_error": str(e)[:120]}


async def wait_for_page_settle(
    page,
    *,
    timeout_ms: int = 12000,
    min_text_len: int = 20,
    min_interactive: int = 3,
) -> Dict[str, Any]:
    """After DCL: wait for load / brief networkidle / SPA content before observe."""
    info: Dict[str, Any] = {
        "load": False,
        "networkidle": False,
        "content": False,
        "timeout_ms": timeout_ms,
    }
    try:
        await page.wait_for_load_state("load", timeout=min(timeout_ms, 15000))
        info["load"] = True
    except Exception:
        pass
    try:
        # Cap networkidle: SPAs often keep long-poll/WS alive.
        await page.wait_for_load_state("networkidle", timeout=min(5000, timeout_ms))
        info["networkidle"] = True
    except Exception:
        pass

    deadline = time.time() + max(0.5, timeout_ms / 1000.0)
    last: Dict[str, Any] = {}
    while time.time() < deadline:
        last = await _page_readiness(page)
        text_len = int(last.get("bodyTextLen") or 0)
        interactive = int(last.get("interactive") or 0)
        if text_len >= min_text_len or interactive >= min_interactive:
            info["content"] = True
            info["ready"] = last
            break
        await asyncio.sleep(0.25)
    if "ready" not in info:
        info["ready"] = last
    return info


async def navigate(page, url: str, allowed_domains: List[str]) -> Dict[str, Any]:
    ok, reason = check_navigation_allowed(url, allowed_domains)
    if not ok:
        return {"success": False, "error": reason}
    # #region agent log
    _t0 = time.time()
    # #endregion
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    # #region agent log
    try:
        import json as _json
        _ready = await _page_readiness(page)
        with open("/Users/zhangjr/apps/LlmDemo/vibe-project/vela-agent/.cursor/debug-66b153.log", "a") as _f:
            _f.write(_json.dumps({
                "sessionId": "66b153", "runId": "post-fix", "hypothesisId": "H1",
                "location": "act.py:navigate:after_goto",
                "message": "goto returned (wait_until=domcontentloaded)",
                "data": {
                    "url": (url or "")[:160],
                    "final_url": (page.url or "")[:160],
                    "elapsed_ms": int((time.time() - _t0) * 1000),
                    "ready": _ready,
                },
                "timestamp": int(time.time() * 1000),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # #endregion

    settle = await wait_for_page_settle(page, timeout_ms=12000)
    # #region agent log
    try:
        import json as _json
        with open("/Users/zhangjr/apps/LlmDemo/vibe-project/vela-agent/.cursor/debug-66b153.log", "a") as _f:
            _f.write(_json.dumps({
                "sessionId": "66b153", "runId": "post-fix", "hypothesisId": "H1",
                "location": "act.py:navigate:after_settle",
                "message": "page settle finished before observe",
                "data": {
                    "url": (page.url or "")[:160],
                    "settle": {
                        "load": settle.get("load"),
                        "networkidle": settle.get("networkidle"),
                        "content": settle.get("content"),
                        "ready": settle.get("ready"),
                    },
                    "elapsed_ms": int((time.time() - _t0) * 1000),
                },
                "timestamp": int(time.time() * 1000),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # #endregion

    final_url = page.url
    # Re-check after redirects to prevent allowlist escape.
    ok_final, reason_final = check_navigation_allowed(final_url, allowed_domains)
    if not ok_final:
        try:
            await page.goto("about:blank", wait_until="domcontentloaded", timeout=5000)
        except Exception:
            pass
        return {
            "success": False,
            "error": f"跳转后 URL 未通过安全检查: {reason_final}",
            "redirected_to": final_url,
        }
    return {"success": True, "url": final_url, "settle": settle}


async def _click_by_value(page, value: str) -> Dict[str, Any]:
    """Click via Playwright text/CSS when SoM ref is unavailable."""
    raw = (value or "").strip()
    if not raw:
        return {"success": False, "error": "click 需要 target_ref 或 value（text=/css=）"}

    locator = None
    mode = "text"
    if raw.startswith("css="):
        mode = "css"
        locator = page.locator(raw[4:].strip()).first
    elif raw.startswith("text="):
        text = raw[5:].strip()
        mode = "text_exact"
        # Prefer exact button name so "登录" does not hit title "用户登录".
        btn = page.get_by_role("button", name=text, exact=True)
        if await btn.count() > 0:
            locator = btn.first
            mode = "role_button_exact"
        else:
            locator = page.get_by_text(text, exact=True).first
    elif raw.startswith("/") or raw.startswith(".") or raw.startswith("#") or raw.startswith("["):
        mode = "css"
        locator = page.locator(raw).first
    else:
        mode = "text_exact"
        btn = page.get_by_role("button", name=raw, exact=True)
        if await btn.count() > 0:
            locator = btn.first
            mode = "role_button_exact"
        else:
            locator = page.get_by_text(raw, exact=True).first

    try:
        await locator.click(timeout=8000)
    except Exception as e:
        return {"success": False, "error": str(e)[:240], "click_mode": mode, "value": raw}
    return {"success": True, "click_mode": mode, "value": raw}


async def _click_associated_checkbox(page, el: Dict[str, Any]) -> Dict[str, Any]:
    """Toggle native/custom checkbox via label association (handles opacity:0 inputs)."""
    label = (el.get("label") or "").strip()[:80]
    box = el.get("box") or {}
    try:
        ok = await page.evaluate(
            """({label, x, y}) => {
              const associated = (lab) => {
                const forId = lab.getAttribute('for');
                if (forId) {
                  try { const el = document.getElementById(forId); if (el) return el; } catch (e) {}
                }
                return lab.querySelector('input[type=checkbox],input[type=radio],[role=checkbox]');
              };
              let lab = null;
              if (label) {
                lab = [...document.querySelectorAll('label')].find(l =>
                  ((l.innerText || '').replace(/\\s+/g, ' ')).includes(label)
                ) || null;
              }
              if (!lab) {
                const hit = document.elementFromPoint(x, y);
                lab = hit ? hit.closest('label') : null;
              }
              const ctrl = lab ? associated(lab) : null;
              if (ctrl) {
                ctrl.click();
                return { ok: true, mode: 'associated_input', checked: !!ctrl.checked };
              }
              if (lab) {
                lab.click();
                return { ok: true, mode: 'label_click', checked: null };
              }
              return { ok: false, mode: 'none' };
            }""",
            {
                "label": label,
                "x": float(box.get("x", 0)) + min(12.0, max(4.0, float(box.get("width", 20)) * 0.08)),
                "y": float(box.get("y", 0)) + float(box.get("height", 0)) / 2,
            },
        )
        if ok and ok.get("ok"):
            return {"success": True, "click_mode": ok.get("mode"), "checked": ok.get("checked")}
        return {"success": False, "error": "no associated checkbox"}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


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
            raw = str(value if value is not None else "1000").strip().lower()
            # Agent sometimes confuses cu_act wait with cu_wait_for_otp.
            if raw in ("otp", "code", "sms", "验证码", "wait_for_otp"):
                return {
                    "success": False,
                    "executed": False,
                    "effect_ok": False,
                    "error": (
                        "cu_act 的 wait 只接受毫秒数字；等待用户输入短信验证码请改用工具 "
                        "cu_wait_for_otp（需提供验证码输入框 selector，可选 submit_selector）"
                    ),
                }
            try:
                ms = int(raw or "1000")
            except ValueError:
                return {
                    "success": False,
                    "executed": False,
                    "effect_ok": False,
                    "error": f"wait 的 value 必须是毫秒整数，收到: {value!r}",
                }
            await asyncio.sleep(ms / 1000.0)
            verification = {"ok": True, "effect_ok": True, "waited_ms": ms, "executed": True}
            return {"success": True, "executed": True, "effect_ok": True, "verification": verification}

        if action == "scroll":
            delta = int(value or 400)
            await page.mouse.wheel(0, delta)
            verification = await verify_action(page, action, before_url, before_shot)
            return {
                "success": True,
                "executed": True,
                "effect_ok": bool(verification.get("effect_ok", verification.get("ok"))),
                "verification": verification,
            }

        if action in ("click", "type", "select"):
            el = find_element_by_ref(elements, target_ref or "") if target_ref else None
            before_target = None
            if el:
                before_target = await snapshot_target_state(page, el)

            if not el and action == "click" and (value or "").strip():
                result = await _click_by_value(page, value or "")
                if not result.get("success"):
                    return {**result, "executed": False, "effect_ok": False}
                verification = await verify_action(
                    page, action, before_url, before_shot, before_target=before_target
                )
                effect_ok = bool(verification.get("effect_ok", verification.get("ok")))
                result["verification"] = verification
                result["executed"] = True
                result["effect_ok"] = effect_ok
                result["success"] = True
                if not effect_ok:
                    result["warning"] = "动作已执行，但未检测到明显 UI 变化；请复核目标或前置条件"
                return result

            if not el:
                return {
                    "success": False,
                    "executed": False,
                    "effect_ok": False,
                    "error": f"未找到元素引用 {target_ref}",
                }

            box = el["box"]
            cx = box["x"] + box["width"] / 2
            cy = box["y"] + box["height"] / 2
            click_mode = None

            if action == "click":
                role = (el.get("role") or "").lower()
                label = (el.get("label") or "").strip()
                # Agreement / custom checkboxes: toggle via associated input first.
                if role in ("checkbox", "switch", "label"):
                    assoc = await _click_associated_checkbox(page, el)
                    if assoc.get("success"):
                        click_mode = assoc.get("click_mode") or "associated_input"
                    else:
                        cx = box["x"] + min(12.0, max(4.0, float(box.get("width", 20)) * 0.08))
                        await page.mouse.click(cx, cy)
                        click_mode = "checkbox_left"
                elif label and len(label) <= 24 and role in ("button", "link"):
                    text_click = await _click_by_value(page, f"text={label}")
                    if text_click.get("success"):
                        click_mode = text_click.get("click_mode")
                    else:
                        await page.mouse.click(cx, cy)
                        click_mode = "coordinate_fallback"
                else:
                    await page.mouse.click(cx, cy)
                    click_mode = "coordinate"
            elif action == "type":
                await page.mouse.click(cx, cy)
                await page.keyboard.press("Control+A")
                await page.keyboard.type(str(value or ""))
            else:
                await page.mouse.click(cx, cy)
                await page.keyboard.type(str(value or ""))

            verification = await verify_action(
                page,
                action,
                before_url,
                before_shot,
                before_target=before_target,
                target_el=el,
            )
            effect_ok = bool(verification.get("effect_ok", verification.get("ok")))
            # For checkbox/label: require checked/ariaChecked flip when possible.
            role_now = (el.get("role") or "").lower()
            if action == "click" and role_now in ("checkbox", "switch", "label"):
                before_dom = (before_target or {}).get("dom") or {}
                after_dom = ((verification.get("after_target") or {}).get("dom") or {})
                flipped = (
                    before_dom.get("checked") != after_dom.get("checked")
                    or before_dom.get("ariaChecked") != after_dom.get("ariaChecked")
                )
                if after_dom and not flipped:
                    effect_ok = False
                    verification["effect_ok"] = False
                    verification["checkbox_flipped"] = False
            result: Dict[str, Any] = {
                "success": True,
                "executed": True,
                "effect_ok": effect_ok,
                "verification": verification,
                "target": el,
            }
            if click_mode:
                result["click_mode"] = click_mode
            if not effect_ok:
                result["warning"] = (
                    "动作已执行，但未检测到明显 UI 变化；请复核目标或前置条件"
                    + ("（协议勾选可能未生效，请改点 checkbox 控件）" if role_now in ("checkbox", "switch", "label") else "")
                )
            return result

        if action == "extract":
            text = await page.inner_text("body")
            return {"success": True, "executed": True, "effect_ok": True, "text": text[:8000]}

        if action == "screenshot":
            shot = await page.screenshot(type="png")
            return {"success": True, "executed": True, "effect_ok": True, "screenshot_len": len(shot)}

        return {"success": False, "executed": False, "effect_ok": False, "error": f"不支持的动作: {action}"}
    except Exception as e:
        return {"success": False, "executed": False, "effect_ok": False, "error": str(e)}
