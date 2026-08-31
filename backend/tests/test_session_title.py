"""Tests for session title derivation."""
from types import SimpleNamespace

from services.session_title import (
    DEFAULT_TITLE,
    ensure_session_title,
    title_from_messages,
    title_from_text,
)


def test_title_from_text_truncates():
    long = "这是一段很长很长的用户消息内容用来测试截断行为是否正确"
    t = title_from_text(long, max_len=10)
    assert t.endswith("…")
    assert len(t) == 10


def test_title_from_messages_first_user():
    msgs = [
        {"role": "assistant", "content": "hi"},
        {"role": "user", "content": "查询天气"},
        {"role": "user", "content": "第二句"},
    ]
    assert title_from_messages(msgs) == "查询天气"


def test_title_from_messages_empty():
    assert title_from_messages([]) == DEFAULT_TITLE
    assert title_from_messages(None) == DEFAULT_TITLE


def test_ensure_session_title_backfill():
    session = SimpleNamespace(title="", messages=[{"role": "user", "content": "hello world"}])
    assert ensure_session_title(session) == "hello world"
    assert session.title == "hello world"
    session.title = "已有标题"
    assert ensure_session_title(session) == "已有标题"
