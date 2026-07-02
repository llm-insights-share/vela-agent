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
    created_at = Column(DateTime, default=now_utc)