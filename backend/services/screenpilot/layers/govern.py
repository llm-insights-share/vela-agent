import asyncio
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from services.screenpilot.layers.ground import find_element_by_ref


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
    for domain in allowed_domains:
        d = domain.strip().lower()
        if not d:
            continue
        if host == d or host.endswith("." + d):
            return True
    return False


async def verify_action(page, action: str, before_url: str, before_shot: bytes) -> Dict[str, Any]:
    await asyncio.sleep(0.3)
    after_url = page.url
    after_shot = await page.screenshot(type="png", full_page=False)
    changed = after_url != before_url or after_shot != before_shot
    return {
        "ok": changed or action in ("type", "select", "scroll", "wait"),
        "before_url": before_url,
        "after_url": after_url,
        "url_changed": after_url != before_url,
    }
