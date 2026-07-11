"""SelfRetriever: 按触发条件从 MemoryGateway 召回并格式化为 prompt 注入文本。"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from services.memory.gateway import MemoryGateway, MemoryQuery


class SelfRetriever:
    def __init__(self, db: Session):
        self.db = db
        self.gateway = MemoryGateway(db)

    def on_session_start(
        self,
        agent_id: str,
        user_id: str = "",
        top_k: int = 5,
    ) -> str:
        records = self.gateway.read(
            MemoryQuery(
                agent_id=agent_id,
                user_id=user_id or None,
                memory_types=["user_pref", "task_summary"],
                top_k=top_k,
            )
        )
        # 若按 user 过滤为空，回退到 agent 级（caller_id 可能为空）
        if not records and user_id:
            records = self.gateway.read(
                MemoryQuery(
                    agent_id=agent_id,
                    memory_types=["user_pref", "task_summary"],
                    top_k=top_k,
                )
            )
        return self._format(records, title="相关长期记忆（会话预加载）")

    def before_tool_invoke(
        self,
        agent_id: str,
        tool_names: Optional[List[str]] = None,
        top_k: int = 3,
    ) -> str:
        records = self.gateway.read(
            MemoryQuery(
                agent_id=agent_id,
                memory_types=["tool_profile"],
                top_k=max(top_k, len(tool_names or []) or 3),
            )
        )
        if tool_names:
            filtered = []
            for r in records:
                name = (r.meta or {}).get("tool_name")
                if name in tool_names:
                    filtered.append(r)
            if filtered:
                records = filtered
        return self._format(records, title="工具能力与成功模式")

    def for_entity_context(self, agent_id: str, keyword: str = "", top_k: int = 8) -> str:
        records = self.gateway.read(
            MemoryQuery(
                agent_id=agent_id,
                memory_types=["experience", "task_summary"],
                keyword=keyword or None,
                top_k=top_k,
            )
        )
        return self._format(records, title="历史结论与经验摘要")

    @staticmethod
    def _format(records, title: str) -> str:
        if not records:
            return ""
        lines = [f"\n\n## {title}"]
        type_labels = {
            "user_pref": "用户偏好",
            "task_summary": "任务摘要",
            "experience": "经验",
            "tool_profile": "工具画像",
            "provenance": "溯源",
        }
        for r in records:
            label = type_labels.get(r.memory_type, r.memory_type)
            lines.append(f"- [{label}] {r.content}")
        return "\n".join(lines)
