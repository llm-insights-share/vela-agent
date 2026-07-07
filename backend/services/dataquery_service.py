import json
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import create_engine, text
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
    DataTermMapping,
    ModelProvider,
    ModelService,
    gen_uuid,
)
from services.model_provider import model_provider_service


class DataQueryService:
    SQL_BLOCK_LIST = ("insert", "update", "delete", "drop", "alter", "truncate", "create", "grant", "revoke")

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
    def _fetch_examples(db: Session, dq_agent_id: str, datasource_id: str, question: str, k: int = 3) -> List[DataQueryExample]:
        q_words = set(question.lower().split())
        candidates = db.query(DataQueryExample).filter(
            DataQueryExample.dq_agent_id == dq_agent_id,
            DataQueryExample.datasource_id == datasource_id,
            DataQueryExample.enabled == True,
        ).all()

        scored = []
        for ex in candidates:
            words = set((ex.nl_question or "").lower().split())
            overlap = len(q_words & words)
            score = overlap + float(ex.quality_score or 0)
            scored.append((score, ex))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [x[1] for x in scored[:k]]

    @staticmethod
    def _schema_context(db: Session, dq_agent_id: str, datasource_id: str) -> str:
        items = db.query(DataDictionaryItem).filter(
            DataDictionaryItem.dq_agent_id == dq_agent_id,
            DataDictionaryItem.datasource_id == datasource_id,
        ).all()
        if not items:
            return "暂无字段字典，请基于通用 SQL 生成。"
        lines = []
        for it in items:
            syn = ",".join(it.synonyms or [])
            lines.append(
                f"- {it.table_name}.{it.column_name}: 业务名={it.business_name or ''}; 描述={it.description or ''}; 同义词={syn}"
            )
        return "\n".join(lines[:300])

    @staticmethod
    def build_prompt(
        db: Session,
        dq_agent: DataQueryAgent,
        datasource: DataQueryDatasourceBinding,
        question: str,
        normalized_question: str,
    ) -> str:
        schema_context = DataQueryService._schema_context(db, dq_agent.dq_agent_id, datasource.datasource_id)
        examples = DataQueryService._fetch_examples(db, dq_agent.dq_agent_id, datasource.datasource_id, normalized_question, 3)
        example_text = "\n".join([
            f"Q: {e.nl_question}\nSQL: {e.sql_template}"
            for e in examples
        ]) or "暂无样例"

        whitelist = datasource.table_whitelist or []
        white_text = ",".join(whitelist) if whitelist else "无限制"

        return f"""
你是企业级 SQL 生成助手。请根据问题输出 SQL，仅输出 SQL 字符串，不要 markdown。

问题: {question}
规范化问题: {normalized_question}
数据库类型: {datasource.db_type}
可访问表白名单: {white_text}
默认限制行数: {datasource.default_limit or dq_agent.default_limit}

字段字典:
{schema_context}

参考样例:
{example_text}

约束:
1) 只能生成只读 SQL（SELECT/WITH）
2) 禁止 DML/DDL
3) 如果没有 LIMIT，请附加 LIMIT {datasource.default_limit or dq_agent.default_limit}
4) 尽量使用字典中的字段/业务名映射
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
    def execute_sql(datasource: DataQueryDatasourceBinding, sql: str) -> Tuple[List[Dict[str, Any]], List[str]]:
        engine = create_engine(datasource.db_url, future=True)
        with engine.connect() as conn:
            result = conn.execute(text(sql))
            rows = [dict(row._mapping) for row in result.fetchall()]
            cols = list(result.keys())
        return rows, cols

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

        ds_query = db.query(DataQueryDatasourceBinding).filter(
            DataQueryDatasourceBinding.dq_agent_id == dq_agent_id,
            DataQueryDatasourceBinding.status == "ACTIVE",
        )
        if datasource_id:
            ds_query = ds_query.filter(DataQueryDatasourceBinding.datasource_id == datasource_id)
        datasource = ds_query.first()
        if not datasource:
            raise ValueError("未找到可用数据源绑定")

        start = time.time()
        normalized, applied_terms = DataQueryService.normalize_question(db, dq_agent_id, question)
        prompt = DataQueryService.build_prompt(db, dq_agent, datasource, question, normalized)
        sql, tokens, planner_notes = await DataQueryService.generate_sql(db, dq_agent, prompt)
        guarded_sql = DataQueryService.guard_sql(sql, datasource, strict_mode and dq_agent.strict_mode)
        if return_sql_only:
            return {
                "success": True,
                "normalized_question": normalized,
                "generated_sql": guarded_sql,
                "tokens_used": tokens,
                "applied_terms": applied_terms,
                "planner_notes": planner_notes,
            }

        try:
            rows, cols = DataQueryService.execute_sql(datasource, guarded_sql)
        except Exception as exec_error:
            # P2: SQL 自检重写回路，重试一次
            retry_sql, retry_tokens, _ = await DataQueryService.generate_sql(
                db, dq_agent, prompt, rewrite_error=str(exec_error)
            )
            tokens += retry_tokens
            guarded_sql = DataQueryService.guard_sql(retry_sql, datasource, strict_mode and dq_agent.strict_mode)
            rows, cols = DataQueryService.execute_sql(datasource, guarded_sql)

        rows = rows[:top_k]
        mapped_rows, applied_mappings = DataQueryService._apply_code_mapping(
            db, dq_agent_id, datasource.datasource_id, rows
        )
        duration_ms = int((time.time() - start) * 1000)

        log = DataQueryExecutionLog(
            log_id=gen_uuid(),
            dq_agent_id=dq_agent_id,
            datasource_id=datasource.datasource_id,
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
                "datasource_id": datasource.datasource_id,
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
