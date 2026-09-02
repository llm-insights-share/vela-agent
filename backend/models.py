import uuid
import json
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, Text, ForeignKey, JSON, Enum as SAEnum, UniqueConstraint
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


class User(Base):
    __tablename__ = "users"

    user_id = Column(String, primary_key=True, default=gen_uuid)
    username = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(256), unique=True, nullable=False, index=True)
    display_name = Column(String(128), nullable=False, default="")
    avatar_url = Column(String(512), default="")
    hashed_password = Column(String(256), nullable=False)
    roles = Column(String(128), nullable=False, default="member")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now_utc)
    updated_at = Column(DateTime, default=now_utc, onupdate=now_utc)


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
    # SGL-CFG-08: 整体对话超时（秒）
    timeout_seconds = Column(Integer, default=180)
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
    package_files = Column(JSON, default=dict)
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
    contextual_retrieval_enabled = Column(Boolean, nullable=True, default=None)
    tag_defs = Column(JSON, default=list)
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
    title = Column(String(128), default="")
    messages = Column(JSON, default=list)
    llm_calls = Column(JSON, default=list)
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
    mcp_server_id = Column(String, ForeignKey("mcp_servers.server_id"), nullable=True, index=True)
    created_at = Column(DateTime, default=now_utc)
    updated_at = Column(DateTime, default=now_utc, onupdate=now_utc)

    mcp_server = relationship("McpServer", back_populates="tools")


class ConnectorStatus(str, enum.Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTED = "CONNECTED"
    ERROR = "ERROR"


class UserConnector(Base):
    __tablename__ = "user_connectors"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_user_connector_name"),)

    connector_id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False, index=True)
    catalog_key = Column(String(32), nullable=True, index=True)
    name = Column(String(128), nullable=False)
    display_name = Column(String(256), default="")
    description = Column(Text, default="")
    mcp_server_id = Column(String, ForeignKey("mcp_servers.server_id"), nullable=False, unique=True, index=True)
    connector_config = Column(JSON, default=dict)
    status = Column(SAEnum(ConnectorStatus), default=ConnectorStatus.DISCONNECTED)
    last_error = Column(Text, default="")
    tool_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=now_utc)
    updated_at = Column(DateTime, default=now_utc, onupdate=now_utc)

    mcp_server = relationship("McpServer", back_populates="user_connector")


class McpServer(Base):
    __tablename__ = "mcp_servers"

    server_id = Column(String, primary_key=True, default=gen_uuid)
    owner_user_id = Column(String, ForeignKey("users.user_id"), nullable=True, index=True)
    name = Column(String(128), unique=True, nullable=False, index=True)
    display_name = Column(String(256), default="")
    description = Column(Text, default="")
    transport = Column(String(32), nullable=False, default="stdio")
    command = Column(String(256), default="")
    args = Column(JSON, default=list)
    env = Column(JSON, default=dict)
    url = Column(String(1024), default="")
    headers = Column(JSON, default=dict)
    auth_type = Column(String(16), default="none")
    status = Column(String(16), default="ACTIVE")
    last_synced_at = Column(DateTime, nullable=True)
    last_error = Column(Text, default="")
    created_at = Column(DateTime, default=now_utc)
    updated_at = Column(DateTime, default=now_utc, onupdate=now_utc)

    tools = relationship("Tool", back_populates="mcp_server")
    oauth_credential = relationship("McpOAuthCredential", back_populates="server", uselist=False, cascade="all, delete-orphan")
    user_connector = relationship("UserConnector", back_populates="mcp_server", uselist=False, cascade="all, delete-orphan")


class McpOAuthCredential(Base):
    __tablename__ = "mcp_oauth_credentials"

    credential_id = Column(String, primary_key=True, default=gen_uuid)
    server_id = Column(String, ForeignKey("mcp_servers.server_id"), nullable=False, unique=True, index=True)
    client_id = Column(String(256), default="")
    client_secret_enc = Column(Text, default="")
    authorization_endpoint = Column(String(1024), default="")
    token_endpoint = Column(String(1024), default="")
    registration_endpoint = Column(String(1024), default="")
    resource = Column(String(1024), default="")
    redirect_uri = Column(String(1024), default="")
    access_token_enc = Column(Text, default="")
    refresh_token_enc = Column(Text, default="")
    token_type = Column(String(32), default="Bearer")
    scope = Column(String(512), default="")
    expires_at = Column(DateTime, nullable=True)
    as_metadata_json = Column(Text, default="")
    created_at = Column(DateTime, default=now_utc)
    updated_at = Column(DateTime, default=now_utc, onupdate=now_utc)

    server = relationship("McpServer", back_populates="oauth_credential")


