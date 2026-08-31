from pydantic import BaseModel, Field, model_validator, field_validator, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime


class ModelProviderCreate(BaseModel):
    provider_code: str = Field(..., min_length=1, max_length=32)
    display_name: str = Field(..., min_length=1, max_length=128)
    base_url: str = Field(..., min_length=1, max_length=512)
    api_key: str = Field(default="", max_length=512)
    extra_headers: Dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=120, ge=1)
    max_retries: int = Field(default=3, ge=0)


class ModelProviderUpdate(BaseModel):
    display_name: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    extra_headers: Optional[Dict[str, str]] = None
    timeout_seconds: Optional[int] = None
    max_retries: Optional[int] = None
    status: Optional[str] = None


class ModelProviderResponse(BaseModel):
    provider_id: str
    provider_code: str
    display_name: str
    base_url: str
    api_key: str = ""
    extra_headers: Dict[str, Any] = {}
    timeout_seconds: int = 120
    max_retries: int = 3
    status: str = "ACTIVE"
    health_check_interval: int = 300
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ModelServiceCreate(BaseModel):
    provider_id: str
    model_name: str = Field(..., min_length=1, max_length=256)
    display_name: str = Field(..., min_length=1, max_length=256)
    max_tokens: int = Field(default=4096, ge=1)
    capabilities: List[str] = Field(default_factory=list)


class ModelServiceUpdate(BaseModel):
    display_name: Optional[str] = None
    max_tokens: Optional[int] = None
    capabilities: Optional[List[str]] = None
    status: Optional[str] = None


class ModelServiceResponse(BaseModel):
    model_service_id: str
    provider_id: str
    provider_code: Optional[str] = None
    model_name: str
    display_name: str
    max_tokens: int = 4096
    capabilities: List[str] = []
    status: str = "ACTIVE"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class AgentCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=128)
    description: str = Field(default="", max_length=2048)
    model_service_id: str = Field(...)
    system_prompt: str = Field(default="", max_length=32000)
    dept_id: str = Field(default="")
    autonomy_level: str = Field(default="L2", pattern="^(L1|L2|L3)$")
    max_concurrent_sessions: int = Field(default=5, ge=1)
    token_budget: int = Field(default=100000, ge=1000)
    tool_permissions: Dict[str, str] = Field(default_factory=dict)
    skill_pack_ids: List[str] = Field(default_factory=list)
    knowledge_base_ids: List[str] = Field(default_factory=list)
    tool_ids: List[str] = Field(default_factory=list)
    # SGL-CFG-06: 支持按工具勾选 HITL 审批；与 tool_ids 二选一，优先 tool_bindings
    tool_bindings: Optional[List["ToolBindingItem"]] = None
    tags: List[str] = Field(default_factory=list)
    # SGL-CFG-02~07: ReAct 循环参数
    max_iterations: int = Field(default=10, ge=1, le=50)
    step_timeout_seconds: int = Field(default=60, ge=5, le=600)
    timeout_seconds: int = Field(default=180, ge=10, le=600)
    tool_retry_count: int = Field(default=2, ge=0, le=10)
    tool_retry_backoff: str = Field(default="fixed", pattern="^(fixed|exponential)$")
    allow_repeat_tool_calls: bool = Field(default=True)
    max_repeat_threshold: int = Field(default=3, ge=2, le=10)
    single_call_token_limit: int = Field(default=8192, ge=1024)
    agent_type: str = Field(default="SINGLE", pattern="^(SINGLE|COMPOSITE|WORKFLOW)$")
    composition_config: Dict[str, Any] = Field(default_factory=dict)
    workflow_definition: Dict[str, Any] = Field(default_factory=dict)


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    model_service_id: Optional[str] = None
    system_prompt: Optional[str] = None
    dept_id: Optional[str] = None
    autonomy_level: Optional[str] = None
    max_concurrent_sessions: Optional[int] = None
    token_budget: Optional[int] = None
    tool_permissions: Optional[Dict[str, str]] = None
    skill_pack_ids: Optional[List[str]] = None
    knowledge_base_ids: Optional[List[str]] = None
    tool_ids: Optional[List[str]] = None
    # SGL-CFG-06: 支持按工具勾选 HITL 审批
    tool_bindings: Optional[List["ToolBindingItem"]] = None
    tags: Optional[List[str]] = None
    change_summary: str = Field(default="")
    max_iterations: Optional[int] = None
    step_timeout_seconds: Optional[int] = None
    timeout_seconds: Optional[int] = None
    tool_retry_count: Optional[int] = None
    tool_retry_backoff: Optional[str] = None
    allow_repeat_tool_calls: Optional[bool] = None
    max_repeat_threshold: Optional[int] = None
    single_call_token_limit: Optional[int] = None
    agent_type: Optional[str] = None
    composition_config: Optional[Dict[str, Any]] = None
    workflow_definition: Optional[Dict[str, Any]] = None


