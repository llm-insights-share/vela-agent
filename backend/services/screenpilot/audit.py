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

    log = UiAuditLog(
        log_id=gen_uuid(),
        screen_session_id=screen_session_id,
        vela_session_id=vela_session_id,
        agent_id=agent_id,
        action=action,
        risk_tier=risk_tier,
        payload=payload or {},
        screenshot_path=shot_path,
        screenshot_hash=shot_hash,
        verification=verification or {},
        approval_id=approval_id,
        created_at=now_utc(),
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log