class McpOAuthState(Base):
    __tablename__ = "mcp_oauth_states"

    state = Column(String(128), primary_key=True)
    server_id = Column(String, ForeignKey("mcp_servers.server_id"), nullable=False, index=True)
    code_verifier = Column(String(256), default="")
    redirect_uri = Column(String(1024), default="")
    frontend_redirect = Column(String(1024), default="")
    created_at = Column(DateTime, default=now_utc)
    expires_at = Column(DateTime, nullable=False)


class AgentToolBinding(Base):
    __tablename__ = "agent_tool_bindings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(String, ForeignKey("agents.agent_id"), nullable=False)
    tool_id = Column(String, ForeignKey("tools.tool_id"), nullable=False)
    permission = Column(String(16), default="allowed")
    # SGL-CFG-06: 该工具调用前是否需要人工审批
    require_approval = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now_utc)


class AgentConnectorBinding(Base):
    """Agent 允许使用的连接器类型（按 catalog_key）及工具级策略。"""
    __tablename__ = "agent_connector_bindings"
    __table_args__ = (
        UniqueConstraint("agent_id", "catalog_key", name="uq_agent_connector_catalog"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(String, ForeignKey("agents.agent_id"), nullable=False, index=True)
    catalog_key = Column(String(64), nullable=False)
    # { mcp_tool_name: { enabled: bool, require_approval: bool } }
    tool_policies = Column(JSON, default=dict)
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


class ScheduleTriggerType(str, enum.Enum):
    CRON = "CRON"
    MANUAL = "MANUAL"


class ScheduleRunStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    HITL_WAIT = "HITL_WAIT"
    SKIPPED = "SKIPPED"


class AgentSchedule(Base):
    __tablename__ = "agent_schedules"

    schedule_id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String(128), unique=True, nullable=False, index=True)
    description = Column(Text, default="")
    agent_id = Column(String, ForeignKey("agents.agent_id"), nullable=False, index=True)
    enabled = Column(Boolean, default=True)
    cron_expression = Column(String(64), nullable=False, default="0 8 * * *")
    timezone = Column(String(64), nullable=False, default="Asia/Shanghai")
    prompt_template = Column(Text, default="")
    skip_if_running = Column(Boolean, default=True)
    timeout_seconds = Column(Integer, nullable=True)
    created_by = Column(String(128), default="")
    last_fired_at = Column(DateTime, nullable=True)
    next_run_at = Column(DateTime, nullable=True)
    last_status = Column(String(32), default="")
    created_at = Column(DateTime, default=now_utc)
    updated_at = Column(DateTime, default=now_utc, onupdate=now_utc)


class AgentScheduleRun(Base):
    __tablename__ = "agent_schedule_runs"

    run_id = Column(String, primary_key=True, default=gen_uuid)
    schedule_id = Column(String, ForeignKey("agent_schedules.schedule_id"), nullable=False, index=True)
    session_id = Column(String, ForeignKey("sessions.session_id"), nullable=True, index=True)
    trigger_type = Column(SAEnum(ScheduleTriggerType), default=ScheduleTriggerType.CRON)
    status = Column(SAEnum(ScheduleRunStatus), default=ScheduleRunStatus.PENDING)
    scheduled_for = Column(DateTime, nullable=False, default=now_utc)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    prompt_rendered = Column(Text, default="")
    error_message = Column(Text, default="")
    token_used = Column(Integer, default=0)
    summary = Column(Text, default="")
    created_at = Column(DateTime, default=now_utc)


class InboxMessage(Base):
    __tablename__ = "inbox_messages"
    __table_args__ = (
        UniqueConstraint("user_id", "related_type", "related_id", name="uq_inbox_user_related"),
    )

    message_id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, nullable=False, index=True)
    title = Column(String(256), nullable=False, default="")
    body = Column(Text, default="")
    level = Column(String(16), default="info")
    link_path = Column(String(512), default="")
    related_type = Column(String(64), default="")
    related_id = Column(String(128), default="")
    is_read = Column(Boolean, default=False, index=True)
    read_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=now_utc)


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
    business_scope = Column(Text, default="")
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
    """L2/溯源语义记忆：双时态提交（保留表；新写入走 Letta）"""
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


