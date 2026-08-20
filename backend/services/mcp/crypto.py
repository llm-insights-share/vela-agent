from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken


def _fernet_key() -> bytes:
    raw = (
        os.getenv("MCP_OAUTH_KEY", "").strip()
        or os.getenv("SCREENPILOT_CREDENTIAL_KEY", "").strip()
    )
    if raw:
        try:
            if len(raw) == 44:
                return raw.encode()
        except Exception:
            pass
    digest = hashlib.sha256(b"vela-mcp-oauth-dev-key").digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_secret(plain: str) -> str:
    if not plain:
        return ""
    return Fernet(_fernet_key()).encrypt(plain.encode()).decode()


def decrypt_secret(cipher: str) -> str:
    if not cipher:
        return ""
    try:
        return Fernet(_fernet_key()).decrypt(cipher.encode()).decode()
    except InvalidToken:
        return ""
