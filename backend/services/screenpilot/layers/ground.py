from typing import Any, Dict, List, Optional


def find_element_by_ref(elements: List[Dict[str, Any]], target_ref: str) -> Optional[Dict[str, Any]]:
    ref = (target_ref or "").strip()
    if not ref.startswith("["):
        ref = f"[{ref.strip('[]')}]"
    for el in elements:
        if el.get("ref") == ref:
            return el
    return None


def build_selector_fingerprint(element: Dict[str, Any]) -> Dict[str, Any]:
    """为技能重放预留的多候选指纹（P1 扩展）。"""
    return {
        "ref": element.get("ref"),
        "role": element.get("role"),
        "label": element.get("label"),
        "box": element.get("box"),
        "path": element.get("path"),
    }
