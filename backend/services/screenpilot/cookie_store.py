"""Playwright storage_state 持久化（按系统凭证 KV，默认 24 小时有效）。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from models import ScreenCredential, gen_uuid, now_utc
from services.screenpilot.crypto_util import decrypt_secret, encrypt_secret

COOKIE_TTL_HOURS = 24
STORAGE_STATE_KEY = "__storage_state"
STORAGE_STATE_AT_KEY = "__storage_state_saved_at"


def _parse_saved_at(saved_at: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(saved_at.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _get_kv(db: Session, system_id: str, name: str) -> Optional[ScreenCredential]:
    return (
        db.query(ScreenCredential)
        .filter(
            ScreenCredential.system_id == system_id,
            ScreenCredential.name == name,
        )
        .first()
    )


def _upsert_kv(db: Session, system_id: str, name: str, plain: str) -> None:
    row = _get_kv(db, system_id, name)
    if row:
        row.value_enc = encrypt_secret(plain)
        row.updated_at = now_utc()
    else:
        db.add(
            ScreenCredential(
                credential_id=gen_uuid(),
                system_id=system_id,
                name=name,
                value_enc=encrypt_secret(plain),
                created_at=now_utc(),
                updated_at=now_utc(),
            )
        )


def get_valid_storage_state(db: Session, system_id: str) -> Optional[Dict[str, Any]]:
    state_row = _get_kv(db, system_id, STORAGE_STATE_KEY)
    at_row = _get_kv(db, system_id, STORAGE_STATE_AT_KEY)
    if not state_row or not at_row or not state_row.value_enc:
        return None
    saved_at = decrypt_secret(at_row.value_enc)
    saved = _parse_saved_at(saved_at)
    if not saved:
        return None
    if datetime.now(timezone.utc) - saved > timedelta(hours=COOKIE_TTL_HOURS):
        return None
    try:
        raw = decrypt_secret(state_row.value_enc)
        if not raw:
            return None
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


async def save_storage_state(db: Session, system_id: str, context: Any) -> None:
    if not context:
        return
    try:
        state = await context.storage_state()
        _upsert_kv(db, system_id, STORAGE_STATE_KEY, json.dumps(state, ensure_ascii=False))
        _upsert_kv(
            db,
            system_id,
            STORAGE_STATE_AT_KEY,
            datetime.now(timezone.utc).isoformat(),
        )
        db.commit()
    except Exception as e:
        print(f"[cookie_store] 保存 storage_state 失败: {e}")


def clear_storage_state(db: Session, system_id: str) -> None:
    for name in (STORAGE_STATE_KEY, STORAGE_STATE_AT_KEY):
        row = _get_kv(db, system_id, name)
        if row:
            db.delete(row)
    db.commit()
