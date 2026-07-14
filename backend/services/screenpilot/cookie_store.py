"""Playwright storage_state 持久化（按系统凭据，默认 24 小时有效）。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from models import ScreenCredential
from services.screenpilot.crypto_util import decrypt_secret, encrypt_secret

COOKIE_TTL_HOURS = 24


def _parse_saved_at(saved_at: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(saved_at.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def get_valid_storage_state(db: Session, system_id: str) -> Optional[Dict[str, Any]]:
    cred = (
        db.query(ScreenCredential)
        .filter(ScreenCredential.system_id == system_id)
        .first()
    )
    if not cred:
        return None
    extra = cred.extra or {}
    enc = extra.get("storage_state_enc")
    saved_at = extra.get("storage_state_saved_at")
    if not enc or not saved_at:
        return None
    saved = _parse_saved_at(saved_at)
    if not saved:
        return None
    if datetime.now(timezone.utc) - saved > timedelta(hours=COOKIE_TTL_HOURS):
        return None
    try:
        raw = decrypt_secret(enc)
        if not raw:
            return None
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


async def save_storage_state(db: Session, system_id: str, context: Any) -> None:
    cred = (
        db.query(ScreenCredential)
        .filter(ScreenCredential.system_id == system_id)
        .first()
    )
    if not cred or not context:
        return
    try:
        state = await context.storage_state()
        extra = dict(cred.extra or {})
        extra["storage_state_enc"] = encrypt_secret(
            json.dumps(state, ensure_ascii=False)
        )
        extra["storage_state_saved_at"] = datetime.now(timezone.utc).isoformat()
        cred.extra = extra
        flag_modified(cred, "extra")
        db.commit()
    except Exception as e:
        print(f"[cookie_store] 保存 storage_state 失败: {e}")


def clear_storage_state(db: Session, system_id: str) -> None:
    cred = (
        db.query(ScreenCredential)
        .filter(ScreenCredential.system_id == system_id)
        .first()
    )
    if not cred:
        return
    extra = dict(cred.extra or {})
    extra.pop("storage_state_enc", None)
    extra.pop("storage_state_saved_at", None)
    cred.extra = extra
    flag_modified(cred, "extra")
    db.commit()
