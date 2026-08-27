import hashlib
import io
import json
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

INTERACTIVE_ROLES = {
    "button",
    "link",
    "textbox",
    "combobox",
    "checkbox",
    "radio",
    "menuitem",
    "tab",
    "switch",
    "searchbox",
    "slider",
    "spinbutton",
}

# More specific roles win when merging a11y + DOM duplicates.
ROLE_SPECIFICITY = {
    "checkbox": 50,
    "radio": 50,
    "switch": 45,
    "textbox": 40,
    "searchbox": 40,
    "combobox": 40,
    "button": 35,
    "link": 30,
    "menuitem": 30,
    "tab": 25,
    "slider": 25,
    "spinbutton": 25,
    "label": 20,
    "hotspot": 15,
    "generic": 5,
}

DEFAULT_MAX_ELEMENTS = 100
IOU_MERGE_THRESHOLD = 0.6

LOGIN_WALL_HINTS = (
    "log in to",
    "scan qr code",
    "登录后",
    "扫码登录",
    "log in to explore more",
    "log in to get notes",
)

# Soft structural boost only (language-agnostic agreement / legal patterns).
AGREEMENT_KEYWORDS = (
    "agree",
    "terms",
    "privacy",
    "同意",
    "协议",
    "隐私",
)

# Structural DOM collector: no site-specific verb lists.
_DOM_COLLECT_JS = """
(limit) => {
  const sels = [
    'input', 'textarea', 'button', 'a', 'select', 'label',
    '[role=button]', '[role=link]', '[role=textbox]',
    '[role=searchbox]', '[role=combobox]', '[role=checkbox]',
    '[role=radio]', '[role=switch]', '[role=tab]', '[aria-checked]',
    '[contenteditable=true]'
  ];

  const isVisible = (el, r, minSize) => {
    if (!r || r.width < minSize || r.height < minSize) return false;
    if (r.bottom < 0 || r.right < 0 || r.top > innerHeight || r.left > innerWidth) return false;
    const st = window.getComputedStyle(el);
    if (!st || st.display === 'none' || st.visibility === 'hidden' || st.pointerEvents === 'none') return false;
    if (parseFloat(st.opacity || '1') === 0) return false;
    return true;
  };

  // Softer gate for inline actions (send-code link/span often has pointer-events quirks).
  const softVisible = (el, r, minSize) => {
    if (!r || r.width < minSize || r.height < minSize) return false;
    if (r.bottom < 0 || r.right < 0 || r.top > innerHeight || r.left > innerWidth) return false;
    const st = window.getComputedStyle(el);
    if (!st || st.display === 'none' || st.visibility === 'hidden') return false;
    return true;
  };

  const shortText = (el) => {
    const t = ((el.innerText || el.textContent || el.value || '') + '').replace(/\\s+/g, ' ').trim();
    return t.slice(0, 120);
  };

  const isFormControl = (el) => {
    const tag = (el.tagName || '').toLowerCase();
    return tag === 'input' || tag === 'textarea' || tag === 'select' || tag === 'button'
      || el.getAttribute('role') === 'textbox' || el.isContentEditable;
  };

  const centersNear = (a, b, maxDx, maxDy) => {
    const ra = a.getBoundingClientRect();
    const rb = b.getBoundingClientRect();
    const ax = ra.x + ra.width / 2, ay = ra.y + ra.height / 2;
    const bx = rb.x + rb.width / 2, by = rb.y + rb.height / 2;
    return Math.abs(ax - bx) <= maxDx && Math.abs(ay - by) <= maxDy;
  };

  // Same row + small horizontal gap / overlap (inline "send code" beside inputs).
  const rowAdjacent = (a, b, maxGap = 56) => {
    const ra = a.getBoundingClientRect();
    const rb = b.getBoundingClientRect();
    const overlapY = Math.min(ra.y + ra.height, rb.y + rb.height) - Math.max(ra.y, rb.y);
    if (overlapY < Math.min(ra.height, rb.height, 14) * 0.35) return false;
    const gapX = Math.max(0, Math.max(ra.x - (rb.x + rb.width), rb.x - (ra.x + ra.width)));
    const overlapX = Math.min(ra.x + ra.width, rb.x + rb.width) - Math.max(ra.x, rb.x);
    return gapX <= maxGap || overlapX > 0;
  };

  const associatedControl = (lab) => {
    if (!lab) return null;
    const forId = lab.getAttribute('for');
    if (forId) {
      try {
        const byId = document.getElementById(forId);
        if (byId) return byId;
      } catch (e) {}
    }
    return lab.querySelector('input[type=checkbox],input[type=radio],[role=checkbox]');
  };

  // Textbox labels: aria/placeholder/label[for]/parent label only.
  // Do NOT steal adjacent short sibling text (those become separate buttons).
  const resolveLabel = (el, role) => {
    const aria = el.getAttribute('aria-label');
    if (aria) return aria.trim().slice(0, 120);
    if (el.id) {
      const byFor = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
      if (byFor) {
        // If label wraps both input and a short action leaf, prefer placeholder.
        const t = (byFor.innerText || '').trim();
        const ph = (el.getAttribute('placeholder') || '').trim();
        if (role === 'textbox' && ph) return ph.slice(0, 120);
        return t.slice(0, 120);
      }
    }
    const parentLabel = el.closest('label');
    if (parentLabel && role !== 'textbox') {
      return (parentLabel.innerText || '').trim().slice(0, 120);
    }
    if (parentLabel && role === 'textbox') {
      const ph = (el.getAttribute('placeholder') || '').trim();
      if (ph) return ph.slice(0, 120);
      // Avoid using huge parent label that includes sibling action text.
      const own = shortText(el);
      if (own) return own;
      const t = (parentLabel.innerText || '').trim();
      if (t.length <= 24) return t.slice(0, 120);
      return ph || (el.getAttribute('name') || '').trim().slice(0, 120);
    }
    const ph = (el.getAttribute('placeholder') || '').trim();
    if (ph) return ph.slice(0, 120);
    const val = (el.getAttribute('value') || '').trim();
    if (val && role === 'button') return val.slice(0, 120);
    const name = el.getAttribute('name');
    if (name) return name.trim().slice(0, 120);
    return shortText(el) || (el.getAttribute('title') || '').slice(0, 120);
  };

  const resolveRole = (el) => {
    const tag = (el.tagName || '').toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    let role = (el.getAttribute('role') || '').toLowerCase();
    if (role) return role;
    if (tag === 'input' && type === 'checkbox') return 'checkbox';
    if (tag === 'input' && type === 'radio') return 'radio';
    if (tag === 'input' && type === 'password') return 'textbox';
    if (tag === 'input' && (type === 'search' || (el.name || '').includes('search'))) return 'searchbox';
    if (tag === 'a') return 'link';
    if (tag === 'button' || type === 'button' || type === 'submit') return 'button';
    if (tag === 'label') return 'label';
    if (tag === 'select') return 'combobox';
    if (tag === 'input' || tag === 'textarea' || el.isContentEditable) return 'textbox';
    if (el.hasAttribute('aria-checked')) return 'checkbox';
    // Structural pseudo-button: short-text leaf near form control, or pointer/tab.
    const t = shortText(el);
    if (t && t.length >= 1 && t.length <= 16) {
      const stCursor = (getComputedStyle(el).cursor || '');
      if (
        stCursor === 'pointer'
        || typeof el.onclick === 'function'
        || (el.getAttribute('role') || '') === 'tab'
      ) {
        return 'button';
      }
      const inputs = document.querySelectorAll('input, textarea, button, [role=textbox]');
      for (const inp of inputs) {
        if (inp === el) continue;
        if (centersNear(el, inp, 280, 64) || rowAdjacent(el, inp, 72)) return 'button';
        if (inp.parentElement && el.parentElement && inp.parentElement.contains(el)) return 'button';
      }
    }
    return tag || 'generic';
  };

  const resolveChecked = (el) => {
    if (typeof el.checked === 'boolean') return el.checked;
    const ac = el.getAttribute('aria-checked');
    if (ac === 'true') return true;
    if (ac === 'false') return false;
    const tag = (el.tagName || '').toLowerCase();
    if (tag === 'label') {
      const ctrl = associatedControl(el);
      if (ctrl && typeof ctrl.checked === 'boolean') return ctrl.checked;
      if (ctrl) {
        const cac = ctrl.getAttribute('aria-checked');
        if (cac === 'true') return true;
        if (cac === 'false') return false;
      }
    }
    return null;
  };

  const nodes = [];
  const seenEl = new Set();
  for (const el of document.querySelectorAll(sels.join(','))) {
    if (seenEl.has(el)) continue;
    seenEl.add(el);
    nodes.push(el);
  }

  // Discover short-text leaf widgets adjacent to form controls (language-agnostic).
  const formControls = [...document.querySelectorAll('input, textarea, select, button')];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
  let n;
  while ((n = walker.nextNode())) {
    if (nodes.length + 80 >= limit) break;
    if (seenEl.has(n)) continue;
    const tag = (n.tagName || '').toLowerCase();
    if (tag === 'script' || tag === 'style' || tag === 'svg' || tag === 'path') continue;
    if (isFormControl(n)) continue;
    const t = shortText(n);
    if (!t || t.length < 1 || t.length > 16) continue;
    // Prefer leaf-ish nodes (few element children).
    if (n.children && n.children.length > 3) continue;
    const r = n.getBoundingClientRect();
    if (!softVisible(n, r, 4)) continue;
    let near = false;
    for (const fc of formControls) {
      if (centersNear(n, fc, 280, 64) || rowAdjacent(n, fc, 72)) { near = true; break; }
      if (fc.parentElement && fc.parentElement.contains(n)) { near = true; break; }
    }
    // Also keep checkbox-like custom widgets with aria-checked.
    const isCheck = n.hasAttribute('aria-checked') || (n.getAttribute('role') || '') === 'checkbox';
    // Short clickable leaves (tabs/nav chips) even when the page has form controls.
    const stCursor = (getComputedStyle(n).cursor || '');
    const standaloneClickable = (
      stCursor === 'pointer' || typeof n.onclick === 'function' || tag === 'a' || tag === 'button'
      || (n.getAttribute('role') || '') === 'button' || (n.getAttribute('role') || '') === 'link'
      || (n.getAttribute('role') || '') === 'tab'
    );
    if (near || isCheck || standaloneClickable) {
      seenEl.add(n);
      nodes.push(n);
    }
  }

  // Same-parent / ancestor siblings of inputs: classic inline send-code link|span.
  for (const inp of document.querySelectorAll('input, textarea')) {
    let scope = inp.parentElement;
    for (let depth = 0; depth < 3 && scope; depth++, scope = scope.parentElement) {
      const candidates = scope.querySelectorAll(
        'a, button, span, div, p, [role=button], [role=link]'
      );
      for (const child of candidates) {
        if (nodes.length + 80 >= limit) break;
        if (seenEl.has(child) || child === inp) continue;
        if (child.contains(inp) || inp.contains(child)) continue;
        const t = shortText(child);
        if (!t || t.length < 1 || t.length > 16) continue;
        if (child.children && child.children.length > 4) continue;
        const r = child.getBoundingClientRect();
        if (!softVisible(child, r, 4)) continue;
        if (!(centersNear(child, inp, 360, 80) || rowAdjacent(child, inp, 120))) continue;
        seenEl.add(child);
        nodes.push(child);
      }
    }
  }

  const dialogs = [];
  for (const d of document.querySelectorAll('[role=dialog], [aria-modal=true], .modal, .dialog, [class*="login"], [class*="Login"]')) {
    const r = d.getBoundingClientRect();
    if (!r || r.width < 80 || r.height < 80) continue;
    if (r.bottom < 0 || r.right < 0 || r.top > innerHeight || r.left > innerWidth) continue;
    dialogs.push({ x: r.x, y: r.y, width: r.width, height: r.height });
  }

  const out = [];
  const seen = new Set();
  for (const el of nodes) {
    if (out.length >= limit) break;
    const role = resolveRole(el);
    const tag = (el.tagName || '').toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    const isNativeCheck = tag === 'input' && (type === 'checkbox' || type === 'radio');
    let r = el.getBoundingClientRect();
    // Native checkboxes are often opacity:0 / 0-size; still expose via label geometry.
    if (isNativeCheck) {
      let boxEl = el;
      if (r.width < 4 || r.height < 4 || parseFloat((getComputedStyle(el).opacity || '1')) === 0) {
        const lab = el.id
          ? document.querySelector('label[for="' + CSS.escape(el.id) + '"]')
          : el.closest('label');
        if (lab) {
          boxEl = lab;
          r = lab.getBoundingClientRect();
        }
      }
      if (!r || r.width < 2 || r.height < 2) continue;
      if (r.bottom < 0 || r.right < 0 || r.top > innerHeight || r.left > innerWidth) continue;
      const key = ['checkbox', Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)].join(':');
      if (seen.has(key)) continue;
      seen.add(key);
      const item = {
        role: type === 'radio' ? 'radio' : 'checkbox',
        label: resolveLabel(boxEl === el ? el : boxEl, 'checkbox') || resolveLabel(el, 'checkbox'),
        box: {
          x: r.x,
          y: r.y,
          // Prefer left tick hit-area when using label geometry.
          width: Math.min(28, Math.max(14, r.height || 16)),
          height: Math.min(28, Math.max(14, r.height || 16)),
        },
        path: 'dom/input',
        source: 'dom',
        checked: resolveChecked(el),
      };
      out.push(item);
      continue;
    }
    const minSize = (role === 'checkbox' || role === 'radio' || role === 'switch') ? 8 : 2;
    // Links/buttons/short inline actions: soft visibility (allow pointer-events quirks).
    const useSoft = role === 'button' || role === 'link' || tag === 'a' || tag === 'span' || tag === 'div';
    if (useSoft) {
      if (!softVisible(el, r, minSize)) continue;
    } else if (!isVisible(el, r, minSize)) {
      continue;
    }
    const key = [el.tagName, Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)].join(':');
    if (seen.has(key)) continue;
    seen.add(key);
    // Prefer link role for <a>; pseudo leaves become button.
    let outRole = role;
    if (tag === 'a') outRole = 'link';
    const checked = resolveChecked(el);
    const item = {
      role: outRole,
      label: resolveLabel(el, outRole),
      box: { x: r.x, y: r.y, width: r.width, height: r.height },
      path: 'dom/' + tag,
      source: 'dom',
    };
    if (tag === 'input' || tag === 'button') {
      item.input_type = type || (tag === 'button' ? 'button' : 'text');
    }
    // Make password fields unmistakable for the agent (avoid typing password into username).
    if (type === 'password') {
      item.input_type = 'password';
      item.field_kind = 'password';
      if (!item.label || item.label === name) {
        item.label = (el.getAttribute('placeholder') || '').trim() || 'password';
      }
    }
    if (type === 'submit' || (outRole === 'button' && /登录|login|sign\\s*in/i.test(item.label || ''))) {
      item.field_kind = 'login_submit';
    }
    // Only expose checked for real checkable roles (avoid input.checked noise on textboxes).
    if (checked !== null && (outRole === 'checkbox' || outRole === 'radio' || outRole === 'switch' || outRole === 'label')) {
      item.checked = checked;
    }
    out.push(item);
  }
  return { elements: out, dialogs };
}
"""


