import hashlib
import json
import os
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from models import UiAuditLog, gen_uuid, now_utc
from services.screenpilot.config import ARTIFACTS_DIR
from services.screenpilot.layers.perceive import screenshot_hash


def save_screenshot(screen_session_id: str, png: bytes, tag: str = "step") -> str:
    folder = os.path.join(ARTIFACTS_DIR, screen_session_id)
    os.makedirs(folder, exist_ok=True)
    fname = f"{tag}_{gen_uuid()[:8]}.png"
    path = os.path.join(folder, fname)
    with open(path, "wb") as f:
        f.write(png)
    return path


def _last_content_hash(db: Session, screen_session_id: str) -> str:
    row = (
        db.query(UiAuditLog)
        .filter(UiAuditLog.screen_session_id == screen_session_id)
        .order_by(UiAuditLog.created_at.desc())
        .first()
    )
    return (row.content_hash if row else "") or ""


def _compute_content_hash(
    *,
    prev_hash: str,
    action: str,
    risk_tier: str,
    payload: Dict[str, Any],
    shot_hash: str,
    verification: Dict[str, Any],
) -> str:
    body = json.dumps(
        {
            "prev_hash": prev_hash,
            "action": action,
            "risk_tier": risk_tier,
            "payload": payload,
            "screenshot_hash": shot_hash,
            "verification": verification,
        },
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(body.encode()).hexdigest()


def write_audit(
    db: Session,
    *,
    screen_session_id: str,
    vela_session_id: str = "",
    agent_id: str = "",
    action: str,
    risk_tier: str = "T0",
    payload: Optional[Dict[str, Any]] = None,
    screenshot_png: Optional[bytes] = None,
    verification: Optional[Dict[str, Any]] = None,
    approval_id: str = "",
) -> UiAuditLog:
    shot_path = ""
    shot_hash = ""
    if screenshot_png:
        shot_path = save_screenshot(screen_session_id, screenshot_png)
        shot_hash = screenshot_hash(screenshot_png)

    prev_hash = _last_content_hash(db, screen_session_id)
    payload = payload or {}
    verification = verification or {}
    content_hash = _compute_content_hash(
        prev_hash=prev_hash,
        action=action,
        risk_tier=risk_tier,
        payload=payload,
        shot_hash=shot_hash,
        verification=verification,
    )

    log = UiAuditLog(
        log_id=gen_uuid(),
        screen_session_id=screen_session_id,
        vela_session_id=vela_session_id,
        agent_id=agent_id,
        action=action,
        risk_tier=risk_tier,
        payload=payload,
        screenshot_path=shot_path,
        screenshot_hash=shot_hash,
        verification=verification,
        approval_id=approval_id,
        prev_hash=prev_hash,
        content_hash=content_hash,
        created_at=now_utc(),
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log