class LettaMemoryAgent(Base):
    """vela Agent(+user) → Letta 记忆 agent 映射"""
    __tablename__ = "letta_memory_agents"
    __table_args__ = (
        UniqueConstraint("agent_id", "user_id", name="uq_letta_memory_agent_scope"),
    )

    mapping_id = Column(String, primary_key=True, default=gen_uuid)
    agent_id = Column(String, ForeignKey("agents.agent_id"), nullable=False, index=True)
    user_id = Column(String(128), default="", index=True)
    letta_agent_id = Column(String(128), nullable=False, index=True)
    created_at = Column(DateTime, default=now_utc)


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
    # CDP: reuse local Chrome/Edge profile cookies instead of launching isolated browser
    reuse_local_browser = Column(Boolean, default=False)
    cdp_url = Column(String(512), default="")
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


class CodeExecutionStatus(str, enum.Enum):
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"


class CodeExecution(Base):
    """Code Interpreter execution record."""
    __tablename__ = "code_executions"

    execution_id = Column(String, primary_key=True, default=gen_uuid)
    session_id = Column(String, index=True, nullable=False)
    agent_id = Column(String, index=True, default="")
    language = Column(String(16), default="python")
    code = Column(Text, default="")
    stdout = Column(Text, default="")
    stderr = Column(Text, default="")
    exit_code = Column(Integer, default=0)
    duration_ms = Column(Integer, default=0)
    artifacts = Column(JSON, default=list)
    status = Column(String(16), default="SUCCESS")
    error_message = Column(Text, default="")
    created_at = Column(DateTime, default=now_utc)


# ─── Monitor & Eval (Trace Store) ───────────────────────────────────────────


class AgentRunStatus(str, enum.Enum):
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    HITL_WAIT = "HITL_WAIT"
    ABORT = "ABORT"
    TIMEOUT = "TIMEOUT"


class AgentRun(Base):
    """一次用户消息 → 助手完成（或 ERROR/HITL/ABORT）的根 Trace 记录。"""
    __tablename__ = "agent_runs"

    run_id = Column(String, primary_key=True, default=gen_uuid)
    session_id = Column(String, ForeignKey("sessions.session_id"), nullable=False, index=True)
    agent_id = Column(String, ForeignKey("agents.agent_id"), nullable=False, index=True)
    version_id = Column(String, ForeignKey("agent_versions.version_id"), nullable=True)
    trace_id = Column(String(128), default="", index=True)
    caller_id = Column(String(128), default="")
    status = Column(String(32), default=AgentRunStatus.SUCCESS.value, index=True)
    started_at = Column(DateTime, default=now_utc, index=True)
    ended_at = Column(DateTime, nullable=True)
    elapsed_ms = Column(Integer, default=0)
    token_in = Column(Integer, default=0)
    token_out = Column(Integer, default=0)
    tool_calls = Column(Integer, default=0)
    execution_mode = Column(String(32), default="")
    error_code = Column(String(64), default="")
    summary = Column(Text, default="")
    message_index = Column(Integer, default=-1)
    attrs_json = Column(JSON, default=dict)
    content_sampled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now_utc)


class AgentSpan(Base):
    __tablename__ = "agent_spans"

    span_id = Column(String, primary_key=True, default=gen_uuid)
    run_id = Column(String, ForeignKey("agent_runs.run_id"), nullable=False, index=True)
    parent_span_id = Column(String, default="")
    name = Column(String(256), default="")
    kind = Column(String(32), default="internal")
    attrs_json = Column(JSON, default=dict)
    duration_ms = Column(Integer, default=0)
    status = Column(String(32), default="OK")
    started_at = Column(DateTime, default=now_utc)


class AgentScore(Base):
    __tablename__ = "agent_scores"

    score_id = Column(String, primary_key=True, default=gen_uuid)
    run_id = Column(String, ForeignKey("agent_runs.run_id"), nullable=False, index=True)
    score_name = Column(String(128), nullable=False)
    value = Column(Float, default=0.0)
    data_type = Column(String(32), default="NUMERIC")
    source = Column(String(32), default="rule")
    comment = Column(Text, default="")
    created_at = Column(DateTime, default=now_utc)


class AgentFeedback(Base):
    __tablename__ = "agent_feedback"

    feedback_id = Column(String, primary_key=True, default=gen_uuid)
    session_id = Column(String, ForeignKey("sessions.session_id"), nullable=False, index=True)
    run_id = Column(String, ForeignKey("agent_runs.run_id"), nullable=True, index=True)
    agent_id = Column(String, index=True, default="")
    message_index = Column(Integer, default=-1)
    rating = Column(Integer, default=0)
    reason = Column(Text, default="")
    user_id = Column(String(128), default="")
    created_at = Column(DateTime, default=now_utc)


