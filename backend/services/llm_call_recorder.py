"""Session-scoped LLM call recording for Playground debug drawer + UI turn cards."""

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

_PREVIEW_LIMIT = 1200
_ARG_PREVIEW_LIMIT = 800
_TOOL_RESULT_PREVIEW = 800


def bind_session(session_id: str, base_seq: int = 0, default_source: str = "react") -> None:
    _recorder_ctx.set(
        {
            "session_id": session_id,
            "base_seq": base_seq,
            "buffer": [],
            "turns": [],
            "default_source": default_source,
            "prev_message_count": 0,
        }
    )


def unbind_session() -> None:
    _recorder_ctx.set(None)
    _call_source_ctx.set(None)


def set_call_source(source: Optional[str]) -> None:
    _call_source_ctx.set(source)


def get_active_context() -> Optional[Dict[str, Any]]:
    return _recorder_ctx.get()


def get_llm_turns() -> List[Dict[str, Any]]:
    ctx = _recorder_ctx.get()
    if not ctx:
        return []
    return list(ctx.get("turns") or [])


def _safe_copy(obj: Any) -> Any:
    try:
        return json.loads(json.dumps(obj, ensure_ascii=False, default=str))
    except Exception:
        return str(obj)


def _truncate(text: Any, limit: int = _PREVIEW_LIMIT) -> str:
    if text is None:
        return ""
    s = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False, default=str)
    if len(s) <= limit:
        return s
    return s[:limit] + "…"


def _preview_message(msg: Dict[str, Any]) -> Dict[str, Any]:
    role = msg.get("role") or "unknown"
    preview: Dict[str, Any] = {"role": role}
    if role == "tool":
        preview["tool_call_id"] = msg.get("tool_call_id")
        preview["name"] = msg.get("name")
        preview["content"] = _truncate(msg.get("content"), _TOOL_RESULT_PREVIEW)
        return preview
    content = msg.get("content")
    if content is not None:
        preview["content"] = _truncate(content, _PREVIEW_LIMIT)
    tool_calls = msg.get("tool_calls")
    if tool_calls:
        preview["tool_calls"] = [
            {
                "id": tc.get("id"),
                "name": (tc.get("function") or {}).get("name") or tc.get("name"),
                "arguments": _truncate(
                    (tc.get("function") or {}).get("arguments") or "",
                    _ARG_PREVIEW_LIMIT,
                ),
            }
            for tc in tool_calls
        ]
    return preview


