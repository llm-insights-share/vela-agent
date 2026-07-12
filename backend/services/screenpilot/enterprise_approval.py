"""T3 动作路由至企业 OA 审批流（可选 webhook）。"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any, Dict, Optional

import httpx

from models import HITLApproval
from services.screenpilot.config import (
    SCREENPILOT_ENTERPRISE_APPROVAL_SECRET,
    SCREENPILOT_ENTERPRISE_APPROVAL_URL,
    SCREENPILOT_ENTERPRISE_CALLBACK_BASE,
)

logger = logging.getLogger(__name__)


def _sign_payload(body: str) -> str:
    secret = SCREENPILOT_ENTERPRISE_APPROVAL_SECRET or "screenpilot"
    return hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()


def enterprise_approval_enabled() -> bool:
    return bool(SCREENPILOT_ENTERPRISE_APPROVAL_URL.strip())


async def submit_enterprise_approval(
    approval: HITLApproval,
    *,
    preview_payload: Dict[str, Any],
    risk_tier: str,
) -> Dict[str, Any]:
    """向企业 OA 审批 API 提交 T3 工单；失败时仍保留平台内 HITL。"""
    if not enterprise_approval_enabled():
        return {"submitted": False, "reason": "enterprise_url_not_configured"}

    callback_url = ""
    if SCREENPILOT_ENTERPRISE_CALLBACK_BASE:
        callback_url = (
            f"{SCREENPILOT_ENTERPRISE_CALLBACK_BASE.rstrip('/')}"
            f"/api/v1/screenpilot/enterprise/callback"
        )

    body = {
        "approval_id": approval.approval_id,
        "session_id": approval.session_id,
        "agent_id": approval.agent_id,
        "tool_name": approval.tool_name,
        "risk_tier": risk_tier,
        "preview": preview_payload,
        "callback_url": callback_url,
        "title": f"ScreenPilot {risk_tier} 动作审批",
        "description": preview_payload.get("target_label") or preview_payload.get("action", ""),
    }
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True)
    headers = {
        "Content-Type": "application/json",
        "X-ScreenPilot-Signature": _sign_payload(raw),
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                SCREENPILOT_ENTERPRISE_APPROVAL_URL,
                content=raw.encode("utf-8"),
                headers=headers,
            )
        if resp.status_code >= 400:
            logger.warning("企业审批提交失败 status=%s body=%s", resp.status_code, resp.text[:500])
            return {"submitted": False, "reason": f"http_{resp.status_code}", "detail": resp.text[:200]}

        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        ticket_id = data.get("ticket_id") or data.get("id") or ""
        return {"submitted": True, "ticket_id": ticket_id, "enterprise_response": data}
    except Exception as e:
        logger.error("企业审批提交异常: %s", e, exc_info=True)
        return {"submitted": False, "reason": "exception", "detail": str(e)}


def verify_callback_signature(body: str, signature: str) -> bool:
    if not signature:
        return False
    expected = _sign_payload(body)
    return hmac.compare_digest(expected, signature)