# WF: 工作流型相关 Schema
class WorkflowDefinitionUpdate(BaseModel):
    version: int = Field(default=1, ge=1)
    nodes: List[Dict[str, Any]] = Field(default_factory=list)
    edges: List[Dict[str, Any]] = Field(default_factory=list)


class WorkflowResponse(BaseModel):
    parent_agent_id: str
    workflow_definition: Dict[str, Any] = {}


class WorkflowValidationResult(BaseModel):
    errors: List[Dict[str, str]] = []
    warnings: List[Dict[str, str]] = []
    passed: bool = True


# MA: 多 Agent 编排相关 Schema
class SubAgentAdd(BaseModel):
    child_agent_id: str
    role_name: str = Field(..., min_length=1, max_length=128)
    role_description: str = Field(default="", max_length=2048)
    task_keywords: List[str] = Field(default_factory=list)


class SubAgentRemove(BaseModel):
    child_agent_id: str


class CoordinatorConfigUpdate(BaseModel):
    dispatch_strategy: str = Field(default="llm", pattern="^(llm|rule)$")
    max_dispatch_rounds: int = Field(default=5, ge=1, le=20)
    result_integration: str = Field(default="coordinator", pattern="^(coordinator|concat)$")
    coordinator_model_service_id: Optional[str] = None
    a2a_direct_whitelist: List[List[str]] = Field(default_factory=list)
    hitl_before_delivery: bool = Field(default=True)
    total_token_budget: int = Field(default=500000, ge=10000)
    max_a2a_calls: int = Field(default=20, ge=1, le=100)


class CompositionResponse(BaseModel):
    parent_agent_id: str
    sub_agents: List[Dict[str, Any]] = []
    coordinator_config: Dict[str, Any] = {}


# HITL 审批 Schema
class HITLApprovalResponse(BaseModel):
    approval_id: str
    session_id: str
    agent_id: str
    tool_name: str
    tool_args: Dict[str, Any] = {}
    status: str
    created_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class HITLReview(BaseModel):
    approved: bool
    reviewer: str = Field(default="", max_length=128)
    comment: str = Field(default="", max_length=2048)
    otp_code: Optional[str] = Field(default=None, max_length=32)
    param_values: Optional[Dict[str, Any]] = None


class ToolBindingItem(BaseModel):
    """SGL-CFG-06: 工具绑定项，支持按工具勾选 HITL"""
    tool_id: str
    require_approval: bool = False


# SGL-CFG-06: 解析 AgentCreate/AgentUpdate 中对 ToolBindingItem 的前向引用
AgentCreate.model_rebuild()
AgentUpdate.model_rebuild()


class AgentResponse(BaseModel):
    agent_id: str
    name: str
    description: str = ""
    model_service_id: str = ""
    model_name: Optional[str] = None
    provider_id: str = ""
    provider_name: str = ""
    provider_code: str = ""
    system_prompt: str = ""
    dept_id: str = ""
    autonomy_level: str = "L2"
    max_concurrent_sessions: int = 5
    token_budget: int = 100000
    tool_permissions: Dict[str, Any] = {}
    tags: List[str] = []
    status: str = "DRAFT"
    current_version_id: Optional[str] = None
    current_version: Optional[str] = None
    skill_pack_ids: List[str] = []
    skill_pack_names: List[str] = []
    knowledge_base_ids: List[str] = []
    knowledge_base_names: List[str] = []
    tool_ids: List[str] = []
    tool_names: List[str] = []
    max_iterations: int = 10
    step_timeout_seconds: int = 60
    timeout_seconds: int = 180
    tool_retry_count: int = 2
    tool_retry_backoff: str = "fixed"
    allow_repeat_tool_calls: bool = True
    max_repeat_threshold: int = 3
    single_call_token_limit: int = 8192
    agent_type: str = "SINGLE"
    composition_config: Dict[str, Any] = {}
    workflow_definition: Dict[str, Any] = {}
    memory_enabled: bool = False
    query_rewrite_enabled: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class AgentVersionResponse(BaseModel):
    version_id: str
    agent_id: str
    version: str
    version_seq: int = 1
    change_type: str = "PATCH"
    change_summary: str = ""
    snapshot: Dict[str, Any] = {}
    status: str = "DRAFT"
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class AgentPublishRequest(BaseModel):
    version_id: Optional[str] = None
    publish_strategy: str = Field(default="blue-green", pattern="^(blue-green|canary|hot-update)$")
    canary_percent: int = Field(default=10, ge=1, le=100)


class SkillPackCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    version: str = Field(default="1.0.0")
    scope: str = Field(default="platform")
    tools: List[Dict[str, Any]] = Field(default_factory=list)
    description: str = Field(default="")


class SkillToolBudgetSchema(BaseModel):
    max_web_search: int = Field(default=5, ge=1, le=50)
    max_tavily_per_iter: int = Field(default=2, ge=1, le=10)
    max_tool_rounds: int = Field(default=3, ge=1, le=20)
    min_timeout_seconds: int = Field(default=180, ge=10, le=600)


class SkillManifestSchema(BaseModel):
    trigger_keywords: List[str] = Field(default_factory=list)
    tool_budget: SkillToolBudgetSchema = Field(default_factory=SkillToolBudgetSchema)
    execution_hints: str = Field(default="")

    model_config = ConfigDict(extra="allow")


class SkillPackUpdate(BaseModel):
    name: Optional[str] = None
    version: Optional[str] = None
    scope: Optional[str] = None
    tools: Optional[List[Dict[str, Any]]] = None
    description: Optional[str] = None
    status: Optional[str] = None
    manifest: Optional[Dict[str, Any]] = None


class SkillPackResponse(BaseModel):
    skill_pack_id: str
    name: str
    version: str = "1.0.0"
    scope: str = "platform"
    tools: List[Dict[str, Any]] = []
    description: str = ""
    manifest: Optional[Dict[str, Any]] = None
    skill_content: str = ""
    package_files: Optional[Dict[str, Any]] = None
    status: str = "ACTIVE"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class KnowledgeTagDef(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    type: str = Field(default="text", pattern="^(text|date)$")
    hint: str = Field(default="")


class KnowledgeTagFilter(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    op: str = Field(default="eq", pattern="^(eq|contains|gte|lte|lt|gt)$")
    value: str = Field(default="")


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(default="")
    kb_type: str = Field(default="document")
    scope: str = Field(default="platform")
    contextual_retrieval_enabled: Optional[bool] = Field(
        default=None,
        description="null=跟随全局，true/false=覆盖全局开关",
    )
    tag_defs: List[KnowledgeTagDef] = Field(default_factory=list)


class KnowledgeBaseUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    kb_type: Optional[str] = None
    scope: Optional[str] = None
    status: Optional[str] = None
    contextual_retrieval_enabled: Optional[bool] = None
    tag_defs: Optional[List[KnowledgeTagDef]] = None


class KnowledgeBaseResponse(BaseModel):
    kb_id: str
    name: str
    description: str = ""
    kb_type: str = "document"
    scope: str = "platform"
    version: str = "1.0.0"
    doc_count: int = 0
    status: str = "ACTIVE"
    contextual_retrieval_enabled: Optional[bool] = None
    tag_defs: List[KnowledgeTagDef] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

    @field_validator("tag_defs", mode="before")
    @classmethod
    def _coerce_tag_defs(cls, value):
        return value or []


class DocumentAddRequest(BaseModel):
    content: str = Field(..., min_length=1)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class KnowledgeFileStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(ACTIVE|INACTIVE)$")


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=50)
    mode: str = Field(default="hybrid", description="hybrid | vector | bm25")
    rerank: bool = Field(default=False, description="已忽略，保留兼容")
    tag_filters: List[KnowledgeTagFilter] = Field(default_factory=list)


class KnowledgeSearchResult(BaseModel):
    chunk_id: str
    content: str
    score: float
    metadata: Dict[str, Any] = {}
    sources: List[str] = []
    tags: Dict[str, str] = {}


class KnowledgeSearchResponse(BaseModel):
    results: List[KnowledgeSearchResult] = []
    query_time_ms: float = 0
    applied_filters: List[KnowledgeTagFilter] = Field(default_factory=list)


class KnowledgeSearchSuggestRequest(BaseModel):
    query: str = Field(..., min_length=1)


class KnowledgeImportConfirmRequest(BaseModel):
    preview_id: str = Field(..., min_length=1)
    tags: Dict[str, str] = Field(default_factory=dict)


class KnowledgeDocumentTagsUpdate(BaseModel):
    tags: Dict[str, str] = Field(default_factory=dict)


class KnowledgeChunkItem(BaseModel):
    chunk_id: str
    index: int
    content: str
    char_count: int
    contextual_prefix: Optional[str] = None
    contextualized: bool = False
    has_index_text: bool = False
    status: str = "ACTIVE"


class KnowledgeChunkListResponse(BaseModel):
    doc_id: str
    filename: str
    total: int
    chunks: List[KnowledgeChunkItem] = []


class SessionCreate(BaseModel):
    agent_id: str
    version_id: Optional[str] = None
    caller_type: str = Field(default="USER")
    caller_id: str = Field(default="")
    token_budget: int = Field(default=100000, ge=1)
    ttl_seconds: int = Field(default=1800, ge=60)


class SessionMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant|system|tool)$")
    content: str = Field(..., min_length=1)


