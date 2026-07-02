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
    tags: List[str] = Field(default_factory=list)


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
    tags: Optional[List[str]] = None
    change_summary: str = Field(default="")


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