"""MemoryProcessor: 派发会话蒸馏到 Letta（工具画像写 block + 转录交给记忆 agent）。"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from models import Agent, MemoryEpisode, Session as SessionModel
from services.memory.recorder import EventType


class MemoryProcessor:
    def __init__(self, db: Session):
        self.db = db

    async def process_session(self, session_id: str) -> Dict[str, Any]:
        session = self.db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
        if not session:
            raise ValueError("会话不存在")

        agent = self.db.query(Agent).filter(Agent.agent_id == session.agent_id).first()
        if not agent or not getattr(agent, "memory_enabled", False):
            return {"skipped": True, "reason": "memory_disabled"}

        from services.memory import letta_store

        if not letta_store.is_letta_enabled():
            return {"skipped": True, "reason": "letta_disabled"}

        user_id = session.caller_id or ""
        episodes = (
            self.db.query(MemoryEpisode)
            .filter(MemoryEpisode.session_id == session_id)
            .order_by(MemoryEpisode.created_at.asc())
            .all()
        )

        # 若尚无 SESSION_CLOSED 归档，用 session.messages 补一份
        closed = [e for e in episodes if e.event_type == EventType.SESSION_CLOSED]
        if not closed:
            from services.memory.recorder import MemoryRecorder

            recorder = MemoryRecorder(self.db)
            ep = recorder.archive_session(
                agent_id=agent.agent_id,
                session_id=session_id,
                user_id=user_id,
                messages=session.messages or [],
            )
            episodes.append(ep)

        # 确保 Letta 记忆 agent 存在
        letta_id = letta_store.ensure_memory_agent(self.db, agent.agent_id, user_id)
        if not letta_id:
            return {"skipped": True, "reason": "letta_agent_unavailable"}

        # 1) 工具画像：纯统计 → 写入 tool_profile block
        tool_stats = self._aggregate_tool_stats(episodes)
        profile_lines = []
        for tool_name, stats in sorted(tool_stats.items()):
            total = stats["success"] + stats["fail"]
            if total == 0:
                continue
            rate = stats["success"] / total
            profile_lines.append(
                f"- {tool_name}: 调用 {total} 次，成功 {stats['success']}，"
                f"失败 {stats['fail']}，成功率 {rate:.0%}"
            )
        tool_profile_updated = False
        if profile_lines:
            value = "工具调用画像（最近会话累计）\n" + "\n".join(profile_lines)
            updated = letta_store.update_block(
                self.db,
                agent.agent_id,
                "tool_profile",
                value,
                user_id=user_id,
            )
            tool_profile_updated = updated is not None

        # 2) 会话转录 → Letta 记忆 agent 自主蒸馏
        transcript = self._build_transcript(session, episodes)
        distill_result: Dict[str, Any] = {"ok": False, "skipped": True}
        if transcript.strip():
            distill_result = letta_store.distill_session(
                self.db,
                agent_id=agent.agent_id,
                user_id=user_id,
                session_id=session_id,
                transcript=transcript,
            )

        result = {
            "skipped": False,
            "letta_agent_id": letta_id,
            "tool_profile_updated": tool_profile_updated,
            "distill": distill_result,
        }
        # #region agent log
        try:
            import json as _j, time as _t
            with open("/Users/zhangjr/apps/LlmDemo/vibe-project/vela-agent/.cursor/debug-5cb12e.log", "a") as _f:
                _f.write(_j.dumps({"sessionId":"5cb12e","runId":"pre-fix","hypothesisId":"H1","location":"processor.py:process_session","message":"process finished","data":{"session_id":session_id,"user_id_prefix":(user_id or "")[:12],"transcript_len":len(transcript or ""),"distill_ok":bool((distill_result or {}).get("ok")),"distill_error":str((distill_result or {}).get("error") or "")[:200]},"timestamp":int(_t.time()*1000)},ensure_ascii=False)+"\n")
        except Exception:
            pass
        # #endregion
        return result

    @staticmethod
    def _aggregate_tool_stats(episodes: List[MemoryEpisode]) -> Dict[str, Dict[str, int]]:
        stats: Dict[str, Dict[str, int]] = defaultdict(lambda: {"success": 0, "fail": 0})
        for ep in episodes:
            if ep.event_type != EventType.TOOL_COMPLETED:
                continue
            payload = ep.payload or {}
            name = payload.get("tool_name") or "unknown"
            if payload.get("success"):
                stats[name]["success"] += 1
            else:
                stats[name]["fail"] += 1
        return dict(stats)

    @staticmethod
    def _build_transcript(session: SessionModel, episodes: List[MemoryEpisode]) -> str:
        for ep in reversed(episodes):
            if ep.event_type == EventType.SESSION_CLOSED:
                transcript = (ep.payload or {}).get("transcript") or []
                if transcript:
                    return MemoryProcessor._format_messages(transcript)
        return MemoryProcessor._format_messages(session.messages or [])

    @staticmethod
    def _format_messages(messages: list) -> str:
        lines = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content") or ""
            if role in ("user", "assistant") and content:
                lines.append(f"{role}: {str(content)[:2000]}")
        return "\n".join(lines[-40:])


async def process_session_background(session_id: str):
    """独立 DB session 的后台处理入口。"""
    from database import SessionLocal

    db = SessionLocal()
    try:
        processor = MemoryProcessor(db)
        result = await processor.process_session(session_id)
        print(f"[MemoryProcessor] session={session_id} result={result}")
        return result
    except Exception as e:
        print(f"[MemoryProcessor] session={session_id} error={e}")
        return {"error": str(e)}
    finally:
        db.close()