class SessionChatRequest(BaseModel):
    message: str = Field(default="", max_length=32000)
    attachment_ids: List[str] = Field(default_factory=list)
    skill_pack_id: Optional[str] = None
    timeout_seconds: Optional[int] = None
    execution_mode: Optional[str] = Field(default="auto", pattern="^(auto|react|plan_and_execute|direct)$")
    skip_history: bool = False

    @model_validator(mode="after")
    def message_or_attachments(self):
        if not self.message.strip() and not self.attachment_ids:
            raise ValueError("消息和附件不能同时为空")
        return self


class SessionAttachmentResponse(BaseModel):
    attachment_id: str
    filename: str
    mime_type: str
    size_bytes: int
    text_length: int = 0
    is_image: bool = False
    uploaded_at: Optional[str] = None


class SessionAttachmentListResponse(BaseModel):
    attachments: List[SessionAttachmentResponse] = Field(default_factory=list)
    total: int = 0


class SessionChatAsyncResponse(BaseModel):
    accepted: bool = True
    session_id: str
    status: str = "RUNNING"


class SessionAbortResponse(BaseModel):
    accepted: bool = True
    session_id: str
    status: str
    message: str = ""


class SessionResponse(BaseModel):
    session_id: str
    agent_id: str
    version_id: Optional[str] = None
    caller_type: str = "USER"
    caller_id: str = ""
    status: str = "ACTIVE"
    token_used: int = 0
    token_budget: int = 100000
    ttl_seconds: int = 1800
    title: str = ""
    messages: List[Dict[str, Any]] = []
    llm_calls: List[Dict[str, Any]] = []
    pending_context: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    last_active_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ScheduleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(default="", max_length=2048)
    agent_id: str
    enabled: bool = True
    cron_expression: str = Field(..., min_length=5, max_length=64)
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=64)
    prompt_template: str = Field(default="", max_length=32000)
    skip_if_running: bool = True
    timeout_seconds: Optional[int] = Field(default=None, ge=5, le=3600)


class ScheduleUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    description: Optional[str] = Field(default=None, max_length=2048)
    agent_id: Optional[str] = None
    enabled: Optional[bool] = None
    cron_expression: Optional[str] = Field(default=None, min_length=5, max_length=64)
    timezone: Optional[str] = Field(default=None, min_length=1, max_length=64)
    prompt_template: Optional[str] = Field(default=None, max_length=32000)
    skip_if_running: Optional[bool] = None
    timeout_seconds: Optional[int] = Field(default=None, ge=5, le=3600)


class ScheduleResponse(BaseModel):
    schedule_id: str
    name: str
    description: str = ""
    agent_id: str
    agent_name: str = ""
    enabled: bool = True
    cron_expression: str
    timezone: str = "Asia/Shanghai"
    prompt_template: str = ""
    skip_if_running: bool = True
    timeout_seconds: Optional[int] = None
    created_by: str = ""
    last_fired_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    last_status: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

    @field_validator("last_status", "created_by", "description", "prompt_template", mode="before")
    @classmethod
    def _none_to_empty_str(cls, v):
        return "" if v is None else v


class ScheduleRunResponse(BaseModel):
    run_id: str
    schedule_id: str
    session_id: Optional[str] = None
    trigger_type: str
    status: str
    scheduled_for: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    prompt_rendered: str = ""
    error_message: str = ""
    token_used: int = 0
    summary: str = ""
    created_at: Optional[datetime] = None
    agent_id: str = ""
    agent_name: str = ""

    model_config = {"from_attributes": True}


class InboxMessageResponse(BaseModel):
    message_id: str
    user_id: str
    title: str
    body: str = ""
    level: str = "info"
    link_path: str = ""
    related_type: str = ""
    related_id: str = ""
    is_read: bool = False
    read_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class InboxUnreadCountResponse(BaseModel):
    unread_count: int = 0


