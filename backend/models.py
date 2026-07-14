import uuid
import json
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, Text, ForeignKey, JSON, Enum as SAEnum
from sqlalchemy.orm import relationship
from database import Base
import enum


def gen_uuid():
    return str(uuid.uuid4())


def now_utc():
    return datetime.now(timezone.utc)


class AgentStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    TESTING = "TESTING"
    PUBLISHED = "PUBLISHED"
    DEPRECATED = "DEPRECATED"
    DELETED = "DELETED"


class AgentType(str, enum.Enum):
    SINGLE = "SINGLE"       # 单体 Agent
    COMPOSITE = "COMPOSITE" # 多 Agent 编排
    WORKFLOW = "WORKFLOW"   # 工作流型


class VersionStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    TESTING = "TESTING"
    PUBLISHED = "PUBLISHED"
    DEPRECATED = "DEPRECATED"


class ChangeType(str, enum.Enum):
    MAJOR = "MAJOR"
    MINOR = "MINOR"
    PATCH = "PATCH"


class ProviderStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    ERROR = "ERROR"


class ModelServiceStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    ERROR = "ERROR"


class SkillPackStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"
    ARCHIVED = "ARCHIVED"


class KnowledgeBaseStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INDEXING = "INDEXING"
    DEPRECATED = "DEPRECATED"
    ARCHIVED = "ARCHIVED"


class SessionStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    RUNNING = "RUNNING"
    HITL_WAIT = "HITL_WAIT"
    IDLE = "IDLE"
    CLOSED = "CLOSED"
    ERROR = "ERROR"


class ModelProvider(Base):
    __tablename__ = "model_providers"

    provider_id = Column(String, primary_key=True, default=gen_uuid)
    provider_code = Column(String(32), unique=True, nullable=False, index=True)
    display_name = Column(String(128), nullable=False)
    base_url = Column(String(512), nullable=False)
    api_key = Column(String(512), nullable=False, default="")
    extra_headers = Column(JSON, default=dict)
    timeout_seconds = Column(Integer, default=120)
    max_retries = Column(Integer, default=3)
    status = Column(SAEnum(ProviderStatus), default=ProviderStatus.ACTIVE)
    health_check_interval = Column(Integer, default=300)
    created_at = Column(DateTime, default=now_utc)
    updated_at = Column(DateTime, default=now_utc, onupdate=now_utc)

    services = relationship("ModelService", back_populates="provider", cascade="all, delete-orphan")


class ModelService(Base):
    __tablename__ = "model_services"

    model_service_id = Column(String, primary_key=True, default=gen_uuid)
    provider_id = Column(String, ForeignKey("model_providers.provider_id"), nullable=False)
    model_name = Column(String(256), nullable=False)
    display_name = Column(String(256), nullable=False)
    max_tokens = Column(Integer, default=4096)
    capabilities = Column(JSON, default=list)
    status = Column(SAEnum(ModelServiceStatus), default=ModelServiceStatus.ACTIVE)
    created_at = Column(DateTime, default=now_utc)
    updated_at = Column(DateTime, default=now_utc, onupdate=now_utc)

    provider = relationship("ModelProvider", back_populates="services")


