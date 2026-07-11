"""MemoryRecorder: 无条件捕获运行时事件写入 L1 Episode。"""
from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from models import MemoryEpisode, gen_uuid, now_utc


class EventType:
    MESSAGE_TURN = "MESSAGE_TURN"
    TOOL_COMPLETED = "TOOL_COMPLETED"
    EXCEPTION_RAISED = "EXCEPTION_RAISED"
    SESSION_CLOSED = "SESSION_CLOSED"
    TASK_PLANNED = "TASK_PLANNED"
    USER_CORRECTED = "USER_CORRECTED"


class MemoryRecorder:
    def __init__(self, db: Session):
        self.db = db

    def on_event(
        self,
        event_type: str,
        *,
        agent_id: str,
        session_id: str = "",
        user_id: str = "",
        payload: Optional[Dict[str, Any]] = None,
    ) -> MemoryEpisode:
        episode = MemoryEpisode(
            episode_id=gen_uuid(),
            agent_id=agent_id,
            session_id=session_id or "",
            user_id=user_id or "",
            event_type=event_type,
            payload=payload or {},
            created_at=now_utc(),
        )
        self.db.add(episode)
        self.db.commit()
        self.db.refresh(episode)
        return episode

    def record_message_turn(
        self,
        agent_id: str,
        session_id: str,
        user_id: str,
        user_message: str,
        assistant_message: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ) -> MemoryEpisode:
        payload = {
            "user_message": user_message,
            "assistant_message": assistant_message,
            **(extra or {}),
        }
        return self.on_event(
            EventType.MESSAGE_TURN,
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
            payload=payload,
        )

    def record_tool_completed(
        self,
        agent_id: str,
        session_id: str,
        user_id: str,
        tool_name: str,
        success: bool,
        args: Optional[Dict[str, Any]] = None,
        result_preview: str = "",
        error: str = "",
    ) -> MemoryEpisode:
        return self.on_event(
            EventType.TOOL_COMPLETED,
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
            payload={
                "tool_name": tool_name,
                "success": success,
                "args": args or {},
                "result_preview": (result_preview or "")[:500],
                "error": error or "",
            },
        )

    def record_exception(
        self,
        agent_id: str,
        session_id: str,
        user_id: str,
        error: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> MemoryEpisode:
        return self.on_event(
            EventType.EXCEPTION_RAISED,
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
            payload={"error": error, "context": context or {}},
        )

    def archive_session(
        self,
        agent_id: str,
        session_id: str,
        user_id: str,
        messages: list,
    ) -> MemoryEpisode:
        return self.on_event(
            EventType.SESSION_CLOSED,
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
            payload={
                "message_count": len(messages or []),
                "transcript": messages or [],
            },
        )