class ScheduleCronPreviewRequest(BaseModel):
    cron_expression: str = Field(..., min_length=5, max_length=64)
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=64)
    count: int = Field(default=5, ge=1, le=20)


class ScheduleCronPreviewResponse(BaseModel):
    next_runs: List[str] = Field(default_factory=list)


class LlmCallLogItem(BaseModel):
    call_id: str
    seq: int
    created_at: Optional[str] = None
    source: str = ""
    model_name: str = ""
    duration_ms: int = 0
    input: Dict[str, Any] = {}
    output: Dict[str, Any] = {}


class LlmCallLogListResponse(BaseModel):
    items: List[LlmCallLogItem] = []


class DataQueryAgentCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=128)
    description: str = Field(default="", max_length=2048)
    model_service_id: str = Field(...)
    planner_model_service_id: Optional[str] = None
    sql_model_service_id: Optional[str] = None
    temperature: float = Field(default=0.1, ge=0, le=2)
    max_tokens: int = Field(default=2048, ge=256, le=32768)
    default_limit: int = Field(default=200, ge=1, le=5000)
    timeout_seconds: int = Field(default=30, ge=5, le=300)
    strict_mode: bool = True
    allow_cross_datasource: bool = False
    status: str = Field(default="ACTIVE", pattern="^(ACTIVE|INACTIVE|DEPRECATED)$")


class DataQueryAgentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    model_service_id: Optional[str] = None
    planner_model_service_id: Optional[str] = None
    sql_model_service_id: Optional[str] = None
    temperature: Optional[float] = Field(default=None, ge=0, le=2)
    max_tokens: Optional[int] = Field(default=None, ge=256, le=32768)
    default_limit: Optional[int] = Field(default=None, ge=1, le=5000)
    timeout_seconds: Optional[int] = Field(default=None, ge=5, le=300)
    strict_mode: Optional[bool] = None
    allow_cross_datasource: Optional[bool] = None
    status: Optional[str] = Field(default=None, pattern="^(ACTIVE|INACTIVE|DEPRECATED)$")


class DataQueryAgentResponse(BaseModel):
    dq_agent_id: str
    name: str
    description: str = ""
    model_service_id: str
    planner_model_service_id: Optional[str] = None
    sql_model_service_id: Optional[str] = None
    temperature: float = 0.1
    max_tokens: int = 2048
    default_limit: int = 200
    timeout_seconds: int = 30
    strict_mode: bool = True
    allow_cross_datasource: bool = False
    status: str = "ACTIVE"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class DataQueryDatasourceBindingItem(BaseModel):
    datasource_id: str
    datasource_name: str = ""
    db_type: str = Field(default="sqlite", pattern="^(sqlite|postgresql|mysql)$")
    db_url: str = Field(..., min_length=1, max_length=1024)
    schema_name: str = ""
    business_scope: str = Field(default="", max_length=200)
    table_whitelist: List[str] = Field(default_factory=list)
    sensitive_columns: List[str] = Field(default_factory=list)
    default_limit: int = Field(default=200, ge=1, le=5000)
    timeout_seconds: int = Field(default=30, ge=5, le=300)
    status: str = Field(default="ACTIVE", pattern="^(ACTIVE|INACTIVE|ERROR)$")


class DataQueryDatasourceBindingResponse(BaseModel):
    id: int
    dq_agent_id: str
    datasource_id: str
    datasource_name: str = ""
    db_type: str = "sqlite"
    db_url: str = ""
    schema_name: str = ""
    business_scope: str = ""
    table_whitelist: List[str] = []
    sensitive_columns: List[str] = []
    default_limit: int = 200
    timeout_seconds: int = 30
    status: str = "ACTIVE"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class DataQueryDatasourceUpdateRequest(BaseModel):
    bindings: List[DataQueryDatasourceBindingItem] = Field(default_factory=list)


class DataQueryTestQueryRequest(BaseModel):
    question: str = Field(..., min_length=1)
    datasource_id: Optional[str] = None
    top_k: int = Field(default=100, ge=1, le=5000)
    strict_mode: bool = True
    return_sql_only: bool = False
    session_id: Optional[str] = None


class DataTableDictionaryUpsert(BaseModel):
    datasource_id: str
    table_name: str
    business_name: str = ""
    description: str = ""
    synonyms: List[str] = Field(default_factory=list)


