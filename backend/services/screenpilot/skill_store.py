"""UI 技能库：SQLite 结构化存储 + FAISS 语义检索。"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import faiss
import numpy as np
from sqlalchemy.orm import Session

from models import UiSkill, UiSkillStep, gen_uuid, now_utc
from services.screenpilot.config import SCREENPILOT_DATA_DIR

logger = logging.getLogger(__name__)

INDEX_DIR = os.path.join(SCREENPILOT_DATA_DIR, "faiss_skills")
os.makedirs(INDEX_DIR, exist_ok=True)


def _scope_key(scope: str) -> str:
    safe = (scope or "default").replace("/", "_")
    return safe


class SkillStore:
    def __init__(self):
        self._indexes: Dict[str, faiss.IndexFlatIP] = {}
        self._id_maps: Dict[str, List[str]] = {}

    def _embedding_model(self):
        from services.knowledge_service import knowledge_service
        return knowledge_service.embedding_model

    def _index_path(self, scope: str) -> str:
        return os.path.join(INDEX_DIR, f"faiss_ui_skills_{_scope_key(scope)}.index")

    def _map_path(self, scope: str) -> str:
        return os.path.join(INDEX_DIR, f"faiss_ui_skills_{_scope_key(scope)}.map.json")

    def _ensure_index(self, scope: str) -> faiss.IndexFlatIP:
        scope = scope or "default"
        if scope in self._indexes:
            return self._indexes[scope]
        idx_path = self._index_path(scope)
        map_path = self._map_path(scope)
        dim = self._embedding_model().get_sentence_embedding_dimension()
        if os.path.exists(idx_path) and os.path.exists(map_path):
            self._indexes[scope] = faiss.read_index(idx_path)
            with open(map_path, "r", encoding="utf-8") as f:
                self._id_maps[scope] = json.load(f)
            if self._indexes[scope].ntotal != len(self._id_maps[scope]):
                logger.warning("FAISS 索引与 skill map 数量不一致，将重建 scope=%s", scope)
                self._indexes[scope] = faiss.IndexFlatIP(dim)
                self._id_maps[scope] = []
        else:
            self._indexes[scope] = faiss.IndexFlatIP(dim)
            self._id_maps[scope] = []
        return self._indexes[scope]

    def _save_index(self, scope: str) -> None:
        scope = scope or "default"
        if scope not in self._indexes:
            return
        faiss.write_index(self._indexes[scope], self._index_path(scope))
        with open(self._map_path(scope), "w", encoding="utf-8") as f:
            json.dump(self._id_maps[scope], f, ensure_ascii=False)

    def _embed(self, text: str) -> np.ndarray:
        vec = self._embedding_model().encode([text], normalize_embeddings=True)
        return np.array(vec).astype("float32")

    def index_skill(self, skill_id: str, description: str, scope: str = "default") -> None:
        scope = scope or "default"
        index = self._ensure_index(scope)
        id_map = self._id_maps[scope]
        if skill_id in id_map:
            return
        emb = self._embed(description or skill_id)
        index.add(emb)
        id_map.append(skill_id)
        self._save_index(scope)

    def remove_skill_from_index(self, skill_id: str, scope: str = "default") -> None:
        """简单重建：删除单个 skill 时重建该 scope 索引。"""
        scope = scope or "default"
        id_map = self._id_maps.get(scope, [])
        if skill_id not in id_map:
            return
        id_map.remove(skill_id)
        dim = self._embedding_model().get_sentence_embedding_dimension()
        self._indexes[scope] = faiss.IndexFlatIP(dim)
        self._id_maps[scope] = []
        self._save_index(scope)

    def rebuild_scope_from_db(self, db: Session, scope: str = "default") -> None:
        scope = scope or "default"
        skills = (
            db.query(UiSkill)
            .filter(UiSkill.scope == scope, UiSkill.status == "ACTIVE")
            .all()
        )
        dim = self._embedding_model().get_sentence_embedding_dimension()
        self._indexes[scope] = faiss.IndexFlatIP(dim)
        self._id_maps[scope] = []
        for s in skills:
            self.index_skill(s.skill_id, f"{s.name}\n{s.description}", scope)

    def search(
        self, query: str, scope: str = "default", top_k: int = 5, db: Optional[Session] = None
    ) -> List[Tuple[str, float]]:
        scope = scope or "default"
        index = self._ensure_index(scope)
        if index.ntotal == 0 and db is not None:
            self.rebuild_scope_from_db(db, scope)
            index = self._ensure_index(scope)
        id_map = self._id_maps.get(scope, [])
        if index.ntotal == 0 or not query.strip():
            return []
        emb = self._embed(query)
        k = min(top_k, index.ntotal)
        scores, indices = index.search(emb, k)
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(id_map):
                continue
            results.append((id_map[idx], float(score)))
        return results

    def create_skill(
        self,
        db: Session,
        *,
        name: str,
        description: str,
        system_id: str,
        steps: List[Dict[str, Any]],
        scope: str = "default",
        param_schema: Optional[Dict[str, Any]] = None,
        source_session_id: str = "",
    ) -> UiSkill:
        skill = UiSkill(
            skill_id=gen_uuid(),
            name=name,
            description=description,
            system_id=system_id,
            scope=scope or "default",
            param_schema=param_schema or {},
            status="ACTIVE",
            source_session_id=source_session_id or "",
            created_at=now_utc(),
            updated_at=now_utc(),
        )
        db.add(skill)
        db.flush()

        for i, step in enumerate(steps):
            db.add(
                UiSkillStep(
                    step_id=gen_uuid(),
                    skill_id=skill.skill_id,
                    step_order=i + 1,
                    system_id=step.get("system_id") or system_id,
                    action=step.get("action", "click"),
                    target_label=step.get("target_label") or "",
                    value_template=step.get("value_template") or step.get("value") or "",
                    fingerprints=step.get("fingerprints") or {},
                    meta=step.get("meta") or {},
                    created_at=now_utc(),
                )
            )

        db.commit()
        db.refresh(skill)
        self.index_skill(skill.skill_id, f"{name}\n{description}", skill.scope)
        return skill

    def get_skill(self, db: Session, skill_id: str) -> Optional[UiSkill]:
        return db.query(UiSkill).filter(UiSkill.skill_id == skill_id).first()

    def get_steps(self, db: Session, skill_id: str) -> List[UiSkillStep]:
        return (
            db.query(UiSkillStep)
            .filter(UiSkillStep.skill_id == skill_id)
            .order_by(UiSkillStep.step_order.asc())
            .all()
        )

    def update_step_fingerprints(
        self, db: Session, step_id: str, fingerprints: Dict[str, Any]
    ) -> None:
        step = db.query(UiSkillStep).filter(UiSkillStep.step_id == step_id).first()
        if not step:
            return
        step.fingerprints = fingerprints
        db.commit()


skill_store = SkillStore()