class Agent(Base):
    __tablename__ = "agents"

    agent_id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String(128), unique=True, nullable=False, index=True)
    description = Column(Text, default="")
    model_service_id = Column(String, ForeignKey("model_services.model_service_id"), nullable=False)
    system_prompt = Column(Text, default="")
    dept_id = Column(String(128), default="")
    autonomy_level = Column(String(8), default="L2")
    max_concurrent_sessions = Column(Integer, default=5)
    token_budget = Column(Integer, default=100000)
    tool_permissions = Column(JSON, default=dict)
    tags = Column(JSON, default=list)
    status = Column(SAEnum(AgentStatus), default=AgentStatus.DRAFT)
    current_version_id = Column(String, nullable=True)
    # MA: Agent 类型与编排配置
    agent_type = Column(SAEnum(AgentType), default=AgentType.SINGLE)
    composition_config = Column(JSON, default=dict)
    # WF: 工作流画布定义
    workflow_definition = Column(JSON, default=dict)
    # SGL-CFG-02: ReAct 最大迭代次数
    max_iterations = Column(Integer, default=10)
    # SGL-CFG-03: 单步超时时间（秒）
    step_timeout_seconds = Column(Integer, default=60)
    # SGL-CFG-04: 工具失败重试次数
    tool_retry_count = Column(Integer, default=2)
    # SGL-CFG-04: 退避策略 fixed/exponential
    tool_retry_backoff = Column(String(16), default="fixed")
    # SGL-CFG-05: 是否允许连续调用同一工具（防死循环开关）
    allow_repeat_tool_calls = Column(Boolean, default=True)
    # SGL-CFG-05: 连续相同调用阈值
    max_repeat_threshold = Column(Integer, default=3)
    # SGL-CFG-07: 单次调用 Token 上限
    single_call_token_limit = Column(Integer, default=8192)
    # 记忆模块：是否挂载闭环记忆（自我记录/处理/检索）
    memory_enabled = Column(Boolean, default=False)
    # Query 改写引擎：是否在检索/工具前按需改写用户输入
    query_rewrite_enabled = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now_utc)
    updated_at = Column(DateTime, default=now_utc, onupdate=now_utc)

    versions = relationship("AgentVersion", back_populates="agent", cascade="all, delete-orphan",
                            foreign_keys="AgentVersion.agent_id")


class AgentVersion(Base):
    __tablename__ = "agent_versions"

    version_id = Column(String, primary_key=True, default=gen_uuid)
    agent_id = Column(String, ForeignKey("agents.agent_id"), nullable=False)
    version = Column(String(32), nullable=False)
    version_seq = Column(Integer, default=1)
    change_type = Column(SAEnum(ChangeType), default=ChangeType.PATCH)
    change_summary = Column(Text, default="")
    snapshot = Column(JSON, default=dict)
    status = Column(SAEnum(VersionStatus), default=VersionStatus.DRAFT)
    created_at = Column(DateTime, default=now_utc)

    agent = relationship("Agent", back_populates="versions", foreign_keys=[agent_id])


class SkillPack(Base):
    __tablename__ = "skill_packs"

    skill_pack_id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String(128), unique=True, nullable=False, index=True)
    version = Column(String(32), default="1.0.0")
    scope = Column(String(32), default="platform")
    tools = Column(JSON, default=list)
    description = Column(Text, default="")
    manifest = Column(JSON, default=dict)
    skill_content = Column(Text, default="")
    status = Column(SAEnum(SkillPackStatus), default=SkillPackStatus.ACTIVE)
    created_at = Column(DateTime, default=now_utc)
    updated_at = Column(DateTime, default=now_utc, onupdate=now_utc)


class AgentSkillBinding(Base):
    __tablename__ = "agent_skill_bindings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(String, ForeignKey("agents.agent_id"), nullable=False)
    skill_pack_id = Column(String, ForeignKey("skill_packs.skill_pack_id"), nullable=False)
    tool_permissions = Column(JSON, default=dict)
    created_at = Column(DateTime, default=now_utc)


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    kb_id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String(128), unique=True, nullable=False, index=True)
    description = Column(Text, default="")
    kb_type = Column(String(32), default="document")
    scope = Column(String(32), default="platform")
    version = Column(String(32), default="1.0.0")
    doc_count = Column(Integer, default=0)
    status = Column(SAEnum(KnowledgeBaseStatus), default=KnowledgeBaseStatus.ACTIVE)
    faiss_index_path = Column(String(512), default="")
    created_at = Column(DateTime, default=now_utc)
    updated_at = Column(DateTime, default=now_utc, onupdate=now_utc)


class AgentKnowledgeBinding(Base):
    __tablename__ = "agent_knowledge_bindings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(String, ForeignKey("agents.agent_id"), nullable=False)
    kb_id = Column(String, ForeignKey("knowledge_bases.kb_id"), nullable=False)
    created_at = Column(DateTime, default=now_utc)