class DataTableDictionaryResponse(BaseModel):
    id: int
    dq_agent_id: str
    datasource_id: str
    table_name: str
    business_name: str = ""
    description: str = ""
    synonyms: List[str] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class DataSchemaTableItem(BaseModel):
    table_name: str
    db_comment: str = ""
    business_name: str = ""
    description: str = ""
    synonyms: List[str] = Field(default_factory=list)


class DataSchemaColumnItem(BaseModel):
    column_name: str
    db_type: str = ""
    db_comment: str = ""
    business_name: str = ""
    description: str = ""


class DataSchemaColumnBatchItem(BaseModel):
    column_name: str
    description: str = ""


class DataSchemaColumnBatchUpsert(BaseModel):
    datasource_id: str
    table_name: str
    columns: List[DataSchemaColumnBatchItem] = Field(default_factory=list)


class DataQueryDictionaryCreate(BaseModel):
    datasource_id: str
    table_name: str
    column_name: str
    business_name: str = ""
    description: str = ""
    value_type: str = "string"
    synonyms: List[str] = Field(default_factory=list)
    metric_formula: str = ""


class DataQueryDictionaryUpdate(BaseModel):
    business_name: Optional[str] = None
    description: Optional[str] = None
    value_type: Optional[str] = None
    synonyms: Optional[List[str]] = None
    metric_formula: Optional[str] = None


class DataQueryDictionaryResponse(BaseModel):
    id: int
    dq_agent_id: str
    datasource_id: str
    table_name: str
    column_name: str
    business_name: str = ""
    description: str = ""
    value_type: str = "string"
    synonyms: List[str] = []
    metric_formula: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class DataCodeMappingCreate(BaseModel):
    datasource_id: str
    table_name: str = ""
    column_name: str
    code_value: str
    display_name: str
    aliases: List[str] = Field(default_factory=list)


class DataCodeMappingUpdate(BaseModel):
    display_name: Optional[str] = None
    aliases: Optional[List[str]] = None


class DataCodeMappingResponse(BaseModel):
    id: int
    dq_agent_id: str
    datasource_id: str
    table_name: str = ""
    column_name: str
    code_value: str
    display_name: str
    aliases: List[str] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class DataQueryExampleCreate(BaseModel):
    datasource_id: str
    intent_tag: str = ""
    nl_question: str = Field(..., min_length=1)
    sql_template: str = Field(..., min_length=1)
    variables: Dict[str, Any] = Field(default_factory=dict)
    explanation: str = ""
    quality_score: float = 0.0
    enabled: bool = True


class DataQueryExampleUpdate(BaseModel):
    intent_tag: Optional[str] = None
    nl_question: Optional[str] = None
    sql_template: Optional[str] = None
    variables: Optional[Dict[str, Any]] = None
    explanation: Optional[str] = None
    quality_score: Optional[float] = None
    enabled: Optional[bool] = None


class DataQueryExampleResponse(BaseModel):
    example_id: str
    dq_agent_id: str
    datasource_id: str
    intent_tag: str = ""
    nl_question: str
    sql_template: str
    variables: Dict[str, Any] = {}
    explanation: str = ""
    quality_score: float = 0.0
    enabled: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class DataTermMappingCreate(BaseModel):
    source_term: str
    normalized_term: str
    mapping_type: str = "synonym"
    priority: int = Field(default=100, ge=1, le=1000)
    enabled: bool = True


class DataTermMappingUpdate(BaseModel):
    normalized_term: Optional[str] = None
    mapping_type: Optional[str] = None
    priority: Optional[int] = Field(default=None, ge=1, le=1000)
    enabled: Optional[bool] = None


class DataTermMappingResponse(BaseModel):
    id: int
    dq_agent_id: str
    source_term: str
    normalized_term: str
    mapping_type: str = "synonym"
    priority: int = 100
    enabled: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class DataQueryFeedbackCreate(BaseModel):
    log_id: str
    rating: int = Field(..., ge=1, le=5)
    comment: str = ""


class DataQueryFeedbackResponse(BaseModel):
    feedback_id: str
    log_id: str
    dq_agent_id: str
    session_id: str = ""
    rating: int = 0
    comment: str = ""
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class DataQueryQualityStatsResponse(BaseModel):
    id: int
    dq_agent_id: str
    stat_date: str
    total_queries: int = 0
    success_queries: int = 0
    failed_queries: int = 0
    avg_duration_ms: float = 0.0
    avg_feedback_score: float = 0.0
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ValidationResult(BaseModel):
    errors: List[Dict[str, str]] = []
    warnings: List[Dict[str, str]] = []
    passed: bool = True