def _walk_a11y(node: Dict[str, Any], out: List[Dict[str, Any]], path: str = "") -> None:
    if not isinstance(node, dict):
        return
    role = (node.get("role") or "").lower()
    name = (node.get("name") or node.get("value") or "").strip()
    box = node.get("boundingBox") or node.get("box")
    if role in INTERACTIVE_ROLES and box and isinstance(box, dict):
        out.append(
            {
                "role": role,
                "label": name,
                "box": {
                    "x": box.get("x", 0),
                    "y": box.get("y", 0),
                    "width": box.get("width", 0),
                    "height": box.get("height", 0),
                },
                "path": path,
                "source": "a11y",
            }
        )
    children = node.get("children") or []
    for i, child in enumerate(children):
        _walk_a11y(child, out, f"{path}/{role}[{i}]")


def extract_a11y_elements(a11y_tree: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if a11y_tree:
        _walk_a11y(a11y_tree, out)
    return out


async def page_css_viewport_size(page) -> Tuple[float, float]:
    """CSS viewport size for aligning SoM boxes with screenshots."""
    vp = getattr(page, "viewport_size", None) or None
    if isinstance(vp, dict) and vp.get("width") and vp.get("height"):
        return float(vp["width"]), float(vp["height"])
    try:
        size = await page.evaluate(
            "() => ({ w: window.innerWidth || 0, h: window.innerHeight || 0 })"
        )
        if isinstance(size, dict):
            w = float(size.get("w") or 0)
            h = float(size.get("h") or 0)
            if w > 0 and h > 0:
                return w, h
    except Exception:
        pass
    return 0.0, 0.0


async def capture_page_state(page) -> Tuple[bytes, Dict[str, Any], str]:
    """截图 + 无障碍树，返回 (png_bytes, a11y_tree, url)。

    使用 scale='css'，使截图像素与 getBoundingClientRect / a11y box（CSS 像素）对齐，
    避免 Retina/DPR 下 SoM 框整体偏左上。
    """
    url = page.url
    try:
        screenshot = await page.screenshot(type="png", full_page=False, scale="css")
    except TypeError:
        # Older Playwright without scale= — caller/build_som will rescale via viewport.
        screenshot = await page.screenshot(type="png", full_page=False)
    try:
        # interesting_only=False keeps custom widgets that screen readers may still expose.
        tree = await page.accessibility.snapshot(interesting_only=False)
    except Exception:
        tree = {}
    return screenshot, tree or {}, url


async def collect_dom_elements(
    page, limit: int = 200
) -> Tuple[List[Dict[str, Any]], List[Dict[str, float]]]:
    """从 DOM 采集可交互元素；同时返回可见 dialog bbox 列表。"""
    try:
        raw = await page.evaluate(_DOM_COLLECT_JS, limit)
        if isinstance(raw, dict):
            elements = list(raw.get("elements") or [])
            dialogs = list(raw.get("dialogs") or [])
        else:
            elements = list(raw or [])
            dialogs = []
        if limit and len(elements) > limit:
            elements = elements[:limit]
        return elements, dialogs
    except Exception:
        return [], []


def _box_area(box: Dict[str, Any]) -> float:
    return max(0.0, float(box.get("width", 0))) * max(0.0, float(box.get("height", 0)))


def _box_center(box: Dict[str, Any]) -> Tuple[float, float]:
    return (
        float(box.get("x", 0)) + float(box.get("width", 0)) / 2,
        float(box.get("y", 0)) + float(box.get("height", 0)) / 2,
    )


def box_iou(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    ax1, ay1 = float(a.get("x", 0)), float(a.get("y", 0))
    ax2, ay2 = ax1 + float(a.get("width", 0)), ay1 + float(a.get("height", 0))
    bx1, by1 = float(b.get("x", 0)), float(b.get("y", 0))
    bx2, by2 = bx1 + float(b.get("width", 0)), by1 + float(b.get("height", 0))
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    union = _box_area(a) + _box_area(b) - inter
    return inter / union if union > 0 else 0.0


def _point_in_box(px: float, py: float, box: Dict[str, Any]) -> bool:
    x, y = float(box.get("x", 0)), float(box.get("y", 0))
    w, h = float(box.get("width", 0)), float(box.get("height", 0))
    return x <= px <= x + w and y <= py <= y + h


def _prefer_element(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    ra = ROLE_SPECIFICITY.get((a.get("role") or "").lower(), 0)
    rb = ROLE_SPECIFICITY.get((b.get("role") or "").lower(), 0)
    if ra != rb:
        winner, other = (a, b) if ra > rb else (b, a)
    else:
        la = len(a.get("label") or "")
        lb = len(b.get("label") or "")
        if la != lb:
            winner, other = (a, b) if la > lb else (b, a)
        elif a.get("source") == "dom" and b.get("source") != "dom":
            winner, other = a, b
        elif b.get("source") == "dom" and a.get("source") != "dom":
            winner, other = b, a
        else:
            winner, other = a, b
    # Preserve DOM-only metadata lost when a11y wins the merge.
    out = dict(winner)
    for key in ("input_type", "field_kind", "checked"):
        if not out.get(key) and other.get(key) is not None:
            out[key] = other[key]
    return out


def enrich_field_kinds(elements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Infer password/username/login_submit from labels when DOM type is missing."""
    out: List[Dict[str, Any]] = []
    for raw in elements or []:
        e = dict(raw)
        role = (e.get("role") or "").lower()
        label = (e.get("label") or "").strip()
        low = label.lower()
        if role in ("textbox", "searchbox"):
            if (e.get("input_type") or "").lower() == "password" or "密码" in label or "password" in low:
                e["input_type"] = "password"
                e["field_kind"] = "password"
            elif any(k in label for k in ("用户", "账号", "帐号")) or "user" in low or "account" in low:
                e["field_kind"] = e.get("field_kind") or "username"
        if role == "button":
            if label in ("登录", "Login", "Sign in", "Log in"):
                e["field_kind"] = "login_submit"
            elif label == "用户登录" or (label.endswith("登录") and label != "登录"):
                e["field_kind"] = "login_title"
        out.append(e)
    return out


def merge_elements(
    a11y_els: List[Dict[str, Any]],
    dom_els: List[Dict[str, Any]],
    *,
    iou_threshold: float = IOU_MERGE_THRESHOLD,
) -> List[Dict[str, Any]]:
    """Merge a11y + DOM elements; dedupe by IoU / center proximity."""
    merged: List[Dict[str, Any]] = []
    for el in list(a11y_els or []) + list(dom_els or []):
        box = el.get("box") or {}
        if _box_area(box) <= 0:
            continue
        cx, cy = _box_center(box)
        dup_idx = None
        for i, existing in enumerate(merged):
            ebox = existing.get("box") or {}
            if box_iou(box, ebox) >= iou_threshold:
                dup_idx = i
                break
            ex, ey = _box_center(ebox)
            if abs(cx - ex) < 8 and abs(cy - ey) < 8:
                dup_idx = i
                break
        if dup_idx is None:
            merged.append(dict(el))
        else:
            merged[dup_idx] = _prefer_element(merged[dup_idx], el)
    return merged


LOGIN_SUBMIT_HINTS = ("登录", "login", "sign in", "signin", "log in", "提交登录")


def rank_elements_for_som(
    elements: List[Dict[str, Any]],
    dialogs: Optional[List[Dict[str, float]]] = None,
) -> List[Dict[str, Any]]:
    """Boost elements inside visible dialogs (Hermes app-scope equivalent)."""
    dialogs = dialogs or []

    def score(el: Dict[str, Any]) -> Tuple[int, int, int, float]:
        box = el.get("box") or {}
        cx, cy = _box_center(box)
        in_dialog = 1 if any(_point_in_box(cx, cy, d) for d in dialogs) else 0
        role_score = ROLE_SPECIFICITY.get((el.get("role") or "").lower(), 0)
        label = (el.get("label") or "").lower().strip()
        agreement_boost = 1 if any(k.lower() in label for k in AGREEMENT_KEYWORDS) else 0
        login_boost = 0
        if el.get("field_kind") == "login_title":
            login_boost = -2  # demote SSO page titles like「用户登录」
        elif (el.get("field_kind") == "login_submit") or (
            (el.get("role") or "").lower() == "button"
            and (el.get("label") or "").strip().lower() in ("登录", "login", "sign in", "log in")
        ):
            login_boost = 3
        if (el.get("input_type") or "").lower() == "password" or el.get("field_kind") == "password":
            login_boost = max(login_boost, 2)
        # Prefer compact interactive controls inside dialogs over huge cards.
        area = _box_area(box)
        compact_boost = 1 if area < 8000 and (el.get("role") or "") in (
            "checkbox", "switch", "button", "textbox", "label",
        ) else 0
        # Deprioritize tiny domain-prefix chips (e.g. "ai\\") next to username.
        tiny_chip_penalty = 0
        if (el.get("role") or "") in ("button", "link") and 0 < len(label) <= 4 and area < 1200:
            tiny_chip_penalty = 1
        return (
            in_dialog,
            login_boost + agreement_boost + compact_boost - tiny_chip_penalty,
            role_score,
            -min(area / 50000.0, 20),
        )

    return sorted(elements, key=score, reverse=True)


def build_login_form_hint(elements: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """When a password field is present, point agent at username/password/submit refs."""
    els = elements or []
    passwords = [
        e for e in els
        if (e.get("input_type") or "").lower() == "password" or e.get("field_kind") == "password"
    ]
    if not passwords:
        return None
    textboxes = [
        e for e in els
        if (e.get("role") or "").lower() in ("textbox", "searchbox")
        and (e.get("input_type") or "").lower() != "password"
        and e.get("field_kind") != "password"
    ]
    submits = [
        e for e in els
        if e.get("field_kind") == "login_submit"
        or (
            (e.get("role") or "").lower() == "button"
            and (e.get("label") or "").strip() in ("登录", "Login", "Sign in", "Log in")
        )
    ]
    # Never treat titles like「用户登录」as submit.
    submits = [e for e in submits if e.get("field_kind") != "login_title"]
    submits_exact = [e for e in submits if (e.get("label") or "").strip() in ("登录", "Login", "Sign in", "Log in")]
    if submits_exact:
        submits = submits_exact
    return {
        "username_refs": [e.get("ref") for e in textboxes[:3] if e.get("ref")],
        "password_refs": [e.get("ref") for e in passwords[:2] if e.get("ref")],
        "submit_refs": [e.get("ref") for e in submits[:3] if e.get("ref")],
        "submit_labels": [(e.get("label") or "")[:20] for e in submits[:3]],
        "hint": (
            "检测到登录表单：请先 type 用户名到 username_refs（不要点域名前缀如 ai\\），"
            "再 type 密码到 password_refs（input_type=password / 标签含「密码」），"
            "最后 click 真正的提交按钮 submit_refs（橙色「登录」原文，不要点「用户登录」标题）。"
            "也可用 cu_act click value=text=登录 兜底（exact 匹配）。"
        ),
    }


def prepare_som_elements(
    a11y_els: List[Dict[str, Any]],
    dom_els: List[Dict[str, Any]],
    dialogs: Optional[List[Dict[str, float]]] = None,
    *,
    max_elements: int = DEFAULT_MAX_ELEMENTS,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Merge, rank, and cap elements for SoM. Returns (elements, meta)."""
    merged = enrich_field_kinds(merge_elements(a11y_els, dom_els))
    ranked = rank_elements_for_som(merged, dialogs)
    total = len(ranked)
    truncated = total > max_elements
    capped = ranked[:max_elements]
    scope = "dialog" if dialogs else "page"
    if a11y_els and dom_els:
        som_source = "a11y+dom"
    elif a11y_els:
        som_source = "a11y"
    elif dom_els:
        som_source = "dom"
    else:
        som_source = "empty"
    meta = {
        "som_source": som_source,
        "total_elements": total,
        "truncated": truncated,
        "scope": scope,
        "dialog_count": len(dialogs or []),
    }
    return capped, meta


def detect_risk_block(
    body_text: str,
    page_url: str = "",
    risk_rules: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, str]]:
    """Detect blocked / risk pages using per-system risk_rules (no site hardcoding)."""
    rules = risk_rules or {}
    low_body = (body_text or "").lower()
    low_url = (page_url or "").lower()

    url_subs = [str(x).lower() for x in (rules.get("block_url_substrings") or []) if x]
    body_hints = [str(x).lower() for x in (rules.get("block_body_hints") or []) if x]
    error_code = str(rules.get("block_error_code") or "RISK_BLOCK")
    message = str(
        rules.get("block_message")
        or "页面触发安全/网络限制，无法继续当前操作"
    )

    if any(s in low_url for s in url_subs):
        return {"error_code": error_code, "message": message}
    if any(h in low_body for h in body_hints):
        return {"error_code": error_code, "message": message}
    return None


def detect_login_wall(body_text: str) -> bool:
    low = (body_text or "").lower()
    return any(h in low for h in LOGIN_WALL_HINTS)


def _som_image_scale(
    img_w: int,
    img_h: int,
    viewport_size: Optional[Tuple[float, float]],
) -> Tuple[float, float]:
    """Map CSS-pixel boxes onto screenshot pixels when sizes diverge (e.g. DPR)."""
    if not viewport_size:
        return 1.0, 1.0
    vw, vh = float(viewport_size[0] or 0), float(viewport_size[1] or 0)
    if vw <= 0 or vh <= 0 or img_w <= 0 or img_h <= 0:
        return 1.0, 1.0
    sx = float(img_w) / vw
    sy = float(img_h) / vh
    # Ignore tiny float noise; treat near-1 as identity.
    if abs(sx - 1.0) < 0.05 and abs(sy - 1.0) < 0.05:
        return 1.0, 1.0
    # Guard against pathological ratios (wrong viewport).
    if sx < 0.4 or sx > 4.0 or sy < 0.4 or sy > 4.0:
        return 1.0, 1.0
    return sx, sy


def build_som(
    screenshot_png: bytes,
    a11y_tree: Dict[str, Any],
    extra_elements: Optional[List[Dict[str, Any]]] = None,
    viewport_size: Optional[Tuple[float, float]] = None,
) -> Tuple[bytes, List[Dict[str, Any]]]:
    """SoM 标注：返回 (标注图 png, elements 列表)。

    Element boxes from DOM/a11y are CSS pixels. Screenshots may still be device
    pixels if scale='css' is unavailable — pass viewport_size so we scale boxes
    onto the image. Returned ``box`` is in image pixels (for UI overlay/click);
    ``box_css`` keeps CSS pixels for Playwright mouse / elementFromPoint.
    """
    raw_elements: List[Dict[str, Any]] = []
    _walk_a11y(a11y_tree, raw_elements)
    if extra_elements:
        raw_elements.extend(extra_elements)

    img = Image.open(io.BytesIO(screenshot_png)).convert("RGBA")
    draw = ImageDraw.Draw(img)
    img_w, img_h = img.size
    sx, sy = _som_image_scale(img_w, img_h, viewport_size)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None

    elements: List[Dict[str, Any]] = []
    for idx, el in enumerate(raw_elements, start=1):
        box = el.get("box") or {}
        try:
            x = float(box.get("x", 0) or 0)
            y = float(box.get("y", 0) or 0)
            w = float(box.get("width", 0) or 0)
            h = float(box.get("height", 0) or 0)
        except (TypeError, ValueError):
            continue
        if w <= 0 or h <= 0:
            continue
        # Image-space geometry for drawing / frontend hit-test.
        ix, iy, iw, ih = x * sx, y * sy, w * sx, h * sy
        # Clamp element box to image bounds for drawing.
        x0 = max(0, min(int(ix), img_w - 1))
        y0 = max(0, min(int(iy), img_h - 1))
        x1 = max(x0 + 1, min(int(ix + iw), img_w))
        y1 = max(y0 + 1, min(int(iy + ih), img_h))
        ref = f"[{idx}]"
        color = (0, 196, 255, 200)
        try:
            draw.rectangle([x0, y0, x1, y1], outline=color, width=2)
            # Tag above the box when possible; otherwise place inside top edge.
            tag_h = 14
            if y0 >= tag_h:
                ty0, ty1 = y0 - tag_h, y0
            else:
                ty0, ty1 = y0, min(y0 + tag_h, img_h)
            if ty1 <= ty0:
                ty1 = ty0 + 1
            tx0 = x0
            tx1 = min(x0 + 28, img_w)
            if tx1 <= tx0:
                tx1 = tx0 + 1
            draw.rectangle([tx0, ty0, tx1, ty1], fill=(245, 200, 66, 230))
            draw.text((tx0 + 2, ty0 + 1), ref, fill=(0, 0, 0), font=font)
        except Exception:
            # Skip drawing for malformed boxes; still expose the element for selection.
            pass
        item = {
            "ref": ref,
            "role": el.get("role", ""),
            "label": el.get("label", ""),
            "box": {"x": ix, "y": iy, "width": iw, "height": ih},
            "box_css": {"x": x, "y": y, "width": w, "height": h},
            "path": el.get("path", ""),
        }
        if sx != 1.0 or sy != 1.0:
            item["box_scale"] = {"x": sx, "y": sy}
        if "checked" in el and el["checked"] is not None:
            item["checked"] = el["checked"]
        if el.get("source"):
            item["source"] = el["source"]
        elements.append(item)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return buf.getvalue(), elements


def screenshot_hash(png: bytes) -> str:
    return hashlib.sha256(png).hexdigest()


def elements_to_json(elements: List[Dict[str, Any]]) -> str:
    return json.dumps(elements, ensure_ascii=False)