class Session(Base):
    __tablename__ = "sessions"

    session_id = Column(String, primary_key=True, default=gen_uuid)
    agent_id = Column(String, ForeignKey("agents.agent_id"), nullable=False)
    version_id = Column(String, ForeignKey("agent_versions.version_id"), nullable=True)
    caller_type = Column(String(32), default="USER")
    caller_id = Column(String(128), default="")
    status = Column(SAEnum(SessionStatus), default=SessionStatus.ACTIVE)
    token_used = Column(Integer, default=0)
    token_budget = Column(Integer, default=100000)
    ttl_seconds = Column(Integer, default=1800)
    messages = Column(JSON, default=list)
    # SGL-CFG-06 / MA-IMP-09: HITL 挂起上下文（pending_tool_call / pending_delivery）
    pending_context = Column(JSON, default=dict)
    trace_id = Column(String(128), default="")
    created_at = Column(DateTime, default=now_utc)
    last_active_at = Column(DateTime, default=now_utc)


class ToolType(str, enum.Enum):
    MCP = "mcp"
    RESTFUL = "restful"
    LOCAL_PYTHON = "local_python"


class ToolStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    ERROR = "ERROR"


class Tool(Base):
    __tablename__ = "tools"

    tool_id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String(128), unique=True, nullable=False, index=True)
    display_name = Column(String(256), default="")
    description = Column(Text, default="")
    tool_type = Column(SAEnum(ToolType), nullable=False)
    config = Column(JSON, default=dict)
    parameters_schema = Column(JSON, default=dict)
    status = Column(SAEnum(ToolStatus), default=ToolStatus.ACTIVE)
    created_at = Column(DateTime, default=now_utc)
    updated_at = Column(DateTime, default=now_utc, onupdate=now_utc)


class AgentToolBinding(Base):
    __tablename__ = "agent_tool_bindings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(String, ForeignKey("agents.agent_id"), nullable=False)
    tool_id = Column(String, ForeignKey("tools.tool_id"), nullable=False)
    permission = Column(String(16), default="allowed")
    # SGL-CFG-06: 该工具调用前是否需要人工审批
    require_approval = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now_utc)


class AgentComposition(Base):
    """MA: 多 Agent 编排关系表"""
    __tablename__ = "agent_compositions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    parent_agent_id = Column(String, ForeignKey("agents.agent_id"), nullable=False, index=True)
    child_agent_id = Column(String, ForeignKey("agents.agent_id"), nullable=False)
    role_name = Column(String(128), nullable=False)
    role_description = Column(Text, default="")
    task_keywords = Column(JSON, default=list)
    created_at = Column(DateTime, default=now_utc)


class AuditLog(Base):
    """审计日志表"""
    __tablename__ = "audit_logs"

    log_id = Column(String, primary_key=True, default=gen_uuid)
    agent_id = Column(String, index=True)
    session_id = Column(String, index=True)
    event_type = Column(String(64))
    event_data = Column(JSON, default=dict)
    tokens_used = Column(Integer, default=0)
    duration_ms = Column(Integer, default=0)
    trace_id = Column(String(128), index=True)
    created_at = Column(DateTime, default=now_utc)


class HITLApproval(Base):
    """HITL 人工审批工单"""
    __tablename__ = "hitl_approvals"

    approval_id = Column(String, primary_key=True, default=gen_uuid)
    session_id = Column(String, ForeignKey("sessions.session_id"), nullable=False, index=True)
    agent_id = Column(String, nullable=False)
    tool_name = Column(String(128), nullable=False)
    tool_args = Column(JSON, default=dict)
    status = Column(String(16), default="PENDING")  # PENDING / APPROVED / REJECTED
    reviewer = Column(String(128), default="")
    review_comment = Column(Text, default="")
    created_at = Column(DateTime, default=now_utc)
    reviewed_at = Column(DateTime, nullable=True)


class DataQueryAgentStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DEPRECATED = "DEPRECATED"


class DataQueryDatasourceStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    ERROR = "ERROR"


