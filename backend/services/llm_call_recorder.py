"""Session-scoped LLM call recording for Playground debug drawer."""

from __future__ import annotations

import contextvars
import json
from typing import Any, Dict, List, Optional

from models import gen_uuid, now_utc

_recorder_ctx: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar(
    "llm_recorder_ctx", default=None
)
_call_source_ctx: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "llm_call_source", default=None
)


def bind_session(session_id: str, base_seq: int = 0, default_source: str = "react") -> None:
    _recorder_ctx.set(
        {
            "session_id": session_id,
            "base_seq": base_seq,
            "buffer": [],
            "default_source": default_source,
        }
    )


def unbind_session() -> None:
    _recorder_ctx.set(None)
    _call_source_ctx.set(None)


def set_call_source(source: Optional[str]) -> None:
    _call_source_ctx.set(source)


def get_active_context() -> Optional[Dict[str, Any]]:
    return _recorder_ctx.get()


def _safe_copy(obj: Any) -> Any:
    try:
        return json.loads(json.dumps(obj, ensure_ascii=False, default=str))
    except Exception:
        return str(obj)


def record_call(
    *,
    model_name: str,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    max_tokens: int,
    temperature: float,
    completion: Optional[Dict[str, Any]] = None,
    duration_ms: int = 0,
    source: Optional[str] = None,
    raw_error: Optional[str] = None,
) -> None:
    ctx = _recorder_ctx.get()
    if not ctx:
        return

    seq = ctx["base_seq"] + len(ctx["buffer"]) + 1
    effective_source = source or _call_source_ctx.get() or ctx.get("default_source", "react")

    output: Dict[str, Any] = {
        "content": None,
        "reasoning_content": None,
        "tool_calls": None,
        "usage": {},
        "raw_error": raw_error,
    }

    if completion and not raw_error:
        choices = completion.get("choices") or []
        msg = choices[0].get("message", {}) if choices else {}
        output["content"] = msg.get("content")
        output["reasoning_content"] = (
            completion.get("reasoning_content")
            or msg.get("reasoning_content")
            or msg.get("thinking")
        )
        output["tool_calls"] = msg.get("tool_calls")
        output["usage"] = completion.get("usage") or {}

    ctx["buffer"].append(
        {
            "call_id": gen_uuid(),
            "seq": seq,
            "created_at": now_utc().isoformat(),
            "source": effective_source,
            "model_name": model_name,
            "duration_ms": duration_ms,
            "input": {
                "messages": _safe_copy(messages),
                "tools": _safe_copy(tools) if tools else None,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            "output": output,
        }
    )


def flush_to_session(db, session) -> None:
    from sqlalchemy.orm.attributes import flag_modified

    ctx = _recorder_ctx.get()
    if not ctx or not ctx.get("buffer"):
        return

    existing = list(session.llm_calls or [])
    existing.extend(ctx["buffer"])
    session.llm_calls = existing
    flag_modified(session, "llm_calls")
    db.commit()
    ctx["buffer"] = []


class LlmRecordingScope:
    """Async context manager to bind/flush LLM call recording for a session chat."""

    def __init__(self, db, session, agent) -> None:
        self.db = db
        self.session = session
        self.agent = agent

    async def __aenter__(self):
        from models import AgentType

        default_source_map = {
            AgentType.COMPOSITE: "coordinator",
            AgentType.WORKFLOW: "workflow",
            AgentType.SINGLE: "react",
        }
        bind_session(
            self.session.session_id,
            base_seq=len(self.session.llm_calls or []),
            default_source=default_source_map.get(self.agent.agent_type, "react"),
        )
        return self

    async def __aexit__(self, exc_type, exc, tb):
        try:
            flush_to_session(self.db, self.session)
        except Exception as e:
            print(f"[llm_call_recorder] flush failed: {e}")
        unbind_session()
        return False
