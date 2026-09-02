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


def _is_placeholder_title(title: str) -> bool:
    """Empty or default UI label — not a real derived title."""
    return not (title or "").strip() or (title or "").strip() == DEFAULT_TITLE


def ensure_session_title(session: Any, *, persist: bool = True) -> str:
    """Set session.title from first user message when unset/placeholder. Returns the title.

    Does not persist DEFAULT_TITLE into the DB when there are no user messages —
    leave title empty so the frontend can show "新对话" as a display fallback.
    """
    current = (getattr(session, "title", None) or "").strip()
    messages = getattr(session, "messages", None) or []
    derived = title_from_messages(messages)

    if not _is_placeholder_title(current):
        return current

    if derived == DEFAULT_TITLE:
        # Keep empty so UI falls back to "新对话" without locking the title.
        session.title = ""
        return DEFAULT_TITLE

    session.title = derived
    return derived
