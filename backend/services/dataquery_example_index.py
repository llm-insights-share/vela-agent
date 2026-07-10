"""DataQuery 样例向量索引：按 dq_agent_id 维护 FAISS 索引，用于语义检索 NL→SQL 样例。"""
import json
import logging
import os
from typing import Any, Dict, List, Optional

import faiss
import numpy as np
from sqlalchemy.orm import Session

from database import DATA_DIR
from models import DataQueryExample
from services.knowledge_service import _create_embedding_model

logger = logging.getLogger(__name__)

os.makedirs(DATA_DIR, exist_ok=True)


class DataQueryExampleIndex:
  def __init__(self):
    self._embedding_model = None
    self._indexes: Dict[str, faiss.IndexFlatIP] = {}
    self._meta: Dict[str, List[Dict[str, Any]]] = {}

  @property
  def embedding_model(self):
    if self._embedding_model is None:
      self._embedding_model = _create_embedding_model()
    return self._embedding_model

  def _index_path(self, dq_agent_id: str) -> str:
    return os.path.join(DATA_DIR, f"faiss_dq_examples_{dq_agent_id}.index")

  def _meta_path(self, dq_agent_id: str) -> str:
    return os.path.join(DATA_DIR, f"dq_examples_{dq_agent_id}.json")

  def invalidate(self, dq_agent_id: str):
    self._indexes.pop(dq_agent_id, None)
    self._meta.pop(dq_agent_id, None)
    for path in (self._index_path(dq_agent_id), self._meta_path(dq_agent_id)):
      if os.path.exists(path):
        try:
          os.remove(path)
        except OSError:
          pass

  def _save(self, dq_agent_id: str):
    if dq_agent_id in self._indexes:
      faiss.write_index(self._indexes[dq_agent_id], self._index_path(dq_agent_id))
    if dq_agent_id in self._meta:
      with open(self._meta_path(dq_agent_id), "w", encoding="utf-8") as f:
        json.dump(self._meta[dq_agent_id], f, ensure_ascii=False, default=str)

  def _load_from_disk(self, dq_agent_id: str) -> bool:
    index_path = self._index_path(dq_agent_id)
    meta_path = self._meta_path(dq_agent_id)
    if not (os.path.exists(index_path) and os.path.exists(meta_path)):
      return False
    index = faiss.read_index(index_path)
    with open(meta_path, "r", encoding="utf-8") as f:
      meta = json.load(f)
    expected_dim = self.embedding_model.get_sentence_embedding_dimension()
    if index.d != expected_dim:
      return False
    self._indexes[dq_agent_id] = index
    self._meta[dq_agent_id] = meta
    return True

  def _db_fingerprint(self, db: Session, dq_agent_id: str) -> str:
    rows = db.query(DataQueryExample).filter(
      DataQueryExample.dq_agent_id == dq_agent_id,
      DataQueryExample.enabled == True,
    ).all()
    if not rows:
      return "empty"
    parts = sorted(
      f"{x.example_id}:{x.updated_at}:{x.nl_question}"
      for x in rows
    )
    return "|".join(parts)

  def rebuild(self, db: Session, dq_agent_id: str):
    examples = db.query(DataQueryExample).filter(
      DataQueryExample.dq_agent_id == dq_agent_id,
      DataQueryExample.enabled == True,
    ).all()
    dim = self.embedding_model.get_sentence_embedding_dimension()
    index = faiss.IndexFlatIP(dim)
    meta: List[Dict[str, Any]] = []
    if examples:
      texts = [ex.nl_question or "" for ex in examples]
      embeddings = self.embedding_model.encode(texts, normalize_embeddings=True)
      embeddings = np.array(embeddings).astype("float32")
      index.add(embeddings)
      meta = [
        {
          "example_id": ex.example_id,
          "datasource_id": ex.datasource_id,
          "nl_question": ex.nl_question,
          "sql_template": ex.sql_template,
          "quality_score": float(ex.quality_score or 0),
        }
        for ex in examples
      ]
    self._indexes[dq_agent_id] = index
    self._meta[dq_agent_id] = meta
    self._save(dq_agent_id)
    with open(self._meta_path(dq_agent_id).replace(".json", "_fp.json"), "w", encoding="utf-8") as f:
      json.dump({"fingerprint": self._db_fingerprint(db, dq_agent_id)}, f)

  def _ensure_index(self, db: Session, dq_agent_id: str):
    fp = self._db_fingerprint(db, dq_agent_id)
    fp_path = self._meta_path(dq_agent_id).replace(".json", "_fp.json")
    cached_fp = ""
    if os.path.exists(fp_path):
      try:
        with open(fp_path, "r", encoding="utf-8") as f:
          cached_fp = json.load(f).get("fingerprint", "")
      except Exception:
        pass

    if dq_agent_id in self._indexes and cached_fp == fp:
      return

    if cached_fp == fp and self._load_from_disk(dq_agent_id):
      return

    self.rebuild(db, dq_agent_id)

  def search(
    self,
    db: Session,
    dq_agent_id: str,
    question: str,
    k: int = 3,
    datasource_ids: Optional[List[str]] = None,
  ) -> List[Dict[str, Any]]:
    self._ensure_index(db, dq_agent_id)
    index = self._indexes.get(dq_agent_id)
    meta = self._meta.get(dq_agent_id, [])
    if not index or index.ntotal == 0 or not meta:
      return []

    allowed = {x for x in (datasource_ids or []) if x}
    candidates = meta
    if allowed:
      candidates = [m for m in meta if m.get("datasource_id") in allowed]
      if not candidates:
        return []

    query_vec = self.embedding_model.encode([question], normalize_embeddings=True)
    query_vec = np.array(query_vec).astype("float32")
    search_k = min(max(k * 5, k), index.ntotal)
    scores, indices = index.search(query_vec, search_k)

    results: List[Dict[str, Any]] = []
    seen = set()
    for score, idx in zip(scores[0], indices[0]):
      if idx < 0 or idx >= len(meta):
        continue
      item = meta[int(idx)]
      if allowed and item.get("datasource_id") not in allowed:
        continue
      eid = item.get("example_id")
      if eid in seen:
        continue
      seen.add(eid)
      results.append({**item, "score": float(score)})
      if len(results) >= k:
        break
    return results


dataquery_example_index = DataQueryExampleIndex()