class DataQueryExecutionStatus(str, enum.Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class DataQueryAgent(Base):
    __tablename__ = "dataquery_agents"

    dq_agent_id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String(128), unique=True, nullable=False, index=True)
    description = Column(Text, default="")
    model_service_id = Column(String, ForeignKey("model_services.model_service_id"), nullable=False)
    planner_model_service_id = Column(String, ForeignKey("model_services.model_service_id"), nullable=True)
    sql_model_service_id = Column(String, ForeignKey("model_services.model_service_id"), nullable=True)
    temperature = Column(Float, default=0.1)
    max_tokens = Column(Integer, default=2048)
    default_limit = Column(Integer, default=200)
    timeout_seconds = Column(Integer, default=30)
    strict_mode = Column(Boolean, default=True)
    allow_cross_datasource = Column(Boolean, default=False)
    status = Column(SAEnum(DataQueryAgentStatus), default=DataQueryAgentStatus.ACTIVE)
    created_at = Column(DateTime, default=now_utc)
    updated_at = Column(DateTime, default=now_utc, onupdate=now_utc)


class DataQueryDatasourceBinding(Base):
    __tablename__ = "dataquery_datasource_bindings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dq_agent_id = Column(String, ForeignKey("dataquery_agents.dq_agent_id"), nullable=False, index=True)
    datasource_id = Column(String(128), nullable=False, index=True)
    datasource_name = Column(String(256), default="")
    db_type = Column(String(32), default="sqlite")
    db_url = Column(String(1024), default="")
    schema_name = Column(String(128), default="")
    table_whitelist = Column(JSON, default=list)
    sensitive_columns = Column(JSON, default=list)
    default_limit = Column(Integer, default=200)
    timeout_seconds = Column(Integer, default=30)
    status = Column(SAEnum(DataQueryDatasourceStatus), default=DataQueryDatasourceStatus.ACTIVE)
    created_at = Column(DateTime, default=now_utc)
    updated_at = Column(DateTime, default=now_utc, onupdate=now_utc)


class DataQueryExecutionLog(Base):
    __tablename__ = "dataquery_execution_logs"

    log_id = Column(String, primary_key=True, default=gen_uuid)
    dq_agent_id = Column(String, ForeignKey("dataquery_agents.dq_agent_id"), nullable=False, index=True)
    datasource_id = Column(String(128), index=True)
    session_id = Column(String(128), index=True)
    question = Column(Text, default="")
    normalized_question = Column(Text, default="")
    generated_sql = Column(Text, default="")
    execution_status = Column(SAEnum(DataQueryExecutionStatus), default=DataQueryExecutionStatus.SUCCESS)
    error_message = Column(Text, default="")
    rows = Column(Integer, default=0)
    duration_ms = Column(Integer, default=0)
    tokens_used = Column(Integer, default=0)
    applied_terms = Column(JSON, default=list)
    applied_mappings = Column(JSON, default=list)
    feedback_score = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=now_utc)


class DataTableDictionary(Base):
    __tablename__ = "dataquery_table_dictionary"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dq_agent_id = Column(String, ForeignKey("dataquery_agents.dq_agent_id"), nullable=False, index=True)
    datasource_id = Column(String(128), nullable=False, index=True)
    table_name = Column(String(128), nullable=False, index=True)
    business_name = Column(String(256), default="")
    description = Column(Text, default="")
    synonyms = Column(JSON, default=list)
    created_at = Column(DateTime, default=now_utc)
    updated_at = Column(DateTime, default=now_utc, onupdate=now_utc)


class DataDictionaryItem(Base):
    __tablename__ = "dataquery_dictionary_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dq_agent_id = Column(String, ForeignKey("dataquery_agents.dq_agent_id"), nullable=False, index=True)
    datasource_id = Column(String(128), nullable=False, index=True)
    table_name = Column(String(128), nullable=False, index=True)
    column_name = Column(String(128), nullable=False, index=True)
    business_name = Column(String(256), default="")
    description = Column(Text, default="")
    value_type = Column(String(64), default="string")
    synonyms = Column(JSON, default=list)
    metric_formula = Column(Text, default="")
    created_at = Column(DateTime, default=now_utc)
    updated_at = Column(DateTime, default=now_utc, onupdate=now_utc)


class DataCodeMapping(Base):
    __tablename__ = "dataquery_code_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dq_agent_id = Column(String, ForeignKey("dataquery_agents.dq_agent_id"), nullable=False, index=True)
    datasource_id = Column(String(128), nullable=False, index=True)
    table_name = Column(String(128), default="")
    column_name = Column(String(128), nullable=False, index=True)
    code_value = Column(String(128), nullable=False, index=True)
    display_name = Column(String(256), nullable=False)
    aliases = Column(JSON, default=list)
    effective_from = Column(DateTime, nullable=True)
    effective_to = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=now_utc)
    updated_at = Column(DateTime, default=now_utc, onupdate=now_utc)


