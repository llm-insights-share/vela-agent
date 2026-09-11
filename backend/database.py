import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

DATABASE_URL = f"sqlite:///{os.path.join(DATA_DIR, 'vela_agent.db')}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False}, echo=False)

@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from models import (
        Agent, AgentVersion, ModelProvider, ModelService, SkillPack, KnowledgeBase,
        AgentSchedule, AgentScheduleRun, InboxMessage,
        McpServer, McpOAuthCredential, McpOAuthState, UserConnector,
        DataQueryAgent, DataQueryDatasourceBinding, DataQueryExecutionLog,
        DataTableDictionary, DataDictionaryItem, DataCodeMapping, DataQueryExample, DataTermMapping,
        DataQueryFeedback, DataQueryQualityStats,
        MemoryEpisode, MemoryRecord, LettaMemoryAgent,
        ScreenSystem, ScreenCredential, ScreenSession, UiAuditLog, UiSkill, UiSkillStep,
        AgentRun, AgentSpan, AgentScore, AgentFeedback, MonitorAlert,
        EvalDataset, EvalCase, EvalJob, EvalJobResult,
    )
    Base.metadata.create_all(bind=engine)
    _migrate_db()


def _migrate_db():
    """SQLite 轻量级迁移：为已有表补充新字段"""
    import sqlite3
    db_path = os.path.join(DATA_DIR, "vela_agent.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 检查 agents 表是否需要新增 V0.2 字段
    cursor.execute("PRAGMA table_info(agents)")
    existing_cols = {row[1] for row in cursor.fetchall()}

    new_columns = [
        ("max_iterations", "INTEGER DEFAULT 10"),
        ("step_timeout_seconds", "INTEGER DEFAULT 60"),
        ("timeout_seconds", "INTEGER DEFAULT 180"),
        ("tool_retry_count", "INTEGER DEFAULT 2"),
        ("tool_retry_backoff", "VARCHAR(16) DEFAULT 'fixed'"),
        ("allow_repeat_tool_calls", "BOOLEAN DEFAULT 1"),
        ("max_repeat_threshold", "INTEGER DEFAULT 3"),
        ("single_call_token_limit", "INTEGER DEFAULT 8192"),
        ("agent_type", "VARCHAR(16) DEFAULT 'SINGLE'"),
        ("composition_config", "TEXT DEFAULT '{}'"),
        ("workflow_definition", "TEXT DEFAULT '{}'"),
        ("memory_enabled", "BOOLEAN DEFAULT 0"),
        ("query_rewrite_enabled", "BOOLEAN DEFAULT 0"),
    ]

    for col_name, col_def in new_columns:
        if col_name not in existing_cols:
            cursor.execute(f"ALTER TABLE agents ADD COLUMN {col_name} {col_def}")

    # SGL-CFG-06 / MA-IMP-09: agent_tool_bindings.require_approval + sessions.pending_context
    cursor.execute("PRAGMA table_info(agent_tool_bindings)")
    atb_cols = {row[1] for row in cursor.fetchall()}
    if "require_approval" not in atb_cols:
        cursor.execute("ALTER TABLE agent_tool_bindings ADD COLUMN require_approval BOOLEAN DEFAULT 0")

    cursor.execute("PRAGMA table_info(sessions)")
    sess_cols = {row[1] for row in cursor.fetchall()}
    if "pending_context" not in sess_cols:
        cursor.execute("ALTER TABLE sessions ADD COLUMN pending_context TEXT DEFAULT '{}'")
    if "llm_calls" not in sess_cols:
        cursor.execute("ALTER TABLE sessions ADD COLUMN llm_calls TEXT DEFAULT '[]'")
    if "title" not in sess_cols:
        cursor.execute("ALTER TABLE sessions ADD COLUMN title VARCHAR(128) DEFAULT ''")

    # ScreenPilot P1: ui_audit_logs 哈希链字段
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ui_audit_logs'")
    if cursor.fetchone():
        cursor.execute("PRAGMA table_info(ui_audit_logs)")
        audit_cols = {row[1] for row in cursor.fetchall()}
        if "prev_hash" not in audit_cols:
            cursor.execute("ALTER TABLE ui_audit_logs ADD COLUMN prev_hash VARCHAR(64) DEFAULT ''")
        if "content_hash" not in audit_cols:
            cursor.execute("ALTER TABLE ui_audit_logs ADD COLUMN content_hash VARCHAR(64) DEFAULT ''")

    # ScreenPilot P2: ui_skills 技能商店字段
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ui_skills'")
    if cursor.fetchone():
        cursor.execute("PRAGMA table_info(ui_skills)")
        skill_cols = {row[1] for row in cursor.fetchall()}
        if "visibility" not in skill_cols:
            cursor.execute("ALTER TABLE ui_skills ADD COLUMN visibility VARCHAR(16) DEFAULT 'PRIVATE'")
        if "publisher_id" not in skill_cols:
            cursor.execute("ALTER TABLE ui_skills ADD COLUMN publisher_id VARCHAR(128) DEFAULT ''")
        if "published_at" not in skill_cols:
            cursor.execute("ALTER TABLE ui_skills ADD COLUMN published_at DATETIME")

    # ScreenPilot: screen_credentials → name/value_enc KV
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='screen_credentials'"
    )
    if cursor.fetchone():
        cursor.execute("PRAGMA table_info(screen_credentials)")
        cred_cols = {row[1] for row in cursor.fetchall()}
        if "value_enc" not in cred_cols and "secret_enc" in cred_cols:
            import json as _json
            import uuid as _uuid

            from services.screenpilot.crypto_util import decrypt_secret, encrypt_secret

            cursor.execute(
                """
                CREATE TABLE screen_credentials_kv (
                    credential_id VARCHAR NOT NULL PRIMARY KEY,
                    system_id VARCHAR NOT NULL,
                    name VARCHAR(128) NOT NULL DEFAULT '',
                    value_enc TEXT DEFAULT '',
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
            cursor.execute(
                "SELECT credential_id, system_id, username, secret_enc, extra, created_at, updated_at "
                "FROM screen_credentials"
            )
            for (
                _cid,
                system_id,
                username,
                secret_enc,
                extra,
                created_at,
                updated_at,
            ) in cursor.fetchall():
                if username:
                    cursor.execute(
                        "INSERT INTO screen_credentials_kv "
                        "(credential_id, system_id, name, value_enc, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            str(_uuid.uuid4()),
                            system_id,
                            "username",
                            encrypt_secret(username),
                            created_at,
                            updated_at,
                        ),
                    )
                if secret_enc:
                    pw_enc = secret_enc if decrypt_secret(secret_enc) else encrypt_secret(secret_enc)
                    cursor.execute(
                        "INSERT INTO screen_credentials_kv "
                        "(credential_id, system_id, name, value_enc, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            str(_uuid.uuid4()),
                            system_id,
                            "password",
                            pw_enc,
                            created_at,
                            updated_at,
                        ),
                    )
                try:
                    extra_obj = (
                        _json.loads(extra) if isinstance(extra, str) and extra else (extra or {})
                    )
                except Exception:
                    extra_obj = {}
                if isinstance(extra_obj, dict):
                    ss = extra_obj.get("storage_state_enc")
                    sat = extra_obj.get("storage_state_saved_at")
                    if ss:
                        cursor.execute(
                            "INSERT INTO screen_credentials_kv "
                            "(credential_id, system_id, name, value_enc, created_at, updated_at) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (
                                str(_uuid.uuid4()),
                                system_id,
                                "__storage_state",
                                ss if decrypt_secret(ss) else encrypt_secret(str(ss)),
                                created_at,
                                updated_at,
                            ),
                        )
                    if sat:
                        cursor.execute(
                            "INSERT INTO screen_credentials_kv "
                            "(credential_id, system_id, name, value_enc, created_at, updated_at) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (
                                str(_uuid.uuid4()),
                                system_id,
                                "__storage_state_saved_at",
                                encrypt_secret(str(sat)),
                                created_at,
                                updated_at,
                            ),
                        )

            cursor.execute("DROP TABLE screen_credentials")
            cursor.execute("ALTER TABLE screen_credentials_kv RENAME TO screen_credentials")
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS ix_screen_credentials_system_id "
                "ON screen_credentials (system_id)"
            )

    # ScreenPilot: reuse local browser (CDP) per system
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='screen_systems'"
    )
    if cursor.fetchone():
        cursor.execute("PRAGMA table_info(screen_systems)")
        sys_cols = {row[1] for row in cursor.fetchall()}
        if "reuse_local_browser" not in sys_cols:
            cursor.execute(
                "ALTER TABLE screen_systems ADD COLUMN reuse_local_browser BOOLEAN DEFAULT 0"
            )
        if "cdp_url" not in sys_cols:
            cursor.execute(
                "ALTER TABLE screen_systems ADD COLUMN cdp_url VARCHAR(512) DEFAULT ''"
            )

    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='skill_packs'"
    )
    if cursor.fetchone():
        cursor.execute("PRAGMA table_info(skill_packs)")
        skill_pack_cols = {row[1] for row in cursor.fetchall()}
        if "package_files" not in skill_pack_cols:
            cursor.execute(
                "ALTER TABLE skill_packs ADD COLUMN package_files TEXT DEFAULT '{}'"
            )

    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='knowledge_bases'"
    )
    if cursor.fetchone():
        cursor.execute("PRAGMA table_info(knowledge_bases)")
        kb_cols = {row[1] for row in cursor.fetchall()}
        if "contextual_retrieval_enabled" not in kb_cols:
            cursor.execute(
                "ALTER TABLE knowledge_bases ADD COLUMN contextual_retrieval_enabled BOOLEAN"
            )
        if "tag_defs" not in kb_cols:
            cursor.execute(
                "ALTER TABLE knowledge_bases ADD COLUMN tag_defs TEXT DEFAULT '[]'"
            )

    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='tools'"
    )
    if cursor.fetchone():
        cursor.execute("PRAGMA table_info(tools)")
        tool_cols = {row[1] for row in cursor.fetchall()}
        if "mcp_server_id" not in tool_cols:
            cursor.execute("ALTER TABLE tools ADD COLUMN mcp_server_id VARCHAR")

    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='dataquery_datasource_bindings'"
    )
    if cursor.fetchone():
        cursor.execute("PRAGMA table_info(dataquery_datasource_bindings)")
        ds_cols = {row[1] for row in cursor.fetchall()}
        if "business_scope" not in ds_cols:
            cursor.execute(
                "ALTER TABLE dataquery_datasource_bindings ADD COLUMN business_scope TEXT DEFAULT ''"
            )

    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='mcp_servers'"
    )
    if cursor.fetchone():
        cursor.execute("PRAGMA table_info(mcp_servers)")
        mcp_cols = {row[1] for row in cursor.fetchall()}
        if "owner_user_id" not in mcp_cols:
            cursor.execute(
                "ALTER TABLE mcp_servers ADD COLUMN owner_user_id VARCHAR"
            )

    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='model_services'"
    )
    if cursor.fetchone():
        cursor.execute("PRAGMA table_info(model_services)")
        ms_cols = {row[1] for row in cursor.fetchall()}
        if "last_test_ok" not in ms_cols:
            cursor.execute("ALTER TABLE model_services ADD COLUMN last_test_ok BOOLEAN")
        if "last_tested_at" not in ms_cols:
            cursor.execute("ALTER TABLE model_services ADD COLUMN last_tested_at DATETIME")
        if "last_test_error" not in ms_cols:
            cursor.execute(
                "ALTER TABLE model_services ADD COLUMN last_test_error TEXT DEFAULT ''"
            )

    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_connector_bindings'"
    )
    if not cursor.fetchone():
        cursor.execute(
            """
            CREATE TABLE agent_connector_bindings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id VARCHAR NOT NULL,
                catalog_key VARCHAR(64) NOT NULL,
                tool_policies TEXT DEFAULT '{}',
                created_at DATETIME,
                UNIQUE (agent_id, catalog_key)
            )
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS ix_agent_connector_bindings_agent_id "
            "ON agent_connector_bindings (agent_id)"
        )

    # Monitor / Eval gap alignment migrations
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_scores'"
    )
    if cursor.fetchone():
        cursor.execute("PRAGMA table_info(agent_scores)")
        score_cols = {row[1] for row in cursor.fetchall()}
        if "data_type" not in score_cols:
            cursor.execute(
                "ALTER TABLE agent_scores ADD COLUMN data_type VARCHAR(32) DEFAULT 'NUMERIC'"
            )

    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='eval_cases'"
    )
    if cursor.fetchone():
        cursor.execute("PRAGMA table_info(eval_cases)")
        case_cols = {row[1] for row in cursor.fetchall()}
        if "expected_output" not in case_cols:
            cursor.execute(
                "ALTER TABLE eval_cases ADD COLUMN expected_output TEXT DEFAULT ''"
            )

    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='eval_jobs'"
    )
    if cursor.fetchone():
        cursor.execute("PRAGMA table_info(eval_jobs)")
        job_cols = {row[1] for row in cursor.fetchall()}
        if "run_mode" not in job_cols:
            cursor.execute(
                "ALTER TABLE eval_jobs ADD COLUMN run_mode VARCHAR(16) DEFAULT 'replay'"
            )
        if "evaluator_id" not in job_cols:
            cursor.execute(
                "ALTER TABLE eval_jobs ADD COLUMN evaluator_id VARCHAR DEFAULT ''"
            )

    for table_sql in (
        """
        CREATE TABLE IF NOT EXISTS eval_rule_evaluators (
            evaluator_id VARCHAR PRIMARY KEY,
            name VARCHAR(128) NOT NULL,
            agent_id VARCHAR,
            enabled BOOLEAN DEFAULT 1,
            rules_json TEXT DEFAULT '{}',
            created_at DATETIME,
            updated_at DATETIME
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS eval_judge_evaluators (
            evaluator_id VARCHAR PRIMARY KEY,
            name VARCHAR(128) NOT NULL,
            agent_id VARCHAR,
            enabled BOOLEAN DEFAULT 1,
            sample_rate FLOAT DEFAULT 0.1,
            prompt_template TEXT DEFAULT '',
            model_service_id VARCHAR DEFAULT '',
            created_at DATETIME,
            updated_at DATETIME
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS monitor_alert_rules (
            rule_id VARCHAR PRIMARY KEY,
            name VARCHAR(128) NOT NULL,
            metric VARCHAR(64) NOT NULL,
            threshold_warning FLOAT DEFAULT 0,
            threshold_alert FLOAT DEFAULT 0,
            webhook_url VARCHAR(512) DEFAULT '',
            enabled BOOLEAN DEFAULT 1,
            agent_id VARCHAR DEFAULT '',
            created_at DATETIME
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS annotation_queues (
            queue_id VARCHAR PRIMARY KEY,
            name VARCHAR(128) NOT NULL,
            agent_id VARCHAR DEFAULT '',
            description TEXT DEFAULT '',
            created_at DATETIME
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS annotation_queue_items (
            item_id VARCHAR PRIMARY KEY,
            queue_id VARCHAR NOT NULL,
            run_id VARCHAR DEFAULT '',
            case_id VARCHAR DEFAULT '',
            status VARCHAR(32) DEFAULT 'pending',
            expected_output TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created_at DATETIME,
            FOREIGN KEY(queue_id) REFERENCES annotation_queues(queue_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS monitor_saved_views (
            view_id VARCHAR PRIMARY KEY,
            name VARCHAR(128) NOT NULL,
            path VARCHAR(64) DEFAULT 'runs',
            filters_json TEXT DEFAULT '{}',
            user_id VARCHAR DEFAULT '',
            created_at DATETIME
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS selfopt_jobs (
            job_id VARCHAR PRIMARY KEY,
            agent_id VARCHAR NOT NULL,
            job_label VARCHAR(256),
            window_start DATETIME,
            window_end DATETIME,
            status VARCHAR(32) DEFAULT 'pending',
            stats_json TEXT DEFAULT '{}',
            created_at DATETIME,
            updated_at DATETIME
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS selfopt_proposals (
            proposal_id VARCHAR PRIMARY KEY,
            job_id VARCHAR,
            agent_id VARCHAR NOT NULL,
            base_version_id VARCHAR,
            candidate_version_id VARCHAR,
            change_kind VARCHAR(64) DEFAULT 'prompt_fewshot',
            risk_tier VARCHAR(16) DEFAULT 'T1',
            diff_json TEXT DEFAULT '{}',
            rationale TEXT DEFAULT '',
            evidence_run_ids TEXT DEFAULT '[]',
            eval_before_job_id VARCHAR DEFAULT '',
            eval_after_job_id VARCHAR DEFAULT '',
            eval_report_json TEXT DEFAULT '{}',
            status VARCHAR(32) DEFAULT 'drafted',
            created_at DATETIME,
            updated_at DATETIME
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS selfopt_ab_experiments (
            experiment_id VARCHAR PRIMARY KEY,
            agent_id VARCHAR NOT NULL,
            proposal_id VARCHAR,
            control_version_id VARCHAR NOT NULL,
            treatment_version_id VARCHAR NOT NULL,
            strategy VARCHAR(32) DEFAULT 'round_robin',
            rr_counter INTEGER DEFAULT 0,
            status VARCHAR(32) DEFAULT 'running',
            started_at DATETIME,
            ended_at DATETIME,
            min_sessions INTEGER DEFAULT 10,
            target_sessions INTEGER DEFAULT 40,
            decision VARCHAR(32) DEFAULT 'pending',
            decided_by VARCHAR(128) DEFAULT '',
            decided_at DATETIME,
            decision_note TEXT DEFAULT '',
            created_at DATETIME
        )
        """,
    ):
        cursor.execute(table_sql)

    # SelfOpt column migrations
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='agents'")
    if cursor.fetchone():
        cursor.execute("PRAGMA table_info(agents)")
        agent_cols = {row[1] for row in cursor.fetchall()}
        if "selfopt_enabled" not in agent_cols:
            cursor.execute("ALTER TABLE agents ADD COLUMN selfopt_enabled BOOLEAN")

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'")
    if cursor.fetchone():
        cursor.execute("PRAGMA table_info(sessions)")
        sess_cols = {row[1] for row in cursor.fetchall()}
        if "ab_experiment_id" not in sess_cols:
            cursor.execute("ALTER TABLE sessions ADD COLUMN ab_experiment_id VARCHAR")
        if "ab_arm" not in sess_cols:
            cursor.execute("ALTER TABLE sessions ADD COLUMN ab_arm VARCHAR(16)")

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='agent_runs'")
    if cursor.fetchone():
        cursor.execute("PRAGMA table_info(agent_runs)")
        run_cols = {row[1] for row in cursor.fetchall()}
        if "ab_experiment_id" not in run_cols:
            cursor.execute("ALTER TABLE agent_runs ADD COLUMN ab_experiment_id VARCHAR")
        if "ab_arm" not in run_cols:
            cursor.execute("ALTER TABLE agent_runs ADD COLUMN ab_arm VARCHAR(16)")

    # SelfOptJob.job_label migration + backfill
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='selfopt_jobs'")
    if cursor.fetchone():
        cursor.execute("PRAGMA table_info(selfopt_jobs)")
        job_cols = {row[1] for row in cursor.fetchall()}
        if "job_label" not in job_cols:
            cursor.execute("ALTER TABLE selfopt_jobs ADD COLUMN job_label VARCHAR(256)")
        # Backfill missing labels: {agent_name|agent_id短码}-{YYYYMMDD}-{seq}
        cursor.execute(
            """
            SELECT j.job_id, j.agent_id, j.created_at, a.name
            FROM selfopt_jobs j
            LEFT JOIN agents a ON a.agent_id = j.agent_id
            WHERE j.job_label IS NULL OR j.job_label = ''
            ORDER BY j.agent_id, j.created_at ASC
            """
        )
        rows = cursor.fetchall()
        day_seq: dict = {}
        for job_id, agent_id, created_at, agent_name in rows:
            name_part = (agent_name or "").strip() or (str(agent_id or "")[:8] or "agent")
            # Normalize created_at to YYYYMMDD
            date_str = ""
            if created_at:
                s = str(created_at).replace("T", " ").replace("-", "")
                date_str = s[:8] if len(s) >= 8 else ""
            if not date_str or not date_str.isdigit():
                from datetime import datetime, timezone

                date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
            key = (agent_id, date_str)
            day_seq[key] = day_seq.get(key, 0) + 1
            label = f"{name_part}-{date_str}-{day_seq[key]:02d}"
            cursor.execute(
                "UPDATE selfopt_jobs SET job_label = ? WHERE job_id = ?",
                (label, job_id),
            )

    conn.commit()
    conn.close()
