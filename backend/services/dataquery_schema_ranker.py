"""DataQuery Schema 两阶段检索：表级混合排序（关键词 + 向量）。"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

import numpy as np

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


@dataclass
class TableCatalogEntry:
    table_name: str
    datasource_id: str
    db_comment: str = ""
    business_name: str = ""
    description: str = ""
    synonyms: List[str] = field(default_factory=list)
    dictionary_only: bool = False

    def search_text(self) -> str:
        parts = [
            self.table_name,
            self.business_name,
            self.description,
            self.db_comment,
            *self.synonyms,
        ]
        return " ".join(p.strip() for p in parts if p and str(p).strip())


class DataQuerySchemaRanker:
    KEYWORD_WEIGHT = 0.35
    VECTOR_WEIGHT = 0.65
    POOL_MULTIPLIER = 4
    MIN_POOL_SIZE = 20

    def __init__(self):
        self._embedding_model = None

    @property
    def embedding_model(self):
        if self._embedding_model is None:
            from services.knowledge_service import _create_embedding_model
            self._embedding_model = _create_embedding_model()
        return self._embedding_model

    @staticmethod
    def _tokenize(text: str) -> Set[str]:
        return {t.lower() for t in _TOKEN_RE.findall(text or "") if len(t) >= 2}

    @staticmethod
    def keyword_score(question: str, entry: TableCatalogEntry) -> float:
        q_lower = (question or "").lower()
        q_tokens = DataQuerySchemaRanker._tokenize(question)
        score = 0.0

        table_lower = entry.table_name.lower()
        if table_lower in q_lower:
            score += 8.0
        if q_tokens and table_lower in q_tokens:
            score += 4.0

        biz = (entry.business_name or "").strip()
        if biz:
            biz_lower = biz.lower()
            if biz_lower in q_lower:
                score += 6.0
            if biz in question:
                score += 4.0

        for syn in entry.synonyms or []:
            syn = (syn or "").strip()
            if not syn:
                continue
            if syn.lower() in q_lower or syn in question:
                score += 5.0

        desc = (entry.description or "").strip()
        if desc and (desc.lower() in q_lower or desc in question):
            score += 3.0

        db_comment = (entry.db_comment or "").strip()
        if db_comment and (db_comment.lower() in q_lower or db_comment in question):
            score += 2.0

        entry_tokens = DataQuerySchemaRanker._tokenize(entry.search_text())
        overlap = len(q_tokens & entry_tokens)
        score += overlap * 1.5

        return score

    def rank_tables(
        self,
        question: str,
        entries: List[TableCatalogEntry],
        top_k: int,
        boost_tables: Optional[Set[str]] = None,
    ) -> List[TableCatalogEntry]:
        if not entries:
            return []
        if len(entries) <= top_k:
            return list(entries)

        boost = {t.lower() for t in (boost_tables or set())}
        keyword_scored: List[tuple[float, TableCatalogEntry]] = []
        for entry in entries:
            kw = self.keyword_score(question, entry)
            if entry.table_name.lower() in boost:
                kw += 10.0
            keyword_scored.append((kw, entry))
        keyword_scored.sort(key=lambda x: x[0], reverse=True)

        pool_size = min(len(entries), max(top_k * self.POOL_MULTIPLIER, self.MIN_POOL_SIZE))
        pool = [e for _, e in keyword_scored[:pool_size]]
        kw_map = {e.table_name: s for s, e in keyword_scored}

        try:
            texts = [e.search_text() or e.table_name for e in pool]
            q_vec = np.array(
                self.embedding_model.encode([question], normalize_embeddings=True)[0],
                dtype="float32",
            )
            t_vecs = np.array(
                self.embedding_model.encode(texts, normalize_embeddings=True),
                dtype="float32",
            )
            hybrid: List[tuple[float, TableCatalogEntry]] = []
            max_kw = max(kw_map.values()) if kw_map else 1.0
            for i, entry in enumerate(pool):
                kw = kw_map.get(entry.table_name, 0.0)
                kw_norm = kw / max_kw if max_kw > 0 else 0.0
                vec = float(np.dot(q_vec, t_vecs[i]))
                hybrid_score = self.KEYWORD_WEIGHT * kw_norm + self.VECTOR_WEIGHT * vec
                if entry.table_name.lower() in boost:
                    hybrid_score += 0.5
                hybrid.append((hybrid_score, entry))
            hybrid.sort(key=lambda x: x[0], reverse=True)
            return [e for _, e in hybrid[:top_k]]
        except Exception as exc:
            logger.warning("表级向量排序失败，降级为关键词排序: %s", exc)
            return [e for _, e in keyword_scored[:top_k]]


dataquery_schema_ranker = DataQuerySchemaRanker()
