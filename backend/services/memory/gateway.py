"""MemoryGateway: 统一读写入口，MVP 写路径自动提交。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from models import MemoryRecord, gen_uuid, now_utc


MEMORY_TYPES = (
    "user_pref",
    "task_summary",
    "experience",
    "tool_profile",
    "provenance",
)


@dataclass
class MemoryCandidate:
    agent_id: str
    memory_type: str
    content: str
    user_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    source_episode_ids: List[str] = field(default_factory=list)
    created_by: str = "system"
    supersede_key: Optional[str] = None  # metadata key used to find prior active record


@dataclass
class MemoryQuery:
    agent_id: Optional[str] = None
    user_id: Optional[str] = None
    memory_types: Optional[List[str]] = None
    keyword: Optional[str] = None
    status: str = "active"
    top_k: int = 10
    include_superseded: bool = False


class MemoryGateway:
    def __init__(self, db: Session):
        self.db = db

    def write(self, candidate: MemoryCandidate) -> MemoryRecord:
        """自动提交：可选按 supersede_key 失效旧记录后写入新事实。"""
        if candidate.memory_type not in MEMORY_TYPES:
            raise ValueError(f"不支持的 memory_type: {candidate.memory_type}")

        now = now_utc()
        if candidate.supersede_key:
            key_val = (candidate.metadata or {}).get(candidate.supersede_key)
            if key_val is not None:
                self._supersede_matching(
                    agent_id=candidate.agent_id,
                    memory_type=candidate.memory_type,
                    user_id=candidate.user_id or "",
                    meta_key=candidate.supersede_key,
                    meta_value=key_val,
                    at=now,
                )

        record = MemoryRecord(
            record_id=gen_uuid(),
            agent_id=candidate.agent_id,
            user_id=candidate.user_id or "",
            memory_type=candidate.memory_type,
            content=candidate.content,
            meta=candidate.metadata or {},
            source_episode_ids=candidate.source_episode_ids or [],
            status="active",
            valid_from=now,
            valid_to=None,
            created_by=candidate.created_by or "system",
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def supersede(self, record_id: str, at: Optional[datetime] = None) -> Optional[MemoryRecord]:
        record = self.db.query(MemoryRecord).filter(MemoryRecord.record_id == record_id).first()
        if not record:
            return None
        if record.status == "superseded" or record.valid_to is not None:
            return record
        at = at or now_utc()
        record.valid_to = at
        record.status = "superseded"
        record.updated_at = at
        self.db.commit()
        self.db.refresh(record)
        return record

    def propose_edit(
        self,
        record_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        actor: str = "human",
    ) -> MemoryRecord:
        """旧事实失效 + 新事实写入。"""
        old = self.db.query(MemoryRecord).filter(MemoryRecord.record_id == record_id).first()
        if not old:
            raise ValueError("记忆记录不存在")

        now = now_utc()
        if old.status == "active" and old.valid_to is None:
            old.valid_to = now
            old.status = "superseded"
            old.updated_at = now

        new_meta = dict(old.meta or {})
        if metadata:
            new_meta.update(metadata)
        new_meta["supersedes"] = old.record_id

        new_record = MemoryRecord(
            record_id=gen_uuid(),
            agent_id=old.agent_id,
            user_id=old.user_id or "",
            memory_type=old.memory_type,
            content=content,
            meta=new_meta,
            source_episode_ids=list(old.source_episode_ids or []),
            status="active",
            valid_from=now,
            valid_to=None,
            created_by=actor,
        )
        self.db.add(new_record)
        self.db.commit()
        self.db.refresh(new_record)
        return new_record

    def score(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        """动作/记忆候选风险打分（与 ScreenPilot GOV 同构，不修改 write 路径）。"""
        from services.screenpilot.layers.govern import classify_risk

        action = candidate.get("action") or candidate.get("memory_type") or "read"
        label = candidate.get("target_label") or candidate.get("content") or ""
        if action in MEMORY_TYPES:
            action = "type" if "write" in str(candidate.get("operation", "")) else "extract"

        tier = classify_risk(str(action), str(label)[:200], candidate.get("risk_rules"))
        score_map = {"T0": 0.15, "T1": 0.45, "T2": 0.72, "T3": 0.95}
        route_map = {"T0": "auto", "T1": "sample_review", "T2": "hitl", "T3": "dual_review"}
        score_val = score_map.get(tier, 0.5)
        return {
            "tier": tier,
            "score": score_val,
            "route": route_map.get(tier, "hitl"),
            "confidence": 1.0 - score_val if tier in ("T0", "T1") else score_val,
        }

    def read(self, query: MemoryQuery) -> List[MemoryRecord]:
        q = self.db.query(MemoryRecord)
        if query.agent_id:
            q = q.filter(MemoryRecord.agent_id == query.agent_id)
        if query.user_id is not None and query.user_id != "":
            q = q.filter(MemoryRecord.user_id == query.user_id)
        if query.memory_types:
            q = q.filter(MemoryRecord.memory_type.in_(query.memory_types))
        if not query.include_superseded:
            if query.status:
                q = q.filter(MemoryRecord.status == query.status)
            q = q.filter(MemoryRecord.valid_to.is_(None))
        elif query.status:
            q = q.filter(MemoryRecord.status == query.status)
        if query.keyword:
            like = f"%{query.keyword}%"
            q = q.filter(MemoryRecord.content.like(like))
        q = q.order_by(MemoryRecord.created_at.desc())
        return q.limit(max(1, query.top_k)).all()

    def get(self, record_id: str) -> Optional[MemoryRecord]:
        return self.db.query(MemoryRecord).filter(MemoryRecord.record_id == record_id).first()

    def _supersede_matching(
        self,
        agent_id: str,
        memory_type: str,
        user_id: str,
        meta_key: str,
        meta_value: Any,
        at: datetime,
    ):
        rows = (
            self.db.query(MemoryRecord)
            .filter(
                MemoryRecord.agent_id == agent_id,
                MemoryRecord.memory_type == memory_type,
                MemoryRecord.user_id == user_id,
                MemoryRecord.status == "active",
                MemoryRecord.valid_to.is_(None),
            )
            .all()
        )
        for row in rows:
            meta = row.meta or {}
            if meta.get(meta_key) == meta_value:
                row.valid_to = at
                row.status = "superseded"
                row.updated_at = at