class SyncModelsRequest(BaseModel):
    provider_id: str = Field(...)


class ToolCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    display_name: str = Field(default="", max_length=256)
    description: str = Field(default="")
    tool_type: str = Field(..., pattern="^(mcp|restful|local_python)$")
    config: Dict[str, Any] = Field(default_factory=dict)
    parameters_schema: Dict[str, Any] = Field(default_factory=dict)
    mcp_server_id: Optional[str] = None


class ToolUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    display_name: Optional[str] = None
    description: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    parameters_schema: Optional[Dict[str, Any]] = None
    status: Optional[str] = None
    mcp_server_id: Optional[str] = None


class ToolResponse(BaseModel):
    tool_id: str
    name: str
    display_name: str = ""
    description: str = ""
    tool_type: str
    config: Dict[str, Any] = {}
    parameters_schema: Dict[str, Any] = {}
    status: str = "ACTIVE"
    mcp_server_id: Optional[str] = None
    mcp_server_name: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ToolTestRequest(BaseModel):
    parameters: Dict[str, Any] = Field(default_factory=dict)


class McpDiscoverRequest(BaseModel):
    transport: str = Field(default="stdio")
    command: str = Field(default="")
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    url: str = Field(default="")
    headers: Dict[str, str] = Field(default_factory=dict)
    auth_type: str = Field(default="none")
    auth_token: str = Field(default="")
    mcp_server_id: str = Field(default="")
    timeout_seconds: int = Field(default=30, ge=1, le=300)


class McpServerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    display_name: str = Field(default="", max_length=256)
    description: str = Field(default="")
    transport: str = Field(default="stdio")
    command: str = Field(default="")
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    url: str = Field(default="")
    headers: Dict[str, str] = Field(default_factory=dict)
    auth_type: str = Field(default="none")