def build_input_preview(
    messages: List[Dict[str, Any]],
    *,
    prev_count: int = 0,
    tools: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build display input: system folded + delta messages since previous call."""
    msgs = messages or []
    has_system = any((m.get("role") == "system") for m in msgs)
    if prev_count <= 0:
        # First call: show last user (+ trailing non-system) rather than full history
        delta: List[Dict[str, Any]] = []
        for m in reversed(msgs):
            if m.get("role") == "system":
                continue
            delta.insert(0, m)
            if m.get("role") == "user":
                break
        if not delta and msgs:
            delta = [m for m in msgs if m.get("role") != "system"][-3:]
    else:
        delta = msgs[prev_count:]
        if not delta:
            # message list replaced/truncated — fall back to last non-system
            delta = [m for m in msgs if m.get("role") != "system"][-2:]

    previews = [_preview_message(m) for m in delta if isinstance(m, dict)]
    summary_parts: List[str] = []
    if has_system:
        summary_parts.append("系统提示已注入")
    for p in previews:
        role = p.get("role")
        if role == "user":
            summary_parts.append(f"用户: {_truncate(p.get('content'), 80)}")
        elif role == "tool":
            summary_parts.append(f"工具结果: {_truncate(p.get('content'), 60)}")
        elif role == "assistant":
            if p.get("tool_calls"):
                names = ", ".join(tc.get("name") or "?" for tc in p["tool_calls"])
                summary_parts.append(f"上轮工具调用: {names}")
            elif p.get("content"):
                summary_parts.append(f"助手: {_truncate(p.get('content'), 60)}")
    return {
        "messages": previews,
        "has_system": has_system,
        "tools_count": len(tools) if tools else 0,
        "summary": " · ".join(summary_parts) if summary_parts else f"{len(previews)} 条消息",
    }


def _normalize_tool_calls(tool_calls: Any) -> Optional[List[Dict[str, Any]]]:
    if not tool_calls:
        return None
    out = []
    for tc in tool_calls:
        fn = tc.get("function") or {}
        out.append(
            {
                "id": tc.get("id"),
                "name": fn.get("name") or tc.get("name"),
                "arguments": _truncate(fn.get("arguments") or "", _ARG_PREVIEW_LIMIT),
            }
        )
    return out


def build_turn_from_record(record: Dict[str, Any], *, prev_message_count: int = 0) -> Dict[str, Any]:
    inp = record.get("input") or {}
    out = record.get("output") or {}
    messages = inp.get("messages") or []
    tools = inp.get("tools")
    thinking = out.get("reasoning_content")
    if isinstance(thinking, str):
        thinking = thinking.strip() or None
    else:
        thinking = None
    content = out.get("content")
    if content is not None and not isinstance(content, str):
        content = _truncate(content, _PREVIEW_LIMIT)
    return {
        "turn_id": record.get("call_id") or gen_uuid(),
        "seq": record.get("seq"),
        "source": record.get("source") or "react",
        "model_name": record.get("model_name") or "",
        "duration_ms": record.get("duration_ms") or 0,
        "created_at": record.get("created_at"),
        "input": build_input_preview(messages, prev_count=prev_message_count, tools=tools),
        "thinking": thinking,
        "response": {
            "content": content,
            "tool_calls": _normalize_tool_calls(out.get("tool_calls")),
            "raw_error": out.get("raw_error"),
        },
        "tool_results": [],
    }


def turns_from_llm_calls(llm_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Rebuild display turns from persisted llm_calls (history fallback)."""
    turns: List[Dict[str, Any]] = []
    prev_count = 0
    for rec in llm_calls or []:
        messages = ((rec.get("input") or {}).get("messages")) or []
        turn = build_turn_from_record(rec, prev_message_count=prev_count)
        turns.append(turn)
        prev_count = len(messages)
    return turns


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
) -> Optional[Dict[str, Any]]:
    ctx = _recorder_ctx.get()
    if not ctx:
        return None

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

    record = {
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
    prev_count = int(ctx.get("prev_message_count") or 0)
    turn = build_turn_from_record(record, prev_message_count=prev_count)
    ctx["buffer"].append(record)
    ctx["turns"].append(turn)
    ctx["prev_message_count"] = len(messages or [])
    return record


def attach_tool_results(
    tool_results: List[Dict[str, Any]],
    *,
    turn_id: Optional[str] = None,
) -> None:
    """Attach tool execution results to the matching (or latest) turn card."""
    ctx = _recorder_ctx.get()
    if not ctx or not ctx.get("turns"):
        return
    turns = ctx["turns"]
    target = None
    if turn_id:
        for t in reversed(turns):
            if t.get("turn_id") == turn_id:
                target = t
                break
    if target is None:
        target = turns[-1]
    cleaned = []
    for r in tool_results or []:
        item = {
            "tool_call_id": r.get("tool_call_id"),
            "name": r.get("name") or "unknown",
            "content_preview": _truncate(r.get("content") or r.get("content_preview") or "", _TOOL_RESULT_PREVIEW),
            "ok": bool(r.get("ok", True)),
        }
        if r.get("code_exec"):
            item["code_exec"] = r["code_exec"]
        if r.get("tool_search"):
            item["tool_search"] = r["tool_search"]
        cleaned.append(item)
    existing = list(target.get("tool_results") or [])
    existing.extend(cleaned)
    target["tool_results"] = existing


def flush_turns_preview(db, session) -> None:
    """Mid-run: expose current turns via pending_context for session polling."""
    from sqlalchemy.orm.attributes import flag_modified

    ctx = _recorder_ctx.get()
    if not ctx:
        return
    turns = list(ctx.get("turns") or [])
    pending = dict(session.pending_context or {})
    pending["llm_turns"] = turns
    session.pending_context = pending
    flag_modified(session, "pending_context")
    try:
        db.commit()
    except Exception as e:
        print(f"[llm_call_recorder] flush_turns_preview failed: {e}")
        try:
            db.rollback()
        except Exception:
            pass


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
        # Clear stale mid-run preview
        try:
            pending = dict(self.session.pending_context or {})
            if "llm_turns" in pending:
                pending.pop("llm_turns", None)
                self.session.pending_context = pending
                from sqlalchemy.orm.attributes import flag_modified

                flag_modified(self.session, "pending_context")
                self.db.commit()
        except Exception:
            pass
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
