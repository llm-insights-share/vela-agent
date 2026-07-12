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
        DataQueryAgent, DataQueryDatasourceBinding, DataQueryExecutionLog,
        DataTableDictionary, DataDictionaryItem, DataCodeMapping, DataQueryExample, DataTermMapping,
        DataQueryFeedback, DataQueryQualityStats,
        MemoryEpisode, MemoryRecord,
        ScreenSystem, ScreenCredential, ScreenSession, UiAuditLog, UiSkill, UiSkillStep,
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

    conn.commit()
    conn.close()