class McpServerUpdate(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    transport: Optional[str] = None
    command: Optional[str] = None
    args: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None
    url: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    auth_type: Optional[str] = None
    status: Optional[str] = None


class McpServerResponse(BaseModel):
    server_id: str
    name: str
    display_name: str = ""
    description: str = ""
    transport: str
    command: str = ""
    args: List[Any] = []
    env: Dict[str, Any] = {}
    url: str = ""
    headers: Dict[str, Any] = {}
    auth_type: str = "none"
    status: str = "ACTIVE"
    last_synced_at: Optional[datetime] = None
    last_error: str = ""
    oauth_status: str = "not_required"
    source: str = ""
    tool_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class McpOAuthStartRequest(BaseModel):
    frontend_redirect: str = Field(default="")
    client_id: str = Field(default="")
    scope: str = Field(default="")


class PaginatedResponse(BaseModel):
    total: int = 0
    page: int = 1
    page_size: int = 20
    items: List[Any] = []


# ─── Memory ──────────────────────────────────────────────────────────────────

class MemoryRecordResponse(BaseModel):
    record_id: str
    agent_id: str
    user_id: str = ""
    memory_type: str
    content: str
    metadata: Dict[str, Any] = {}
    source_episode_ids: List[str] = []
    status: str = "active"
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    created_by: str = "system"

    model_config = {"from_attributes": True}


class MemoryRecordUpdate(BaseModel):
    content: str = Field(..., min_length=1)
    metadata: Optional[Dict[str, Any]] = None


class MemoryEpisodeResponse(BaseModel):
    episode_id: str
    agent_id: str
    session_id: str = ""
    user_id: str = ""
    event_type: str
    payload: Dict[str, Any] = {}
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class MemoryAgentMountItem(BaseModel):
    agent_id: str
    memory_enabled: bool


class MemoryAgentMountUpdate(BaseModel):
    items: List[MemoryAgentMountItem]


class MemoryAgentMountResponse(BaseModel):
    agent_id: str
    name: str
    status: str = "DRAFT"
    memory_enabled: bool = False


class MemoryBlockResponse(BaseModel):
    label: str
    value: str = ""
    limit: int = 2000
    description: str = ""
    read_only: bool = False
    id: Optional[str] = None


class MemoryBlockUpdate(BaseModel):
    agent_id: str
    user_id: str = ""
    value: str = ""


class MemoryPassageResponse(BaseModel):
    id: str
    content: str = ""
    tags: List[str] = []
    created_at: Optional[Any] = None
    metadata: Dict[str, Any] = {}
    rank: Optional[int] = None


class MemoryPassageCreate(BaseModel):
    agent_id: str
    user_id: str = ""
    text: str = Field(..., min_length=1)
    tags: List[str] = []


class MemoryScopeResponse(BaseModel):
    mapping_id: str
    agent_id: str
    user_id: str = ""
    username: str = ""
    letta_agent_id: str
    created_at: Optional[datetime] = None


class LettaStatusResponse(BaseModel):
    enabled: bool = True
    healthy: bool = False
    base_url: str = ""
    embedding_model: str = "vela-embedding"
    embedding_dim: int = 1024
    error: Optional[str] = None
    version: Optional[str] = None
    mapping_count: int = 0


class LettaConfigResponse(BaseModel):
    enabled: bool = True
    base_url: str = "http://127.0.0.1:8283"
    password: str = ""
    gateway_base: str = "http://127.0.0.1:8000"
    gateway_token: str = ""
    distill_model_service_id: str = ""
    embedding_model: str = "vela-embedding"
    embedding_dim: int = 1024


class LettaConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    base_url: Optional[str] = None
    password: Optional[str] = None
    gateway_base: Optional[str] = None
    gateway_token: Optional[str] = None
    distill_model_service_id: Optional[str] = None


class ContextualRetrievalConfigResponse(BaseModel):
    enabled: bool = False
    model_service_id: str = ""
    max_concurrency: int = 12
    chunk_timeout_seconds: int = 30
    prefix_max_tokens: int = 128
    temperature: float = 0.0
    min_chunk_length: int = 50
    document_excerpt_max_chars: int = 2000


class ContextualRetrievalConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    model_service_id: Optional[str] = None
    max_concurrency: Optional[int] = None
    chunk_timeout_seconds: Optional[int] = None
    prefix_max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    min_chunk_length: Optional[int] = None
    document_excerpt_max_chars: Optional[int] = None


class QueryRewriteAgentMountItem(BaseModel):
    agent_id: str
    query_rewrite_enabled: bool


class QueryRewriteAgentMountUpdate(BaseModel):
    items: List[QueryRewriteAgentMountItem]


class QueryRewriteAgentMountResponse(BaseModel):
    agent_id: str
    name: str
    status: str = "DRAFT"
    query_rewrite_enabled: bool = False


class QueryRewritePreviewRequest(BaseModel):
    agent_id: str
    query: str
    history: Optional[List[Dict[str, Any]]] = None


class QueryRewritePreviewResponse(BaseModel):
    rewrite: Dict[str, Any]


# ── Auth / User ──────────────────────────────────────────────

class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    user_id: str
    username: str
    email: str
    display_name: str
    avatar_url: str = ""
    roles: str
    is_active: bool = True
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class RegisterIn(BaseModel):
    email: str
    username: str
    password: str = Field(..., min_length=6)
    display_name: str = ""


class AdminCreateUserIn(BaseModel):
    email: str
    username: str
    password: str = Field(..., min_length=6)
    display_name: str = ""
    roles: str = "member"


class ActiveIn(BaseModel):
    is_active: bool


class RolesIn(BaseModel):
    roles: str


class ProfileUpdateIn(BaseModel):
    display_name: str = ""
    email: str


class PasswordUpdateIn(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=6)


# ─── Code Execution ──────────────────────────────────────────────────────────

class CodeExecutionResponse(BaseModel):
    execution_id: str
    session_id: str
    agent_id: str = ""
    language: str = "python"
    code: str = ""
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    duration_ms: int = 0
    artifacts: List[Any] = []
    status: str = "SUCCESS"
    error_message: str = ""
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class CodeExecutionListResponse(BaseModel):
    items: List[CodeExecutionResponse] = []
    total: int = 0


class CodeExecutionRunRequest(BaseModel):
    code: str = Field(..., min_length=1)
    language: str = "python"
    timeout: Optional[int] = None
    reset_state: bool = False


class CodeExecConfigResponse(BaseModel):
    enabled: bool = True
    venv_path: str = ""
    wall_timeout: int = 60
    cpu_seconds: int = 30
    memory_mb: int = 2048
    max_output_bytes: int = 65536
    max_artifact_mb: int = 20
    allow_network: bool = False
    allow_install: bool = True
    package_allowlist: List[str] = []
    state_persist: bool = True


class CodeExecConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    venv_path: Optional[str] = None
    wall_timeout: Optional[int] = None
    cpu_seconds: Optional[int] = None
    memory_mb: Optional[int] = None
    max_output_bytes: Optional[int] = None
    max_artifact_mb: Optional[int] = None
    allow_network: Optional[bool] = None
    allow_install: Optional[bool] = None
    package_allowlist: Optional[List[str]] = None
    state_persist: Optional[bool] = None
