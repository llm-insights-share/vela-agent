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
            }
        )
    children = node.get("children") or []
    for i, child in enumerate(children):
        _walk_a11y(child, out, f"{path}/{role}[{i}]")


async def capture_page_state(page) -> Tuple[bytes, Dict[str, Any], str]:
    """截图 + 无障碍树，返回 (png_bytes, a11y_tree, url)。"""
    url = page.url
    screenshot = await page.screenshot(type="png", full_page=False)
    try:
        tree = await page.accessibility.snapshot(interesting_only=True)
    except Exception:
        tree = {}
    return screenshot, tree or {}, url


def build_som(
    screenshot_png: bytes, a11y_tree: Dict[str, Any]
) -> Tuple[bytes, List[Dict[str, Any]]]:
    """SoM 标注：返回 (标注图 png, elements 列表)。"""
    raw_elements: List[Dict[str, Any]] = []
    _walk_a11y(a11y_tree, raw_elements)

    img = Image.open(io.BytesIO(screenshot_png)).convert("RGBA")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None

    elements: List[Dict[str, Any]] = []
    for idx, el in enumerate(raw_elements, start=1):
        box = el["box"]
        x, y, w, h = box["x"], box["y"], box["width"], box["height"]
        if w <= 0 or h <= 0:
            continue
        ref = f"[{idx}]"
        color = (0, 196, 255, 200)
        draw.rectangle([x, y, x + w, y + h], outline=color, width=2)
        tag = ref
        draw.rectangle([x, max(0, y - 14), x + 28, y], fill=(245, 200, 66, 230))
        draw.text((x + 2, max(0, y - 12)), tag, fill=(0, 0, 0), font=font)
        elements.append(
            {
                "ref": ref,
                "role": el["role"],
                "label": el["label"],
                "box": box,
                "path": el.get("path", ""),
            }
        )

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return buf.getvalue(), elements


def screenshot_hash(png: bytes) -> str:
    return hashlib.sha256(png).hexdigest()


def elements_to_json(elements: List[Dict[str, Any]]) -> str:
    return json.dumps(elements, ensure_ascii=False)
