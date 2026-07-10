"""DataQuery 数据源 Schema 快照缓存（TTL + 字典/绑定指纹失效）。"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from sqlalchemy.orm import Session

from models import DataDictionaryItem, DataQueryDatasourceBinding, DataTableDictionary
from services.dataquery_schema_ranker import TableCatalogEntry


@dataclass
class CachedColumn:
    name: str
    db_type: str
    db_comment: str = ""


@dataclass
class SchemaSnapshot:
    catalog: List[TableCatalogEntry] = field(default_factory=list)
    table_names: List[str] = field(default_factory=list)
    table_names_lower: Set[str] = field(default_factory=set)
    columns: Dict[str, List[CachedColumn]] = field(default_factory=dict)
    table_db_comments: Dict[str, str] = field(default_factory=dict)
    fingerprint: str = ""
    cached_at: float = 0.0


class DataQuerySchemaCache:
    TTL_SECONDS = 300
    _store: Dict[str, SchemaSnapshot] = {}

    @classmethod
    def cache_key(cls, dq_agent_id: str, datasource_id: str) -> str:
        return f"{dq_agent_id}:{datasource_id}"

    @classmethod
    def compute_fingerprint(
        cls,
        db: Session,
        dq_agent_id: str,
        binding: DataQueryDatasourceBinding,
    ) -> str:
        table_max = db.query(DataTableDictionary.updated_at).filter(
            DataTableDictionary.dq_agent_id == dq_agent_id,
            DataTableDictionary.datasource_id == binding.datasource_id,
        ).order_by(DataTableDictionary.updated_at.desc()).first()
        col_max = db.query(DataDictionaryItem.updated_at).filter(
            DataDictionaryItem.dq_agent_id == dq_agent_id,
            DataDictionaryItem.datasource_id == binding.datasource_id,
        ).order_by(DataDictionaryItem.updated_at.desc()).first()
        whitelist = ",".join(binding.table_whitelist or [])
        binding_ts = binding.updated_at.isoformat() if binding.updated_at else ""
        return "|".join([
            binding.db_url or "",
            binding.db_type or "",
            binding.schema_name or "",
            whitelist,
            binding_ts,
            str(table_max[0] if table_max else ""),
            str(col_max[0] if col_max else ""),
        ])

    @classmethod
    def get(
        cls,
        db: Session,
        dq_agent_id: str,
        binding: DataQueryDatasourceBinding,
        builder,
    ) -> SchemaSnapshot:
        key = cls.cache_key(dq_agent_id, binding.datasource_id)
        fingerprint = cls.compute_fingerprint(db, dq_agent_id, binding)
        cached = cls._store.get(key)
        now = time.time()
        if (
            cached
            and cached.fingerprint == fingerprint
            and now - cached.cached_at < cls.TTL_SECONDS
        ):
            return cached

        snapshot = builder()
        snapshot.fingerprint = fingerprint
        snapshot.cached_at = now
        cls._store[key] = snapshot
        return snapshot

    @classmethod
    def invalidate(cls, dq_agent_id: str, datasource_id: Optional[str] = None) -> None:
        if datasource_id:
            cls._store.pop(cls.cache_key(dq_agent_id, datasource_id), None)
            return
        prefix = f"{dq_agent_id}:"
        for key in list(cls._store.keys()):
            if key.startswith(prefix):
                cls._store.pop(key, None)


dataquery_schema_cache = DataQuerySchemaCache()
