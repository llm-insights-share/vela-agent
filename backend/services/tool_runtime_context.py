"""Contextvars for tool execution (JWT / caller / KB scope for ops & kb_search)."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, List, Optional

_api_token: ContextVar[Optional[str]] = ContextVar("vela_tool_api_token", default=None)
_caller_id: ContextVar[Optional[str]] = ContextVar("vela_tool_caller_id", default=None)
_allowed_kb_ids: ContextVar[Optional[List[str]]] = ContextVar(
    "vela_tool_allowed_kb_ids", default=None
)
_exclude_project_kbs: ContextVar[bool] = ContextVar(
    "vela_tool_exclude_project_kbs", default=True
)


def get_api_token() -> Optional[str]:
    return _api_token.get()


def get_caller_id() -> Optional[str]:
    return _caller_id.get()


def get_allowed_kb_ids() -> Optional[List[str]]:
    """None = unrestricted platform KBs (still may exclude project scope)."""
    return _allowed_kb_ids.get()


def get_exclude_project_kbs() -> bool:
    return _exclude_project_kbs.get()


@contextmanager
def tool_auth_context(
    token: Optional[str],
    caller_id: Optional[str] = None,
    *,
    allowed_kb_ids: Optional[List[str]] = None,
    exclude_project_kbs: bool = True,
) -> Iterator[None]:
    t = _api_token.set(token)
    c = _caller_id.set(caller_id)
    k = _allowed_kb_ids.set(allowed_kb_ids)
    e = _exclude_project_kbs.set(exclude_project_kbs)
    try:
        yield
    finally:
        _api_token.reset(t)
        _caller_id.reset(c)
        _allowed_kb_ids.reset(k)
        _exclude_project_kbs.reset(e)


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
