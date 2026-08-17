"""SelfRetriever: 从 Letta 读 core blocks + 按消息语义召回 archival passages。"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session


BLOCK_LABELS_ZH = {
    "user_pref": "用户偏好",
    "task_context": "任务上下文",
    "tool_profile": "工具画像",
}


class SelfRetriever:
    def __init__(self, db: Session):
        self.db = db

    def on_session_start(
        self,
        agent_id: str,
        user_id: str = "",
        top_k: int = 5,
    ) -> str:
        """注入核心记忆 blocks（常驻上下文）。"""
        from services.memory import letta_store

        if not letta_store.is_letta_enabled():
            return ""
        blocks = letta_store.read_blocks(self.db, agent_id, user_id)
        if not blocks and user_id:
            blocks = letta_store.read_blocks(self.db, agent_id, "")
        return self._format_blocks(blocks, title="核心记忆（会话预加载）")

    def before_tool_invoke(
        self,
        agent_id: str,
        tool_names: Optional[List[str]] = None,
        top_k: int = 3,
        user_id: str = "",
    ) -> str:
        """工具画像来自 tool_profile block（已在 on_session_start 注入时可省略）。"""
        from services.memory import letta_store

        if not letta_store.is_letta_enabled():
            return ""
        blocks = letta_store.read_blocks(self.db, agent_id, user_id)
        tool_blocks = [b for b in blocks if b.get("label") == "tool_profile" and (b.get("value") or "").strip()]
        if not tool_blocks:
            return ""
        return self._format_blocks(tool_blocks, title="工具能力与成功模式")

    def recall_for_message(
        self,
        agent_id: str,
        user_id: str,
        message: str,
        top_k: int = 5,
    ) -> str:
        """按当前用户消息做 archival 语义召回。"""
        from services.memory import letta_store

        if not letta_store.is_letta_enabled():
            return ""
        text = (message or "").strip()
        if not text:
            return ""
        query = text[:500]

        # 关键词回退优先（不依赖 embedding，避免与 llm-gateway 同进程死锁）
        fallback = self._fallback_keyword_passages(
            agent_id=agent_id,
            user_id=user_id,
            query=query,
            top_k=top_k,
        )
        # 关键词已够用时跳过语义检索，减少 Letta→gateway 往返与超时
        semantic: list = []
        if len(fallback) < top_k:
            semantic = letta_store.search_passages(
                self.db,
                agent_id=agent_id,
                query=query,
                user_id=user_id,
                top_k=top_k,
            )
            if not semantic and user_id:
                semantic = letta_store.search_passages(
                    self.db,
                    agent_id=agent_id,
                    query=query,
                    user_id="",
                    top_k=top_k,
                )

        merged: list = []
        seen: set = set()
        for p in (fallback or []) + (semantic or []):
            pid = p.get("id") or (p.get("content") or "")[:80]
            if pid in seen:
                continue
            seen.add(pid)
            merged.append(p)
            if len(merged) >= top_k:
                break
        return self._format_passages(merged, title="相关归档记忆（语义召回）")

    def _fallback_keyword_passages(
        self,
        agent_id: str,
        user_id: str,
        query: str,
        top_k: int = 5,
    ) -> list:
        from services.memory import letta_store

        items = letta_store.list_passages(self.db, agent_id, user_id, limit=50)
        if not items and user_id:
            items = letta_store.list_passages(self.db, agent_id, "", limit=50)
        if not items:
            return []
        # 取查询中的汉字/字母数字片段做简单匹配
        import re

        tokens = [t for t in re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_-]{3,}", query) if t]
        if not tokens:
            return items[:top_k]
        scored = []
        for p in items:
            content = p.get("content") or ""
            score = sum(1 for t in tokens if t in content)
            if score > 0:
                scored.append((score, p))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in scored[:top_k]]

    def for_entity_context(self, agent_id: str, keyword: str = "", top_k: int = 8, user_id: str = "") -> str:
        from services.memory import letta_store

        if not letta_store.is_letta_enabled() or not keyword:
            return ""
        passages = letta_store.search_passages(
            self.db,
            agent_id=agent_id,
            query=keyword,
            user_id=user_id,
            top_k=top_k,
        )
        return self._format_passages(passages, title="历史结论与经验摘要")

    @staticmethod
    def _format_blocks(blocks: list, title: str) -> str:
        lines = []
        for b in blocks or []:
            value = (b.get("value") or "").strip()
            if not value:
                continue
            label = BLOCK_LABELS_ZH.get(b.get("label"), b.get("label") or "记忆")
            lines.append(f"- [{label}] {value}")
        if not lines:
            return ""
        header = (
            f"\n\n## {title}\n"
            "【记忆遵从规则】以下为核心长期记忆。回答用户问题时：\n"
            "1. 若记忆中含有与问题相关的偏好、格式、代号或事实，必须直接采用，禁止忽略或改写代号；\n"
            "2. 不得编造与记忆冲突的替代值；记忆未覆盖的内容可正常推理。\n"
        )
        return header + "\n".join(lines)

    @staticmethod
    def _format_passages(passages: list, title: str) -> str:
        if not passages:
            return ""
        lines = [
            f"\n\n## {title}",
            "【记忆遵从规则】以下为与当前问题相关的归档记忆（语义召回）。回答时：",
            "1. 若召回条目中已包含问题答案（如项目代号、组名、阈值、列名等），必须原样采用这些事实；",
            "2. 禁止回答「无法确认/不知道」——召回中已有依据时；禁止编造其他代号；",
            "3. 可简要引用召回内容作答，勿复述无关条目。",
        ]
        for p in passages:
            content = (p.get("content") or "").strip()
            if not content:
                continue
            tags = p.get("tags") or []
            tag_str = f" ({', '.join(tags)})" if tags else ""
            lines.append(f"- {content}{tag_str}")
        if len(lines) <= 5:
            return ""
        return "\n".join(lines)