class DataQueryExample(Base):
    __tablename__ = "dataquery_examples"

    example_id = Column(String, primary_key=True, default=gen_uuid)
    dq_agent_id = Column(String, ForeignKey("dataquery_agents.dq_agent_id"), nullable=False, index=True)
    datasource_id = Column(String(128), nullable=False, index=True)
    intent_tag = Column(String(128), default="", index=True)
    nl_question = Column(Text, nullable=False)
    sql_template = Column(Text, nullable=False)
    variables = Column(JSON, default=dict)
    explanation = Column(Text, default="")
    quality_score = Column(Float, default=0.0)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now_utc)
    updated_at = Column(DateTime, default=now_utc, onupdate=now_utc)


class DataTermMapping(Base):
    __tablename__ = "dataquery_term_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dq_agent_id = Column(String, ForeignKey("dataquery_agents.dq_agent_id"), nullable=False, index=True)
    source_term = Column(String(256), nullable=False, index=True)
    normalized_term = Column(String(256), nullable=False)
    mapping_type = Column(String(32), default="synonym")
    priority = Column(Integer, default=100)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now_utc)
    updated_at = Column(DateTime, default=now_utc, onupdate=now_utc)


class DataQueryFeedback(Base):
    __tablename__ = "dataquery_feedback"

    feedback_id = Column(String, primary_key=True, default=gen_uuid)
    log_id = Column(String, ForeignKey("dataquery_execution_logs.log_id"), nullable=False, index=True)
    dq_agent_id = Column(String, ForeignKey("dataquery_agents.dq_agent_id"), nullable=False, index=True)
    session_id = Column(String(128), index=True)
    rating = Column(Integer, default=0)  # 1-5
    comment = Column(Text, default="")
    created_at = Column(DateTime, default=now_utc)


class DataQueryQualityStats(Base):
    __tablename__ = "dataquery_quality_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dq_agent_id = Column(String, ForeignKey("dataquery_agents.dq_agent_id"), nullable=False, index=True)
    stat_date = Column(String(16), nullable=False, index=True)  # YYYY-MM-DD
    total_queries = Column(Integer, default=0)
    success_queries = Column(Integer, default=0)
    failed_queries = Column(Integer, default=0)
    avg_duration_ms = Column(Float, default=0.0)
    avg_feedback_score = Column(Float, default=0.0)
    updated_at = Column(DateTime, default=now_utc, onupdate=now_utc)


class MemoryEpisode(Base):
    """L1 情景记忆：原始交互事件归档"""
    __tablename__ = "memory_episodes"

    episode_id = Column(String, primary_key=True, default=gen_uuid)
    agent_id = Column(String, ForeignKey("agents.agent_id"), nullable=False, index=True)
    session_id = Column(String, index=True, default="")
    user_id = Column(String(128), default="", index=True)
    event_type = Column(String(64), nullable=False, index=True)
    payload = Column(JSON, default=dict)
    created_at = Column(DateTime, default=now_utc, index=True)


class MemoryRecord(Base):
    """L2/溯源语义记忆：双时态提交"""
    __tablename__ = "memory_records"

    record_id = Column(String, primary_key=True, default=gen_uuid)
    agent_id = Column(String, ForeignKey("agents.agent_id"), nullable=False, index=True)
    user_id = Column(String(128), default="", index=True)
    # user_pref | task_summary | experience | tool_profile | provenance
    memory_type = Column(String(32), nullable=False, index=True)
    content = Column(Text, nullable=False, default="")
    meta = Column("metadata", JSON, default=dict)
    source_episode_ids = Column(JSON, default=list)
    status = Column(String(16), default="active", index=True)  # active | superseded
    valid_from = Column(DateTime, default=now_utc)
    valid_to = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=now_utc)
    updated_at = Column(DateTime, default=now_utc, onupdate=now_utc)
    created_by = Column(String(128), default="system")


