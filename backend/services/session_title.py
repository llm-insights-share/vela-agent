"""Derive a short human-readable title from session messages."""
from __future__ import annotations

from typing import Any, List, Optional

DEFAULT_TITLE = "新对话"
MAX_TITLE_LEN = 40


def title_from_text(text: str, *, max_len: int = MAX_TITLE_LEN) -> str:
    cleaned = " ".join((text or "").split()).strip()
    if not cleaned:
        return DEFAULT_TITLE
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1] + "…"


def title_from_messages(messages: Optional[List[Any]], *, max_len: int = MAX_TITLE_LEN) -> str:
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if content is None:
            continue
        if not isinstance(content, str):
            content = str(content)
        return title_from_text(content, max_len=max_len)
    return DEFAULT_TITLE


def ensure_session_title(session: Any, *, persist: bool = True) -> str:
    """Set session.title from first user message when empty. Returns the title."""
    current = (getattr(session, "title", None) or "").strip()
    if current:
        return current
    derived = title_from_messages(getattr(session, "messages", None) or [])
    session.title = derived
    return derived
