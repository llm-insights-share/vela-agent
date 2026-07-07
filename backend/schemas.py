from pydantic import BaseModel, Field
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
    tool_retry_count: int = 2
    tool_retry_backoff: str = "fixed"
    allow_repeat_tool_calls: bool = True
    max_repeat_threshold: int = 3
    single_call_token_limit: int = 8192
    agent_type: str = "SINGLE"
    composition_config: Dict[str, Any] = {}
    workflow_definition: Dict[str, Any] = {}
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


class SkillPackUpdate(BaseModel):
    name: Optional[str] = None
    version: Optional[str] = None
    scope: Optional[str] = None
    tools: Optional[List[Dict[str, Any]]] = None
    description: Optional[str] = None
    status: Optional[str] = None


class SkillPackResponse(BaseModel):
    skill_pack_id: str
    name: str
    version: str = "1.0.0"
    scope: str = "platform"
    tools: List[Dict[str, Any]] = []
    description: str = ""
    manifest: Optional[Dict[str, Any]] = None
    skill_content: str = ""
    status: str = "ACTIVE"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(default="")
    kb_type: str = Field(default="document")
    scope: str = Field(default="platform")


class KnowledgeBaseUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    kb_type: Optional[str] = None
    scope: Optional[str] = None
    status: Optional[str] = None


class KnowledgeBaseResponse(BaseModel):
    kb_id: str
    name: str
    description: str = ""
    kb_type: str = "document"
    scope: str = "platform"
    version: str = "1.0.0"
    doc_count: int = 0
    status: str = "ACTIVE"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class DocumentAddRequest(BaseModel):
    content: str = Field(..., min_length=1)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=50)
    rerank: bool = Field(default=False)


class KnowledgeSearchResult(BaseModel):
    chunk_id: str
    content: str
    score: float
    metadata: Dict[str, Any] = {}


class KnowledgeSearchResponse(BaseModel):
    results: List[KnowledgeSearchResult] = []
    query_time_ms: float = 0


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
    message: str = Field(..., min_length=1)
    skill_pack_id: Optional[str] = None
    timeout_seconds: Optional[int] = None
    execution_mode: Optional[str] = Field(default="auto", pattern="^(auto|react|plan_and_execute|direct)$")
    skip_history: bool = False


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
    messages: List[Dict[str, Any]] = []
    created_at: Optional[datetime] = None
    last_active_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


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


class ToolUpdate(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    parameters_schema: Optional[Dict[str, Any]] = None
    status: Optional[str] = None


class ToolResponse(BaseModel):
    tool_id: str
    name: str
    display_name: str = ""
    description: str = ""
    tool_type: str
    config: Dict[str, Any] = {}
    parameters_schema: Dict[str, Any] = {}
    status: str = "ACTIVE"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ToolTestRequest(BaseModel):
    parameters: Dict[str, Any] = Field(default_factory=dict)


class McpDiscoverRequest(BaseModel):
    command: str = Field(..., min_length=1)
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=30, ge=1, le=300)


class PaginatedResponse(BaseModel):
    total: int = 0
    page: int = 1
    page_size: int = 20
    items: List[Any] = []