# --- ScreenPilot (驭屏引擎) ---


class ScreenSystem(Base):
    """目标系统注册表"""
    __tablename__ = "screen_systems"

    system_id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String(128), nullable=False, unique=True)
    entry_url = Column(String(512), nullable=False, default="")
    login_type = Column(String(32), default="form")  # form | sso | cas
    exec_mode = Column(String(16), default="browser")  # browser | desktop
    allowed_domains = Column(JSON, default=list)
    login_macro = Column(JSON, default=dict)
    risk_rules = Column(JSON, default=dict)
    status = Column(String(16), default="ACTIVE")
    created_at = Column(DateTime, default=now_utc)
    updated_at = Column(DateTime, default=now_utc, onupdate=now_utc)


class ScreenCredential(Base):
    """ScreenPilot 系统凭证 KV（value Fernet 加密）"""
    __tablename__ = "screen_credentials"

    credential_id = Column(String, primary_key=True, default=gen_uuid)
    system_id = Column(String, ForeignKey("screen_systems.system_id"), nullable=False, index=True)
    name = Column(String(128), nullable=False, default="")
    value_enc = Column(Text, default="")
    created_at = Column(DateTime, default=now_utc)
    updated_at = Column(DateTime, default=now_utc, onupdate=now_utc)


class ScreenSession(Base):
    """Playwright 浏览器会话"""
    __tablename__ = "screen_sessions"

    screen_session_id = Column(String, primary_key=True, default=gen_uuid)
    system_id = Column(String, ForeignKey("screen_systems.system_id"), nullable=False, index=True)
    vela_session_id = Column(String, index=True, default="")
    agent_id = Column(String, default="")
    status = Column(String(16), default="ACTIVE")  # ACTIVE | CLOSED | ERROR
    current_url = Column(String(1024), default="")
    meta = Column(JSON, default=dict)
    created_at = Column(DateTime, default=now_utc)
    updated_at = Column(DateTime, default=now_utc, onupdate=now_utc)


class UiAuditLog(Base):
    """ScreenPilot 操作审计"""
    __tablename__ = "ui_audit_logs"

    log_id = Column(String, primary_key=True, default=gen_uuid)
    screen_session_id = Column(String, index=True, default="")
    vela_session_id = Column(String, index=True, default="")
    agent_id = Column(String, default="")
    action = Column(String(64), default="")
    risk_tier = Column(String(8), default="T0")
    payload = Column(JSON, default=dict)
    screenshot_path = Column(String(512), default="")
    screenshot_hash = Column(String(64), default="")
    verification = Column(JSON, default=dict)
    approval_id = Column(String, default="")
    prev_hash = Column(String(64), default="")
    content_hash = Column(String(64), default="")
    created_at = Column(DateTime, default=now_utc)


class UiSkill(Base):
    """UI 技能模板（SKL 层）"""
    __tablename__ = "ui_skills"

    skill_id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")
    system_id = Column(String, ForeignKey("screen_systems.system_id"), nullable=False, index=True)
    scope = Column(String(64), default="default", index=True)
    param_schema = Column(JSON, default=dict)
    status = Column(String(16), default="ACTIVE")
    visibility = Column(String(16), default="PRIVATE", index=True)  # PRIVATE | DEPARTMENT | PUBLIC
    publisher_id = Column(String(128), default="")
    published_at = Column(DateTime, nullable=True)
    source_session_id = Column(String, default="")
    created_at = Column(DateTime, default=now_utc)
    updated_at = Column(DateTime, default=now_utc, onupdate=now_utc)


class UiSkillStep(Base):
    """技能步骤与选择器指纹"""
    __tablename__ = "ui_skill_steps"

    step_id = Column(String, primary_key=True, default=gen_uuid)
    skill_id = Column(String, ForeignKey("ui_skills.skill_id"), nullable=False, index=True)
    step_order = Column(Integer, nullable=False, default=0)
    system_id = Column(String, default="")
    action = Column(String(32), nullable=False)
    target_label = Column(String(256), default="")
    value_template = Column(String(1024), default="")
    fingerprints = Column(JSON, default=dict)
    meta = Column(JSON, default=dict)
    created_at = Column(DateTime, default=now_utc)