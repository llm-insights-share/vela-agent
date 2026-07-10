import json
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import create_engine, inspect as sa_inspect, text
from sqlalchemy.orm import Session

from models import (
    AuditLog,
    DataCodeMapping,
    DataDictionaryItem,
    DataQueryAgent,
    DataQueryDatasourceBinding,
    DataQueryExample,
    DataQueryExecutionLog,
    DataQueryExecutionStatus,
    DataQueryFeedback,
    DataQueryQualityStats,
    DataTableDictionary,
    DataTermMapping,
    ModelProvider,
    ModelService,
    gen_uuid,
    now_utc,
)
from services.dataquery_example_index import dataquery_example_index
from services.dataquery_schema_cache import CachedColumn, SchemaSnapshot, dataquery_schema_cache
from services.dataquery_schema_ranker import TableCatalogEntry, dataquery_schema_ranker
from services.model_provider import model_provider_service


class DataQueryService:
    SQL_BLOCK_LIST = ("insert", "update", "delete", "drop", "alter", "truncate", "create", "grant", "revoke")
    MAX_SQL_REWRITE_RETRIES = 3
    MAX_SCHEMA_TABLES = 80
    MAX_SCHEMA_COLUMNS = 40
    TOP_SCHEMA_TABLES = 8

    @staticmethod
    def _get_datasource_binding(db: Session, dq_agent_id: str, datasource_id: str) -> DataQueryDatasourceBinding:
        binding = db.query(DataQueryDatasourceBinding).filter(
            DataQueryDatasourceBinding.dq_agent_id == dq_agent_id,
            DataQueryDatasourceBinding.datasource_id == datasource_id,
        ).first()
        if not binding:
            raise ValueError("数据源绑定不存在")
        if not binding.db_url:
            raise ValueError("数据源未配置连接串")
        return binding

    @staticmethod
    def normalize_db_url(db_type: str, db_url: str) -> str:
        url = (db_url or "").strip()
        db_type = (db_type or "").lower()
        if db_type == "mysql":
            if url.startswith("mysql+mysqldb://"):
                return "mysql+pymysql://" + url[len("mysql+mysqldb://"):]
            if url.startswith("mysql://"):
                return "mysql+pymysql://" + url[len("mysql://"):]
        return url

    @staticmethod
    def _inspect_binding(binding: DataQueryDatasourceBinding):
        engine = create_engine(
            DataQueryService.normalize_db_url(binding.db_type, binding.db_url)
        )
        inspector = sa_inspect(engine)
        schema = binding.schema_name or None
        return engine, inspector, schema

    @staticmethod
    def list_schema_tables(db: Session, dq_agent_id: str, datasource_id: str) -> List[Dict[str, Any]]:
        binding = DataQueryService._get_datasource_binding(db, dq_agent_id, datasource_id)
        snapshot = DataQueryService._get_schema_snapshot(db, dq_agent_id, binding)
        annotations = {
            x.table_name: x
            for x in db.query(DataTableDictionary).filter(
                DataTableDictionary.dq_agent_id == dq_agent_id,
                DataTableDictionary.datasource_id == datasource_id,
            ).all()
        }
        items = []
        for entry in snapshot.catalog:
            if entry.dictionary_only:
                continue
            ann = annotations.get(entry.table_name)
            items.append({
                "table_name": entry.table_name,
                "db_comment": entry.db_comment,
                "business_name": ann.business_name if ann else entry.business_name,
                "description": ann.description if ann else entry.description,
                "synonyms": (ann.synonyms if ann else entry.synonyms) or [],
            })
        return items

    @staticmethod
    def list_schema_columns(
        db: Session,
        dq_agent_id: str,
        datasource_id: str,
        table_name: str,
    ) -> List[Dict[str, Any]]:
        binding = DataQueryService._get_datasource_binding(db, dq_agent_id, datasource_id)
        snapshot = DataQueryService._get_schema_snapshot(db, dq_agent_id, binding)
        saved = {
            x.column_name: x
            for x in db.query(DataDictionaryItem).filter(
                DataDictionaryItem.dq_agent_id == dq_agent_id,
                DataDictionaryItem.datasource_id == datasource_id,
                DataDictionaryItem.table_name == table_name,
            ).all()
        }
        items = []
        for col in snapshot.columns.get(table_name, []):
            saved_item = saved.get(col.name)
            items.append({
                "column_name": col.name,
                "db_type": col.db_type,
                "db_comment": col.db_comment,
                "business_name": (saved_item.business_name if saved_item and saved_item.business_name else col.name),
                "description": saved_item.description if saved_item else "",
            })
        return items

    @staticmethod
    def upsert_table_dictionary(
        db: Session,
        dq_agent_id: str,
        datasource_id: str,
        table_name: str,
        business_name: str = "",
        description: str = "",
        synonyms: Optional[List[str]] = None,
    ) -> DataTableDictionary:
        item = db.query(DataTableDictionary).filter(
            DataTableDictionary.dq_agent_id == dq_agent_id,
            DataTableDictionary.datasource_id == datasource_id,
            DataTableDictionary.table_name == table_name,
        ).first()
        if not item:
            item = DataTableDictionary(
                dq_agent_id=dq_agent_id,
                datasource_id=datasource_id,
                table_name=table_name,
            )
            db.add(item)
        item.business_name = business_name
        item.description = description
        item.synonyms = synonyms or []
        item.updated_at = now_utc()
        db.commit()
        db.refresh(item)
        DataQueryService.invalidate_schema_cache(dq_agent_id, datasource_id)
        return item

    @staticmethod
    def batch_upsert_column_dictionary(
        db: Session,
        dq_agent_id: str,
        datasource_id: str,
        table_name: str,
        columns: List[Dict[str, str]],
    ) -> int:
        updated = 0
        for col in columns:
            column_name = col.get("column_name", "")
            if not column_name:
                continue
            description = col.get("description", "")
            item = db.query(DataDictionaryItem).filter(
                DataDictionaryItem.dq_agent_id == dq_agent_id,
                DataDictionaryItem.datasource_id == datasource_id,
                DataDictionaryItem.table_name == table_name,
                DataDictionaryItem.column_name == column_name,
            ).first()
            if item:
                item.description = description
                item.updated_at = now_utc()
            else:
                item = DataDictionaryItem(
                    dq_agent_id=dq_agent_id,
                    datasource_id=datasource_id,
                    table_name=table_name,
                    column_name=column_name,
                    business_name=column_name,
                    description=description,
                )
                db.add(item)
            updated += 1
        db.commit()
        DataQueryService.invalidate_schema_cache(dq_agent_id, datasource_id)
        return updated

    @staticmethod
    def normalize_question(db: Session, dq_agent_id: str, question: str) -> Tuple[str, List[Dict[str, Any]]]:
        mappings = db.query(DataTermMapping).filter(
            DataTermMapping.dq_agent_id == dq_agent_id,
            DataTermMapping.enabled == True,
        ).order_by(DataTermMapping.priority.asc()).all()
        normalized = question
        applied = []
        for m in mappings:
            if m.source_term and m.source_term in normalized:
                normalized = normalized.replace(m.source_term, m.normalized_term)
                applied.append({
                    "source_term": m.source_term,
                    "normalized_term": m.normalized_term,
                    "mapping_type": m.mapping_type,
                })
        return normalized, applied

    @staticmethod
    def list_active_datasources(
        db: Session,
        dq_agent_id: str,
        datasource_id: Optional[str] = None,
    ) -> List[DataQueryDatasourceBinding]:
        ds_query = db.query(DataQueryDatasourceBinding).filter(
            DataQueryDatasourceBinding.dq_agent_id == dq_agent_id,
            DataQueryDatasourceBinding.status == "ACTIVE",
        )
        if datasource_id:
            ds_query = ds_query.filter(DataQueryDatasourceBinding.datasource_id == datasource_id)
        bindings = ds_query.order_by(DataQueryDatasourceBinding.id.asc()).all()
        if not bindings:
            raise ValueError("未找到可用数据源绑定")
        return bindings

    @staticmethod
    def _fetch_examples(
        db: Session,
        dq_agent_id: str,
        datasource_ids: List[str],
        question: str,
        k: int = 3,
    ) -> List[Dict[str, Any]]:
        hits = dataquery_example_index.search(
            db,
            dq_agent_id,
            question,
            k=k,
            datasource_ids=datasource_ids or None,
        )
        if hits:
            return hits

        # 向量索引为空时降级为词重叠检索
        q_words = set(question.lower().split())
        query = db.query(DataQueryExample).filter(
            DataQueryExample.dq_agent_id == dq_agent_id,
            DataQueryExample.enabled == True,
        )
        if datasource_ids:
            query = query.filter(DataQueryExample.datasource_id.in_(datasource_ids))
        candidates = query.all()
        scored = []
        for ex in candidates:
            words = set((ex.nl_question or "").lower().split())
            overlap = len(q_words & words)
            score = overlap + float(ex.quality_score or 0)
            scored.append((score, ex))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {
                "example_id": ex.example_id,
                "datasource_id": ex.datasource_id,
                "nl_question": ex.nl_question,
                "sql_template": ex.sql_template,
                "quality_score": float(ex.quality_score or 0),
            }
            for _, ex in scored[:k]
        ]

    @staticmethod
    def invalidate_schema_cache(dq_agent_id: str, datasource_id: Optional[str] = None):
        dataquery_schema_cache.invalidate(dq_agent_id, datasource_id)

    @staticmethod
    def invalidate_example_index(dq_agent_id: str):
        dataquery_example_index.invalidate(dq_agent_id)

    @staticmethod
    def _build_schema_snapshot(
        db: Session,
        dq_agent_id: str,
        binding: DataQueryDatasourceBinding,
    ) -> SchemaSnapshot:
        table_ann, _ = DataQueryService._dictionary_annotations(
            db, dq_agent_id, binding.datasource_id
        )
        engine, inspector, schema = DataQueryService._inspect_binding(binding)
        snapshot = SchemaSnapshot()
        seen: Set[str] = set()
        try:
            if binding.table_whitelist:
                table_names = list(binding.table_whitelist)[: DataQueryService.MAX_SCHEMA_TABLES]
            else:
                table_names = inspector.get_table_names(schema=schema)[: DataQueryService.MAX_SCHEMA_TABLES]

            snapshot.table_names = list(table_names)
            snapshot.table_names_lower = {n.lower() for n in table_names}

            for table_name in table_names:
                db_comment = ""
                try:
                    comment = inspector.get_table_comment(table_name, schema=schema)
                    if comment and comment.get("text"):
                        db_comment = comment["text"]
                except Exception:
                    pass
                snapshot.table_db_comments[table_name] = db_comment
                ann = table_ann.get(table_name)
                snapshot.catalog.append(TableCatalogEntry(
                    table_name=table_name,
                    datasource_id=binding.datasource_id,
                    db_comment=db_comment,
                    business_name=ann.business_name if ann else "",
                    description=ann.description if ann else "",
                    synonyms=list(ann.synonyms or []) if ann else [],
                ))
                seen.add(table_name.lower())

                cols: List[CachedColumn] = []
                try:
                    for col in inspector.get_columns(table_name, schema=schema)[: DataQueryService.MAX_SCHEMA_COLUMNS]:
                        cols.append(CachedColumn(
                            name=col["name"],
                            db_type=str(col.get("type", "")),
                            db_comment=col.get("comment") or "",
                        ))
                except Exception:
                    pass
                snapshot.columns[table_name] = cols

            for table_name, ann in table_ann.items():
                if table_name.lower() in seen:
                    continue
                snapshot.catalog.append(TableCatalogEntry(
                    table_name=table_name,
                    datasource_id=binding.datasource_id,
                    business_name=ann.business_name or "",
                    description=ann.description or "",
                    synonyms=list(ann.synonyms or []),
                    dictionary_only=True,
                ))
        finally:
            engine.dispose()
        return snapshot

    @staticmethod
    def _get_schema_snapshot(
        db: Session,
        dq_agent_id: str,
        binding: DataQueryDatasourceBinding,
    ) -> SchemaSnapshot:
        return dataquery_schema_cache.get(
            db,
            dq_agent_id,
            binding,
            lambda: DataQueryService._build_schema_snapshot(db, dq_agent_id, binding),
        )

    @staticmethod
    def _set_query_timeout(conn, db_type: str, timeout_seconds: int) -> None:
        if timeout_seconds <= 0:
            return
        db_type = (db_type or "").lower()
        ms = int(timeout_seconds * 1000)
        try:
            if db_type == "postgresql":
                conn.execute(text(f"SET LOCAL statement_timeout = {ms}"))
            elif db_type == "mysql":
                conn.execute(text(f"SET SESSION MAX_EXECUTION_TIME = {ms}"))
        except Exception:
            pass

    @staticmethod
    def _resolve_query_timeout(
        datasource: DataQueryDatasourceBinding,
        dq_agent: Optional[DataQueryAgent] = None,
    ) -> int:
        if datasource.timeout_seconds:
            return int(datasource.timeout_seconds)
        if dq_agent and dq_agent.timeout_seconds:
            return int(dq_agent.timeout_seconds)
        return 30

    @staticmethod
    def _dictionary_annotations(
        db: Session,
        dq_agent_id: str,
        datasource_id: str,
    ) -> Tuple[Dict[str, DataTableDictionary], Dict[Tuple[str, str], DataDictionaryItem]]:
        table_items = {
            x.table_name: x
            for x in db.query(DataTableDictionary).filter(
                DataTableDictionary.dq_agent_id == dq_agent_id,
                DataTableDictionary.datasource_id == datasource_id,
            ).all()
        }
        column_items = {
            (x.table_name, x.column_name): x
            for x in db.query(DataDictionaryItem).filter(
                DataDictionaryItem.dq_agent_id == dq_agent_id,
                DataDictionaryItem.datasource_id == datasource_id,
            ).all()
        }
        return table_items, column_items

    @staticmethod
    def _introspect_datasource_tables(
        db: Session,
        dq_agent_id: str,
        binding: DataQueryDatasourceBinding,
    ) -> Set[str]:
        if binding.table_whitelist:
            return {t.lower() for t in binding.table_whitelist}
        snapshot = DataQueryService._get_schema_snapshot(db, dq_agent_id, binding)
        return set(snapshot.table_names_lower)

    @staticmethod
    def _format_table_columns(
        table_name: str,
        binding: DataQueryDatasourceBinding,
        col_ann: Dict[Tuple[str, str], DataDictionaryItem],
        table_ann: Dict[str, DataTableDictionary],
        cached_columns: Optional[List[CachedColumn]] = None,
        db_comment: str = "",
    ) -> List[str]:
        lines: List[str] = []
        ann = table_ann.get(table_name)
        if not db_comment:
            db_comment = ""
        biz = ann.business_name if ann else ""
        desc = ann.description if ann else ""
        syn = ",".join(ann.synonyms or []) if ann else ""
        lines.append(
            f"表 `{table_name}`"
            f" (类型: {binding.db_type}; DB注释: {db_comment or '无'}"
            f"; 业务名: {biz or '无'}; 描述: {desc or '无'}; 别名: {syn or '无'})"
        )
        raw_cols = cached_columns or []
        for col in raw_cols[: DataQueryService.MAX_SCHEMA_COLUMNS]:
            col_name = col.name
            saved = col_ann.get((table_name, col_name))
            db_type = col.db_type
            db_col_comment = col.db_comment or ""
            biz_name = saved.business_name if saved and saved.business_name else col_name
            col_desc = saved.description if saved else ""
            col_syn = ",".join(saved.synonyms or []) if saved else ""
            lines.append(
                f"  - {col_name} {db_type}"
                f" (DB注释: {db_col_comment or '无'}"
                f"; 业务名: {biz_name}; 描述: {col_desc or '无'}"
                f"; 同义词: {col_syn or '无'})"
            )
        return lines

    @staticmethod
    def _schema_context_for_datasource(
        db: Session,
        dq_agent_id: str,
        binding: DataQueryDatasourceBinding,
        question: str,
        boost_tables: Optional[Set[str]] = None,
    ) -> str:
        table_ann, col_ann = DataQueryService._dictionary_annotations(
            db, dq_agent_id, binding.datasource_id
        )
        try:
            snapshot = DataQueryService._get_schema_snapshot(db, dq_agent_id, binding)
        except Exception as exc:
            return f"(无法连接数据源读取 schema: {exc})"

        catalog = snapshot.catalog
        lines: List[str] = []
        selected = dataquery_schema_ranker.rank_tables(
            question,
            catalog,
            top_k=DataQueryService.TOP_SCHEMA_TABLES,
            boost_tables=boost_tables,
        )
        selected_names = {e.table_name for e in selected}
        other_names = [e.table_name for e in catalog if e.table_name not in selected_names]

        lines.append(f"【相关表详情】（按问题筛选 Top-{len(selected)}，含完整列信息）")
        for entry in selected:
            if entry.dictionary_only:
                syn = ",".join(entry.synonyms or [])
                lines.append(
                    f"表 `{entry.table_name}` (仅字典标注; 业务名={entry.business_name or ''}; "
                    f"描述={entry.description or ''}; 别名={syn})"
                )
                for (t, col_name), item in col_ann.items():
                    if t != entry.table_name:
                        continue
                    syn_c = ",".join(item.synonyms or [])
                    lines.append(
                        f"  - {col_name}: 业务名={item.business_name or ''}; "
                        f"描述={item.description or ''}; 同义词={syn_c}"
                    )
            else:
                lines.extend(DataQueryService._format_table_columns(
                    entry.table_name,
                    binding,
                    col_ann,
                    table_ann,
                    cached_columns=snapshot.columns.get(entry.table_name, []),
                    db_comment=snapshot.table_db_comments.get(entry.table_name, entry.db_comment),
                ))

        if other_names:
            preview = ", ".join(other_names[:40])
            suffix = f" ...共{len(other_names)}张" if len(other_names) > 40 else ""
            lines.append(f"【库内其他表】（仅表名，未展开列）: {preview}{suffix}")

        if not lines:
            return "暂无 schema 信息。"
        return "\n".join(lines)

    @staticmethod
    def _boost_tables_from_examples(
        examples: List[Dict[str, Any]],
        datasource_id: str,
    ) -> Set[str]:
        tables: Set[str] = set()
        for ex in examples:
            if ex.get("datasource_id") and ex.get("datasource_id") != datasource_id:
                continue
            sql = ex.get("sql_template") or ""
            tables.update(DataQueryService._extract_sql_tables(sql))
        return tables

    @staticmethod
    def _schema_context(
        db: Session,
        dq_agent_id: str,
        datasources: List[DataQueryDatasourceBinding],
        question: str,
        examples: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        sections = []
        examples = examples or []
        for binding in datasources:
            ds_label = binding.datasource_name or binding.datasource_id
            boost = DataQueryService._boost_tables_from_examples(examples, binding.datasource_id)
            body = DataQueryService._schema_context_for_datasource(
                db, dq_agent_id, binding, question, boost_tables=boost
            )
            whitelist = binding.table_whitelist or []
            white_text = ",".join(whitelist) if whitelist else "无限制"
            sections.append(
                f"### 数据源 [{binding.datasource_id}] {ds_label} ({binding.db_type})\n"
                f"可访问表白名单: {white_text}\n"
                f"默认 LIMIT: {binding.default_limit or 200}\n"
                f"{body}"
            )
        return "\n\n".join(sections)

    @staticmethod
    def _extract_sql_tables(sql: str) -> Set[str]:
        low = sql.lower()
        from_tables = re.findall(r"\bfrom\s+([a-zA-Z0-9_\.]+)", low)
        join_tables = re.findall(r"\bjoin\s+([a-zA-Z0-9_\.]+)", low)
        tables = set()
        for t in from_tables + join_tables:
            base = t.split(".")[-1]
            tables.add(base)
        return tables

    @staticmethod
    def resolve_execution_datasource(
        db: Session,
        dq_agent_id: str,
        sql: str,
        datasources: List[DataQueryDatasourceBinding],
        preferred_datasource_id: Optional[str] = None,
    ) -> DataQueryDatasourceBinding:
        if preferred_datasource_id:
            for ds in datasources:
                if ds.datasource_id == preferred_datasource_id:
                    return ds
            raise ValueError(f"指定数据源不可用: {preferred_datasource_id}")

        if len(datasources) == 1:
            return datasources[0]

        touched = DataQueryService._extract_sql_tables(sql)
        if not touched:
            return datasources[0]

        table_map: Dict[str, Set[str]] = {}
        for ds in datasources:
            table_map[ds.datasource_id] = DataQueryService._introspect_datasource_tables(
                db, dq_agent_id, ds
            )

        candidates = []
        for ds in datasources:
            known = table_map.get(ds.datasource_id, set())
            if touched.issubset(known):
                candidates.append(ds)

        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            return candidates[0]

        # 按命中表数量择优
        scored = []
        for ds in datasources:
            known = table_map.get(ds.datasource_id, set())
            overlap = len(touched & known)
            scored.append((overlap, ds))
        scored.sort(key=lambda x: x[0], reverse=True)
        if scored and scored[0][0] > 0:
            return scored[0][1]
        return datasources[0]

    @staticmethod
    def build_prompt(
        db: Session,
        dq_agent: DataQueryAgent,
        datasources: List[DataQueryDatasourceBinding],
        question: str,
        normalized_question: str,
    ) -> str:
        datasource_ids = [ds.datasource_id for ds in datasources]
        examples = DataQueryService._fetch_examples(
            db, dq_agent.dq_agent_id, datasource_ids, normalized_question, 3
        )
        schema_context = DataQueryService._schema_context(
            db, dq_agent.dq_agent_id, datasources, normalized_question, examples
        )
        example_text = "\n".join([
            f"[{e.get('datasource_id', '')}] Q: {e.get('nl_question', '')}\nSQL: {e.get('sql_template', '')}"
            for e in examples
        ]) or "暂无样例"

        ds_summary = "; ".join([
            f"{ds.datasource_id}({ds.db_type})"
            for ds in datasources
        ])
        default_limit = datasources[0].default_limit or dq_agent.default_limit

        multi_ds_hint = ""
        if len(datasources) > 1:
            multi_ds_hint = (
                "\n5) 存在多个数据源时，SQL 只能访问单个数据源内的表；"
                "请根据 schema 选择最匹配的数据源生成 SQL"
            )

        return f"""
你是企业级 SQL 生成助手。请根据问题输出 SQL，仅输出 SQL 字符串，不要 markdown。

问题: {question}
规范化问题: {normalized_question}
可用数据源: {ds_summary}
默认限制行数: {default_limit}

库表结构（两阶段检索：相关表含完整列信息，其余仅表名）:
{schema_context}

参考样例（向量检索）:
{example_text}

约束:
1) 只能生成只读 SQL（SELECT/WITH）
2) 禁止 DML/DDL
3) 如果没有 LIMIT，请附加 LIMIT {default_limit}
4) 优先使用 schema 中的真实表名/列名，并结合业务字典理解语义{multi_ds_hint}
"""

    @staticmethod
    async def _generate_text(
        db: Session,
        model_service_id: str,
        prompt: str,
        max_tokens: int,
        timeout_seconds: int,
    ) -> Tuple[str, int]:
        model_svc = db.query(ModelService).filter(ModelService.model_service_id == model_service_id).first()
        if not model_svc:
            raise ValueError("DataQueryAgent 未配置有效模型服务")
        provider = db.query(ModelProvider).filter(ModelProvider.provider_id == model_svc.provider_id).first()
        if not provider:
            raise ValueError("DataQueryAgent 模型供应商不存在")

        completion = await model_provider_service.chat_completion(
            provider=provider,
            model_name=model_svc.model_name,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )
        content = completion.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
        tokens = completion.get("usage", {}).get("total_tokens", 0)
        return content, tokens

    @staticmethod
    async def generate_sql(
        db: Session,
        dq_agent: DataQueryAgent,
        prompt: str,
        rewrite_error: str = "",
    ) -> Tuple[str, int, str]:
        planner_notes = ""
        total_tokens = 0

        if dq_agent.planner_model_service_id:
            planner_prompt = f"""
你是查询规划助手。请给出完成下述查询问题的结构化思考要点（不要输出SQL）。
{prompt}
"""
            planner_notes, t = await DataQueryService._generate_text(
                db=db,
                model_service_id=dq_agent.planner_model_service_id,
                prompt=planner_prompt,
                max_tokens=min(1024, dq_agent.max_tokens or 2048),
                timeout_seconds=dq_agent.timeout_seconds or 30,
            )
            total_tokens += t

        sql_model_service_id = dq_agent.sql_model_service_id or dq_agent.model_service_id
        sql_prompt = prompt
        if planner_notes:
            sql_prompt += f"\n\n查询规划参考:\n{planner_notes}\n"
        if rewrite_error:
            sql_prompt += f"\n\n上一次 SQL 执行报错:\n{rewrite_error}\n请修正 SQL 并只输出 SQL。"

        sql_text, t2 = await DataQueryService._generate_text(
            db=db,
            model_service_id=sql_model_service_id,
            prompt=sql_prompt,
            max_tokens=dq_agent.max_tokens or 2048,
            timeout_seconds=dq_agent.timeout_seconds or 30,
        )
        total_tokens += t2
        sql = DataQueryService._extract_sql(sql_text)
        return sql, total_tokens, planner_notes

    @staticmethod
    def _extract_sql(content: str) -> str:
        if not content:
            return ""
        m = re.search(r"```sql\s*(.*?)```", content, re.IGNORECASE | re.DOTALL)
        if m:
            return m.group(1).strip().rstrip(";")
        return content.strip().rstrip(";")

    @staticmethod
    def guard_sql(sql: str, datasource: DataQueryDatasourceBinding, strict_mode: bool = True) -> str:
        if not sql:
            raise ValueError("未生成 SQL")

        low = sql.lower().strip()
        if not (low.startswith("select") or low.startswith("with")):
            raise ValueError("仅允许 SELECT/WITH 查询")

        for kw in DataQueryService.SQL_BLOCK_LIST:
            if re.search(rf"\b{kw}\b", low):
                raise ValueError(f"检测到禁止关键字: {kw}")

        whitelist = datasource.table_whitelist or []
        if strict_mode and whitelist:
            from_tables = re.findall(r"\bfrom\s+([a-zA-Z0-9_\.]+)", low)
            join_tables = re.findall(r"\bjoin\s+([a-zA-Z0-9_\.]+)", low)
            touched = set(from_tables + join_tables)
            allow = {x.lower() for x in whitelist}
            for t in touched:
                base = t.split(".")[-1]
                if t not in allow and base not in allow:
                    raise ValueError(f"查询表不在白名单: {t}")

        if " limit " not in f" {low} ":
            sql = f"{sql} LIMIT {datasource.default_limit or 200}"

        return sql

    @staticmethod
    def execute_sql(
        datasource: DataQueryDatasourceBinding,
        sql: str,
        timeout_seconds: Optional[int] = None,
        dq_agent: Optional[DataQueryAgent] = None,
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        timeout = timeout_seconds or DataQueryService._resolve_query_timeout(datasource, dq_agent)
        engine = create_engine(
            DataQueryService.normalize_db_url(datasource.db_type, datasource.db_url),
            future=True,
            pool_pre_ping=True,
        )
        try:
            with engine.connect() as conn:
                with conn.begin():
                    DataQueryService._set_query_timeout(conn, datasource.db_type, timeout)
                    result = conn.execution_options(timeout=timeout).execute(text(sql))
                    rows = [dict(row._mapping) for row in result.fetchall()]
                    cols = list(result.keys())
                return rows, cols
        except Exception as exc:
            low = str(exc).lower()
            if "timeout" in low or "max_execution_time" in low or "statement timeout" in low:
                raise ValueError(f"SQL 执行超时（{timeout}s）: {exc}") from exc
            raise
        finally:
            engine.dispose()

    @staticmethod
    def _apply_code_mapping(db: Session, dq_agent_id: str, datasource_id: str, rows: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        if not rows:
            return rows, []
        mappings = db.query(DataCodeMapping).filter(
            DataCodeMapping.dq_agent_id == dq_agent_id,
            DataCodeMapping.datasource_id == datasource_id,
        ).all()
        if not mappings:
            return rows, []

        mapping_idx = {}
        for m in mappings:
            mapping_idx.setdefault(m.column_name, {})[str(m.code_value)] = m.display_name

        applied = []
        output = []
        for r in rows:
            rr = dict(r)
            for c, idx in mapping_idx.items():
                if c in rr and rr[c] is not None:
                    key = str(rr[c])
                    if key in idx:
                        rr[f"{c}_name"] = idx[key]
                        applied.append({"column": c, "code": key, "name": idx[key]})
            output.append(rr)
        return output, applied

    @staticmethod
    def _update_quality_stats(db: Session, dq_agent_id: str, success: bool, duration_ms: int):
        stat_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        stat = db.query(DataQueryQualityStats).filter(
            DataQueryQualityStats.dq_agent_id == dq_agent_id,
            DataQueryQualityStats.stat_date == stat_date,
        ).first()
        if not stat:
            stat = DataQueryQualityStats(
                dq_agent_id=dq_agent_id,
                stat_date=stat_date,
                total_queries=0,
                success_queries=0,
                failed_queries=0,
                avg_duration_ms=0.0,
            )
            db.add(stat)

        prev_total = stat.total_queries or 0
        stat.total_queries = prev_total + 1
        if success:
            stat.success_queries = (stat.success_queries or 0) + 1
        else:
            stat.failed_queries = (stat.failed_queries or 0) + 1

        total = stat.total_queries
        stat.avg_duration_ms = ((stat.avg_duration_ms or 0.0) * prev_total + duration_ms) / max(total, 1)

    @staticmethod
    def _write_audit(db: Session, dq_agent: DataQueryAgent, payload: Dict[str, Any], duration_ms: int = 0, tokens_used: int = 0):
        audit = AuditLog(
            log_id=gen_uuid(),
            agent_id=dq_agent.dq_agent_id,
            session_id=payload.get("session_id", ""),
            event_type=payload.get("event_type", "sql_query"),
            event_data=payload,
            duration_ms=duration_ms,
            tokens_used=tokens_used,
            trace_id=payload.get("trace_id", ""),
        )
        db.add(audit)

    @staticmethod
    async def query(
        db: Session,
        dq_agent_id: str,
        question: str,
        datasource_id: Optional[str] = None,
        top_k: int = 100,
        strict_mode: bool = True,
        return_sql_only: bool = False,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        dq_agent = db.query(DataQueryAgent).filter(DataQueryAgent.dq_agent_id == dq_agent_id).first()
        if not dq_agent:
            raise ValueError("DataQueryAgent 不存在")

        datasources = DataQueryService.list_active_datasources(db, dq_agent_id, datasource_id=None)
        if datasource_id and not any(ds.datasource_id == datasource_id for ds in datasources):
            raise ValueError(f"指定数据源不可用或未激活: {datasource_id}")

        start = time.time()
        normalized, applied_terms = DataQueryService.normalize_question(db, dq_agent_id, question)
        prompt = DataQueryService.build_prompt(db, dq_agent, datasources, question, normalized)

        last_error: Optional[Exception] = None
        sql = ""
        guarded_sql = ""
        tokens = 0
        planner_notes = ""
        execution_ds = datasources[0]
        rows: List[Dict[str, Any]] = []
        cols: List[str] = []

        for attempt in range(DataQueryService.MAX_SQL_REWRITE_RETRIES + 1):
            try:
                if attempt == 0:
                    sql, gen_tokens, planner_notes = await DataQueryService.generate_sql(
                        db, dq_agent, prompt
                    )
                else:
                    sql, gen_tokens, _ = await DataQueryService.generate_sql(
                        db, dq_agent, prompt, rewrite_error=str(last_error)
                    )
                tokens += gen_tokens
                execution_ds = DataQueryService.resolve_execution_datasource(
                    db, dq_agent_id, sql, datasources, preferred_datasource_id=datasource_id
                )
                guarded_sql = DataQueryService.guard_sql(
                    sql, execution_ds, strict_mode and dq_agent.strict_mode
                )
                if return_sql_only:
                    return {
                        "success": True,
                        "normalized_question": normalized,
                        "generated_sql": guarded_sql,
                        "datasource_id": execution_ds.datasource_id,
                        "tokens_used": tokens,
                        "applied_terms": applied_terms,
                        "planner_notes": planner_notes,
                    }
                rows, cols = DataQueryService.execute_sql(
                    execution_ds, guarded_sql, dq_agent=dq_agent
                )
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                if attempt >= DataQueryService.MAX_SQL_REWRITE_RETRIES:
                    break

        if last_error is not None:
            DataQueryService.log_failure(
                db,
                dq_agent_id,
                execution_ds.datasource_id,
                question,
                normalized,
                guarded_sql,
                str(last_error),
                session_id=session_id or "",
            )
            raise ValueError(f"SQL 执行失败（已重试 {DataQueryService.MAX_SQL_REWRITE_RETRIES} 次）: {last_error}")

        rows = rows[:top_k]
        mapped_rows, applied_mappings = DataQueryService._apply_code_mapping(
            db, dq_agent_id, execution_ds.datasource_id, rows
        )
        duration_ms = int((time.time() - start) * 1000)

        log = DataQueryExecutionLog(
            log_id=gen_uuid(),
            dq_agent_id=dq_agent_id,
            datasource_id=execution_ds.datasource_id,
            session_id=session_id or "",
            question=question,
            normalized_question=normalized,
            generated_sql=guarded_sql,
            execution_status=DataQueryExecutionStatus.SUCCESS,
            rows=len(mapped_rows),
            duration_ms=duration_ms,
            tokens_used=tokens,
            applied_terms=applied_terms,
            applied_mappings=applied_mappings,
        )
        db.add(log)
        DataQueryService._update_quality_stats(db, dq_agent_id, True, duration_ms)
        DataQueryService._write_audit(
            db,
            dq_agent,
            {
                "event_type": "sql_query",
                "dq_agent_id": dq_agent_id,
                "datasource_id": execution_ds.datasource_id,
                "sql": guarded_sql,
                "row_count": len(mapped_rows),
                "session_id": session_id or "",
            },
            duration_ms=duration_ms,
            tokens_used=tokens,
        )
        db.commit()

        return {
            "success": True,
            "log_id": log.log_id,
            "datasource_id": execution_ds.datasource_id,
            "normalized_question": normalized,
            "generated_sql": guarded_sql,
            "columns": cols,
            "rows": mapped_rows,
            "row_count": len(mapped_rows),
            "duration_ms": duration_ms,
            "tokens_used": tokens,
            "applied_terms": applied_terms,
            "applied_mappings": applied_mappings,
            "warnings": [],
            "planner_notes": planner_notes,
        }

    @staticmethod
    def log_failure(
        db: Session,
        dq_agent_id: str,
        datasource_id: str,
        question: str,
        normalized_question: str,
        generated_sql: str,
        error_message: str,
        session_id: str = "",
    ):
        log = DataQueryExecutionLog(
            log_id=gen_uuid(),
            dq_agent_id=dq_agent_id,
            datasource_id=datasource_id,
            session_id=session_id,
            question=question,
            normalized_question=normalized_question,
            generated_sql=generated_sql,
            execution_status=DataQueryExecutionStatus.FAILED,
            error_message=error_message[:2000],
            rows=0,
            duration_ms=0,
            tokens_used=0,
        )
        db.add(log)
        DataQueryService._update_quality_stats(db, dq_agent_id, False, 0)
        db.commit()

    @staticmethod
    def add_feedback(db: Session, log_id: str, rating: int, comment: str = "") -> DataQueryFeedback:
        log = db.query(DataQueryExecutionLog).filter(DataQueryExecutionLog.log_id == log_id).first()
        if not log:
            raise ValueError("执行日志不存在")
        fb = DataQueryFeedback(
            feedback_id=gen_uuid(),
            log_id=log_id,
            dq_agent_id=log.dq_agent_id,
            session_id=log.session_id or "",
            rating=rating,
            comment=comment or "",
        )
        db.add(fb)
        log.feedback_score = rating

        stat_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        stat = db.query(DataQueryQualityStats).filter(
            DataQueryQualityStats.dq_agent_id == log.dq_agent_id,
            DataQueryQualityStats.stat_date == stat_date,
        ).first()
        if stat:
            prev_total = stat.total_queries or 0
            stat.avg_feedback_score = ((stat.avg_feedback_score or 0.0) * max(prev_total - 1, 0) + rating) / max(prev_total, 1)

        db.commit()
        db.refresh(fb)
        return fb


dataquery_service = DataQueryService()
