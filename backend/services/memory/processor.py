"""MemoryProcessor: 从 L1 情景蒸馏 L2 语义记忆并自动提交。"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from models import Agent, MemoryEpisode, ModelProvider, ModelService, Session as SessionModel
from services.memory.gateway import MemoryCandidate, MemoryGateway
from services.memory.recorder import EventType


EXTRACT_PROMPT = """你是记忆蒸馏助手。根据以下会话转录，提取可复用的长期记忆。
只输出 JSON，不要 markdown 代码块，格式如下：
{
  "preferences": ["用户偏好1", "..."],
  "task_summary": "本次任务目标与结果的简短摘要，无则空字符串",
  "experiences": ["可复用的问题-方案-结论", "..."]
}

规则：
- preferences 只收录稳定偏好（如时间安排、输出格式、沟通风格），忽略一次性指令
- experiences 只收录有复用价值的结论，不要流水账
- 若无明显内容，对应字段用空数组或空字符串

会话转录：
"""


class MemoryProcessor:
    def __init__(self, db: Session):
        self.db = db
        self.gateway = MemoryGateway(db)

    async def process_session(self, session_id: str) -> Dict[str, Any]:
        session = self.db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
        if not session:
            raise ValueError("会话不存在")

        agent = self.db.query(Agent).filter(Agent.agent_id == session.agent_id).first()
        if not agent or not getattr(agent, "memory_enabled", False):
            return {"skipped": True, "reason": "memory_disabled"}

        user_id = session.caller_id or ""
        episodes = (
            self.db.query(MemoryEpisode)
            .filter(MemoryEpisode.session_id == session_id)
            .order_by(MemoryEpisode.created_at.asc())
            .all()
        )
        episode_ids = [e.episode_id for e in episodes]

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
            episode_ids.append(ep.episode_id)
            episodes.append(ep)

        written: List[str] = []

        # 1) 工具画像：纯统计
        tool_stats = self._aggregate_tool_stats(episodes)
        for tool_name, stats in tool_stats.items():
            total = stats["success"] + stats["fail"]
            if total == 0:
                continue
            rate = stats["success"] / total
            content = (
                f"工具 {tool_name}: 调用 {total} 次，成功 {stats['success']}，"
                f"失败 {stats['fail']}，成功率 {rate:.0%}"
            )
            rec = self.gateway.write(
                MemoryCandidate(
                    agent_id=agent.agent_id,
                    user_id=user_id,
                    memory_type="tool_profile",
                    content=content,
                    metadata={"tool_name": tool_name, "stats": stats, "session_id": session_id},
                    source_episode_ids=episode_ids,
                    supersede_key="tool_name",
                    created_by="system",
                )
            )
            written.append(rec.record_id)
            self._write_provenance(agent.agent_id, user_id, rec.record_id, episode_ids, session_id)

        # 2) LLM 蒸馏偏好 / 摘要 / 经验
        transcript = self._build_transcript(session, episodes)
        if transcript.strip():
            extracted = await self._llm_extract(agent, transcript)
            for pref in extracted.get("preferences") or []:
                pref = (pref or "").strip()
                if not pref:
                    continue
                rec = self.gateway.write(
                    MemoryCandidate(
                        agent_id=agent.agent_id,
                        user_id=user_id,
                        memory_type="user_pref",
                        content=pref,
                        metadata={"session_id": session_id, "pref_key": pref[:64]},
                        source_episode_ids=episode_ids,
                        supersede_key="pref_key",
                        created_by="system",
                    )
                )
                written.append(rec.record_id)
                self._write_provenance(agent.agent_id, user_id, rec.record_id, episode_ids, session_id)

            summary = (extracted.get("task_summary") or "").strip()
            if summary:
                rec = self.gateway.write(
                    MemoryCandidate(
                        agent_id=agent.agent_id,
                        user_id=user_id,
                        memory_type="task_summary",
                        content=summary,
                        metadata={"session_id": session_id},
                        source_episode_ids=episode_ids,
                        supersede_key="session_id",
                        created_by="system",
                    )
                )
                written.append(rec.record_id)
                self._write_provenance(agent.agent_id, user_id, rec.record_id, episode_ids, session_id)

            for exp in extracted.get("experiences") or []:
                exp = (exp or "").strip()
                if not exp:
                    continue
                rec = self.gateway.write(
                    MemoryCandidate(
                        agent_id=agent.agent_id,
                        user_id=user_id,
                        memory_type="experience",
                        content=exp,
                        metadata={"session_id": session_id},
                        source_episode_ids=episode_ids,
                        created_by="system",
                    )
                )
                written.append(rec.record_id)
                self._write_provenance(agent.agent_id, user_id, rec.record_id, episode_ids, session_id)

        return {"skipped": False, "written_count": len(written), "record_ids": written}

    def _write_provenance(
        self,
        agent_id: str,
        user_id: str,
        target_record_id: str,
        episode_ids: List[str],
        session_id: str,
    ):
        self.gateway.write(
            MemoryCandidate(
                agent_id=agent_id,
                user_id=user_id,
                memory_type="provenance",
                content=f"记录 {target_record_id} 来源于会话 {session_id} 的 {len(episode_ids)} 条情景事件",
                metadata={
                    "target_record_id": target_record_id,
                    "session_id": session_id,
                },
                source_episode_ids=episode_ids,
                supersede_key="target_record_id",
                created_by="system",
            )
        )

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
                lines.append(f"{role}: {content[:2000]}")
        return "\n".join(lines[-40:])

    async def _llm_extract(self, agent: Agent, transcript: str) -> Dict[str, Any]:
        model_svc = self.db.query(ModelService).filter(
            ModelService.model_service_id == agent.model_service_id
        ).first()
        if not model_svc:
            return {}
        provider = self.db.query(ModelProvider).filter(
            ModelProvider.provider_id == model_svc.provider_id
        ).first()
        if not provider:
            return {}

        try:
            from services.model_provider import model_provider_service

            completion = await model_provider_service.chat_completion(
                provider=provider,
                model_name=model_svc.model_name,
                messages=[
                    {"role": "system", "content": "你只输出合法 JSON。"},
                    {"role": "user", "content": EXTRACT_PROMPT + transcript[:12000]},
                ],
                max_tokens=1024,
                timeout_seconds=60,
            )
            choices = completion.get("choices") or []
            if not choices:
                return {}
            text = (choices[0].get("message") or {}).get("content") or ""
            return self._parse_json(text)
        except Exception as e:
            print(f"[MemoryProcessor] LLM 蒸馏失败: {e}")
            return {}

    @staticmethod
    def _parse_json(text: str) -> Dict[str, Any]:
        text = (text or "").strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if m:
            try:
                return json.loads(m.group(1).strip())
            except json.JSONDecodeError:
                pass
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        return {}


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
