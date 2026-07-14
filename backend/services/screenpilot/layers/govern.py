import asyncio
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from services.screenpilot.url_safety import check_url_safety, host_in_allowlist

T3_KEYWORDS = ("提交", "审批", "删除", "支付", "付款", "通过", "驳回", "确认提交")
T2_KEYWORDS = ("保存", "暂存", "发送", "确定")


def classify_risk(action: str, target_label: str = "", risk_rules: Optional[Dict] = None) -> str:
    action = (action or "").lower()
    label = (target_label or "").lower()

    if action in ("navigate", "screenshot", "extract", "observe", "wait", "scroll"):
        return "T0"
    if action in ("type", "select", "upload"):
        return "T1"

    if action == "click":
        combined = label + " " + str((risk_rules or {}).get("extra_text", ""))
        for kw in T3_KEYWORDS:
            if kw in combined:
                return "T3"
        for kw in T2_KEYWORDS:
            if kw in combined:
                return "T2"
        custom = (risk_rules or {}).get("t3_labels") or []
        for kw in custom:
            if kw in combined:
                return "T3"
        return "T1"

    return "T1"


def requires_hitl(risk_tier: str) -> bool:
    return risk_tier in ("T2", "T3")


def check_domain_allowed(url: str, allowed_domains: List[str]) -> bool:
    if not allowed_domains:
        return True
    host = urlparse(url).hostname or ""
    return host_in_allowlist(host, allowed_domains)


def check_navigation_allowed(
    url: str, allowed_domains: Optional[List[str]] = None
) -> Tuple[bool, str]:
    """Domain allowlist + SSRF/secret checks. Empty allowlist means no host filter."""
    allowed = allowed_domains or []
    if allowed and not check_domain_allowed(url, allowed):
        return False, f"URL 不在域名白名单内: {url}"
    ok, reason = check_url_safety(url, allowed_domains=allowed)
    if not ok:
        return False, reason
    return True, ""


async def snapshot_target_state(page, el: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Capture target widget state for post-action effect checks."""
    if not el or not page:
        return None
    box = el.get("box") or {}
    cx = float(box.get("x", 0)) + float(box.get("width", 0)) / 2
    cy = float(box.get("y", 0)) + float(box.get("height", 0)) / 2
    label = (el.get("label") or "")[:120]
    role = (el.get("role") or "").lower()
    try:
        state = await page.evaluate(
            """({x, y, label, role}) => {
              const associated = (lab) => {
                if (!lab) return null;
                const forId = lab.getAttribute('for');
                if (forId) {
                  try { const el = document.getElementById(forId); if (el) return el; } catch (e) {}
                }
                return lab.querySelector('input[type=checkbox],input[type=radio],[role=checkbox]');
              };
              let el = document.elementFromPoint(x, y);
              let ctrl = null;
              if (role === 'checkbox' || role === 'switch' || role === 'label') {
                const lab = (el && el.closest && el.closest('label')) || (
                  label
                    ? [...document.querySelectorAll('label')].find(l =>
                        ((l.innerText || '').replace(/\\s+/g, ' ')).includes(label)
                      )
                    : null
                );
                ctrl = associated(lab);
                if (!ctrl && el && typeof el.checked === 'boolean') ctrl = el;
              }
              const target = ctrl || el;
              if (!target) return null;
              const st = getComputedStyle(target);
              return {
                tag: (target.tagName || '').toLowerCase(),
                text: ((target.innerText || target.textContent || target.value || '') + '').replace(/\\s+/g, ' ').trim().slice(0, 120),
                checked: typeof target.checked === 'boolean' ? target.checked : null,
                ariaChecked: target.getAttribute('aria-checked'),
                disabled: !!(target.disabled || target.getAttribute('aria-disabled') === 'true'),
                className: ((target.className || '') + '').toString().slice(0, 120),
                opacity: st.opacity,
              };
            }""",
            {"x": cx, "y": cy, "label": label, "role": role},
        )
    except Exception:
        state = None
    return {
        "label": label,
        "role": role,
        "box": {"x": box.get("x"), "y": box.get("y"), "w": box.get("width"), "h": box.get("height")},
        "dom": state,
    }


def _target_state_changed(before: Optional[Dict[str, Any]], after: Optional[Dict[str, Any]]) -> bool:
    if not before or not after:
        return False
    b, a = before.get("dom") or {}, after.get("dom") or {}
    if not b and not a:
        return False
    for key in ("text", "checked", "ariaChecked", "disabled", "className"):
        if b.get(key) != a.get(key):
            return True
    return False


async def verify_action(
    page,
    action: str,
    before_url: str,
    before_shot: bytes,
    *,
    before_target: Optional[Dict[str, Any]] = None,
    target_el: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Generic post-action verification: URL/screenshot/target-state deltas."""
    await asyncio.sleep(0.3)
    after_url = page.url
    after_shot = await page.screenshot(type="png", full_page=False)
    url_changed = after_url != before_url
    shot_changed = after_shot != before_shot

    after_target = None
    target_changed = False
    if target_el is not None or before_target is not None:
        after_target = await snapshot_target_state(page, target_el or {"box": (before_target or {}).get("box") or {}, "label": "", "role": ""})
        target_changed = _target_state_changed(before_target, after_target)

    # type/select/scroll/wait are soft-ok even without visual delta
    soft_ok = action in ("type", "select", "scroll", "wait")
    effect_ok = bool(url_changed or shot_changed or target_changed or soft_ok)

    return {
        "ok": effect_ok,
        "effect_ok": effect_ok,
        "executed": True,
        "before_url": before_url,
        "after_url": after_url,
        "url_changed": url_changed,
        "shot_changed": shot_changed,
        "target_changed": target_changed,
        "before_target": before_target,
        "after_target": after_target,
    }
