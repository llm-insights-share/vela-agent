import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken


def _fernet_key() -> bytes:
    raw = os.getenv("SCREENPILOT_CREDENTIAL_KEY", "").strip()
    if raw:
        try:
            return raw.encode() if isinstance(raw, str) else raw
        except Exception:
            pass
    digest = hashlib.sha256(b"vela-screenpilot-dev-key").digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_secret(plain: str) -> str:
    if not plain:
        return ""
    f = Fernet(_fernet_key())
    return f.encrypt(plain.encode()).decode()


def decrypt_secret(cipher: str) -> str:
    if not cipher:
        return ""
    f = Fernet(_fernet_key())
    try:
        return f.decrypt(cipher.encode()).decode()
    except InvalidToken:
        return ""
