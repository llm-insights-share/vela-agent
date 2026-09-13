"""Contextvars for tool execution (JWT / caller for ops CLI tools)."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

_api_token: ContextVar[Optional[str]] = ContextVar("vela_tool_api_token", default=None)
_caller_id: ContextVar[Optional[str]] = ContextVar("vela_tool_caller_id", default=None)


def get_api_token() -> Optional[str]:
    return _api_token.get()


def get_caller_id() -> Optional[str]:
    return _caller_id.get()


@contextmanager
def tool_auth_context(token: Optional[str], caller_id: Optional[str] = None) -> Iterator[None]:
    t = _api_token.set(token)
    c = _caller_id.set(caller_id)
    try:
        yield
    finally:
        _api_token.reset(t)
        _caller_id.reset(c)


def mint_token_for_caller(db, caller_id: str) -> Optional[str]:
    """Mint a JWT for session.caller_id (user_id or username)."""
    if not caller_id:
        return None
    from models import User
    from security import create_access_token

    user = db.query(User).filter(User.user_id == caller_id).first()
    if not user:
        user = db.query(User).filter(User.username == caller_id).first()
    if not user or not user.is_active:
        return None
    return create_access_token(user.username, {"roles": user.roles or ""})