class MonitorAlert(Base):
    __tablename__ = "monitor_alerts"

    alert_id = Column(String, primary_key=True, default=gen_uuid)
    rule_name = Column(String(128), nullable=False, index=True)
    severity = Column(String(16), default="warning")
    message = Column(Text, default="")
    run_id = Column(String, default="")
    agent_id = Column(String, index=True, default="")
    acknowledged = Column(Boolean, default=False)
    attrs_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=now_utc, index=True)


class EvalDataset(Base):
    __tablename__ = "eval_datasets"

    dataset_id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String(128), unique=True, nullable=False)
    description = Column(Text, default="")
    agent_id = Column(String, index=True, default="")
    tags = Column(JSON, default=list)
    created_at = Column(DateTime, default=now_utc)
    updated_at = Column(DateTime, default=now_utc, onupdate=now_utc)


class EvalCase(Base):
    __tablename__ = "eval_cases"

    case_id = Column(String, primary_key=True, default=gen_uuid)
    dataset_id = Column(String, ForeignKey("eval_datasets.dataset_id"), nullable=False, index=True)
    input_text = Column(Text, default="")
    expected_output = Column(Text, default="")
    expected_tools = Column(JSON, default=list)
    expected_keywords = Column(JSON, default=list)
    rubric = Column(Text, default="")
    source_run_id = Column(String, default="")
    created_at = Column(DateTime, default=now_utc)


class EvalJobStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class EvalJob(Base):
    __tablename__ = "eval_jobs"

    job_id = Column(String, primary_key=True, default=gen_uuid)
    dataset_id = Column(String, ForeignKey("eval_datasets.dataset_id"), nullable=False, index=True)
    agent_id = Column(String, index=True, default="")
    status = Column(String(32), default=EvalJobStatus.PENDING.value)
    pass_threshold = Column(Float, default=0.8)
    run_mode = Column(String(16), default="replay")
    evaluator_id = Column(String, default="")
    summary = Column(JSON, default=dict)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=now_utc)


class EvalJobResult(Base):
    __tablename__ = "eval_job_results"

    result_id = Column(String, primary_key=True, default=gen_uuid)
    job_id = Column(String, ForeignKey("eval_jobs.job_id"), nullable=False, index=True)
    case_id = Column(String, ForeignKey("eval_cases.case_id"), nullable=False)
    passed = Column(Boolean, default=False)
    scores = Column(JSON, default=dict)
    details = Column(JSON, default=dict)
    created_at = Column(DateTime, default=now_utc)


class EvalRuleEvaluator(Base):
    __tablename__ = "eval_rule_evaluators"

    evaluator_id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String(128), nullable=False)
    agent_id = Column(String, index=True, default="")
    enabled = Column(Boolean, default=True)
    rules_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=now_utc)
    updated_at = Column(DateTime, default=now_utc, onupdate=now_utc)


class EvalJudgeEvaluator(Base):
    __tablename__ = "eval_judge_evaluators"

    evaluator_id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String(128), nullable=False)
    agent_id = Column(String, index=True, default="")
    enabled = Column(Boolean, default=True)
    sample_rate = Column(Float, default=0.1)
    prompt_template = Column(Text, default="")
    model_service_id = Column(String, default="")
    created_at = Column(DateTime, default=now_utc)
    updated_at = Column(DateTime, default=now_utc, onupdate=now_utc)


class MonitorAlertRule(Base):
    __tablename__ = "monitor_alert_rules"

    rule_id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String(128), nullable=False)
    metric = Column(String(64), nullable=False)
    threshold_warning = Column(Float, default=0.0)
    threshold_alert = Column(Float, default=0.0)
    webhook_url = Column(String(512), default="")
    enabled = Column(Boolean, default=True)
    agent_id = Column(String, index=True, default="")
    created_at = Column(DateTime, default=now_utc)


class AnnotationQueue(Base):
    __tablename__ = "annotation_queues"

    queue_id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String(128), nullable=False)
    agent_id = Column(String, index=True, default="")
    description = Column(Text, default="")
    created_at = Column(DateTime, default=now_utc)


class AnnotationQueueItem(Base):
    __tablename__ = "annotation_queue_items"

    item_id = Column(String, primary_key=True, default=gen_uuid)
    queue_id = Column(String, ForeignKey("annotation_queues.queue_id"), nullable=False, index=True)
    run_id = Column(String, default="")
    case_id = Column(String, default="")
    status = Column(String(32), default="pending")
    expected_output = Column(Text, default="")
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=now_utc)


class MonitorSavedView(Base):
    __tablename__ = "monitor_saved_views"

    view_id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String(128), nullable=False)
    path = Column(String(64), default="runs")
    filters_json = Column(JSON, default=dict)
    user_id = Column(String, default="")
    created_at = Column(DateTime, default=now_utc)