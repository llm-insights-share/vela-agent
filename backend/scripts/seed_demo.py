"""Idempotent seed for demo agents.

Domains:
  - audit (COMPOSITE): economic-responsibility audit
  - hr (SINGLE): HR assistant
  - office (COMPOSITE): daily office / admin
  - pm (COMPOSITE): product manager workspace

Usage (from backend/):
  python -m scripts.seed_demo

Env:
  VELA_DEMO_MODEL_SERVICE_ID  optional; else first ModelService is used
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure backend root is on path when run as script
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

_REPO_ROOT = _BACKEND_ROOT.parent
_DEMOS = _REPO_ROOT / "demos"

from database import SessionLocal, init_db
from models import (
    Agent,
    AgentComposition,
    AgentKnowledgeBinding,
    AgentSkillBinding,
    AgentToolBinding,
    AgentType,
    AgentVersion,
    KnowledgeBase,
    KnowledgeBaseStatus,
    ModelService,
    SkillPack,
    SkillPackStatus,
    Tool,
    ToolStatus,
    ToolType,
    gen_uuid,
)
from routes.skills import _parse_skill_md
from schemas import AgentCreate, ToolBindingItem
from services.agent_service import AgentService
from services.knowledge_service import KnowledgeService


def _log(msg: str) -> None:
    print(f"[seed_demo] {msg}")


def _build_sqlite(domain: str) -> Path:
    """Build mock SQLite under demos/*/data and mirror to backend/data for DataQuery bindings."""
    data_dir = _DEMOS / domain / "data"
    db_path = data_dir / f"demo_{domain}.db"
    schema = (data_dir / "schema.sql").read_text(encoding="utf-8")
    seed = (data_dir / "seed.sql").read_text(encoding="utf-8")
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(schema)
        conn.executescript(seed)
        conn.commit()
    finally:
        conn.close()
    _log(f"built {db_path}")

    # Mirror into backend/data (common DataQuery URL target)
    mirror_dir = _BACKEND_ROOT / "data"
    mirror_dir.mkdir(parents=True, exist_ok=True)
    mirror_path = mirror_dir / f"demo_{domain}.db"
    if mirror_path.exists():
        mirror_path.unlink()
    import shutil

    shutil.copy2(db_path, mirror_path)
    _log(f"mirrored {mirror_path} ({mirror_path.stat().st_size} bytes)")
    return db_path


def _upsert_skill(db, md_path: Path) -> SkillPack:
    raw = md_path.read_text(encoding="utf-8")
    manifest, instructions = _parse_skill_md(raw)
    name = manifest.get("name") or md_path.stem
    version = str(manifest.get("version") or "1.0.0")
    description = str(manifest.get("description") or "")
    tools = manifest.get("tools") or []
    skill = db.query(SkillPack).filter(SkillPack.name == name).first()
    if skill:
        skill.version = version
        skill.description = description
        skill.tools = tools
        skill.manifest = manifest
        skill.skill_content = instructions
        skill.status = SkillPackStatus.ACTIVE
        _log(f"updated skill {name}")
    else:
        skill = SkillPack(
            skill_pack_id=gen_uuid(),
            name=name,
            version=version,
            scope="platform",
            tools=tools,
            description=description,
            manifest=manifest,
            skill_content=instructions,
            status=SkillPackStatus.ACTIVE,
        )
        db.add(skill)
        _log(f"created skill {name}")
    db.flush()
    return skill


def _upsert_kb(db, ks: KnowledgeService, name: str, description: str, doc_dir: Path) -> KnowledgeBase:
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.name == name).first()
    if not kb:
        kb = KnowledgeBase(
            kb_id=gen_uuid(),
            name=name,
            description=description,
            kb_type="document",
            scope="platform",
            status=KnowledgeBaseStatus.ACTIVE,
            doc_count=0,
        )
        db.add(kb)
        db.flush()
        _log(f"created kb {name}")
    else:
        kb.description = description
        kb.status = KnowledgeBaseStatus.ACTIVE
        _log(f"reuse kb {name}")

    # Idempotent docs: only ingest when empty
    if (kb.doc_count or 0) == 0:
        documents = []
        for path in sorted(doc_dir.glob("*.md")):
            documents.append(
                {
                    "content": path.read_text(encoding="utf-8"),
                    "metadata": {
                        "filename": path.name,
                        "file_type": "md",
                        "source": "demo_seed",
                    },
                }
            )
        if documents:
            added = ks.add_documents(kb.kb_id, documents)
            kb.doc_count = (kb.doc_count or 0) + max(added, len(documents))
            _log(f"indexed {len(documents)} docs into {name} (chunks≈{added})")
    db.flush()
    return kb


def _upsert_tool(
    db,
    *,
    name: str,
    display_name: str,
    description: str,
    function: str,
    parameters_schema: Dict[str, Any],
    module: str = "demo_tools",
) -> Tool:
    config = {
        "module": module,
        "function": function,
    }
    tool = db.query(Tool).filter(Tool.name == name).first()
    if tool:
        tool.display_name = display_name
        tool.description = description
        tool.tool_type = ToolType.LOCAL_PYTHON
        tool.config = config
        tool.parameters_schema = parameters_schema
        tool.status = ToolStatus.ACTIVE
        _log(f"updated tool {name}")
    else:
        tool = Tool(
            tool_id=gen_uuid(),
            name=name,
            display_name=display_name,
            description=description,
            tool_type=ToolType.LOCAL_PYTHON,
            config=config,
            parameters_schema=parameters_schema,
            status=ToolStatus.ACTIVE,
        )
        db.add(tool)
        _log(f"created tool {name}")
    db.flush()
    return tool


def _replace_agent_bindings(
    db,
    agent: Agent,
    *,
    skill_ids: List[str],
    kb_ids: List[str],
    tool_bindings: List[Tuple[str, bool]],
) -> None:
    db.query(AgentSkillBinding).filter(AgentSkillBinding.agent_id == agent.agent_id).delete()
    db.query(AgentKnowledgeBinding).filter(AgentKnowledgeBinding.agent_id == agent.agent_id).delete()
    db.query(AgentToolBinding).filter(AgentToolBinding.agent_id == agent.agent_id).delete()
    for sid in skill_ids:
        db.add(AgentSkillBinding(agent_id=agent.agent_id, skill_pack_id=sid, tool_permissions={}))
    for kid in kb_ids:
        db.add(AgentKnowledgeBinding(agent_id=agent.agent_id, kb_id=kid))
    for tid, require_approval in tool_bindings:
        db.add(
            AgentToolBinding(
                agent_id=agent.agent_id,
                tool_id=tid,
                permission="allowed",
                require_approval=require_approval,
            )
        )
    db.flush()


def _upsert_agent(
    db,
    *,
    name: str,
    description: str,
    model_service_id: str,
    system_prompt: str,
    agent_type: str,
    tags: List[str],
    skill_ids: List[str],
    kb_ids: List[str],
    tool_bindings: List[Tuple[str, bool]],
    composition_config: Optional[Dict[str, Any]] = None,
    max_iterations: int = 12,
) -> Agent:
    existing = db.query(Agent).filter(Agent.name == name).first()
    if existing:
        existing.description = description
        existing.model_service_id = model_service_id
        existing.system_prompt = system_prompt
        existing.agent_type = AgentType(agent_type)
        existing.tags = tags
        existing.composition_config = composition_config or {}
        existing.max_iterations = max_iterations
        _replace_agent_bindings(
            db,
            existing,
            skill_ids=skill_ids,
            kb_ids=kb_ids,
            tool_bindings=tool_bindings,
        )
        # refresh draft version snapshot lightly
        if existing.current_version_id:
            ver = db.query(AgentVersion).filter(
                AgentVersion.version_id == existing.current_version_id
            ).first()
            if ver and ver.snapshot is not None:
                snap = dict(ver.snapshot)
                snap.update(
                    {
                        "description": description,
                        "system_prompt": system_prompt,
                        "model_service_id": model_service_id,
                        "tags": tags,
                        "agent_type": agent_type,
                        "composition_config": composition_config or {},
                    }
                )
                ver.snapshot = snap
        db.flush()
        _log(f"updated agent {name}")
        return existing

    data = AgentCreate(
        name=name,
        description=description,
        model_service_id=model_service_id,
        system_prompt=system_prompt,
        tags=tags,
        agent_type=agent_type,
        skill_pack_ids=skill_ids,
        knowledge_base_ids=kb_ids,
        tool_bindings=[
            ToolBindingItem(tool_id=tid, require_approval=ra) for tid, ra in tool_bindings
        ],
        composition_config=composition_config or {},
        max_iterations=max_iterations,
    )
    agent = AgentService.create_agent(db, data)
    db.commit()
    db.refresh(agent)
    _log(f"created agent {name}")
    return agent


def _ensure_composition(
    db,
    parent: Agent,
    children: List[Dict[str, Any]],
) -> None:
    db.query(AgentComposition).filter(
        AgentComposition.parent_agent_id == parent.agent_id
    ).delete()
    for child in children:
        db.add(
            AgentComposition(
                parent_agent_id=parent.agent_id,
                child_agent_id=child["agent_id"],
                role_name=child["role_name"],
                role_description=child.get("role_description", ""),
                task_keywords=child.get("task_keywords") or [],
            )
        )
    db.flush()
    _log(f"composition set for {parent.name}: {[c['role_name'] for c in children]}")


def _publish(db, agent: Agent) -> Agent:
    published = AgentService.publish_agent(db, agent.agent_id)
    if not published:
        raise RuntimeError(f"publish failed for {agent.name}")
    _log(f"published {agent.name} ({agent.agent_id})")
    return published


def _resolve_model_service_id(db) -> str:
    env_id = os.environ.get("VELA_DEMO_MODEL_SERVICE_ID", "").strip()
    if env_id:
        ms = db.query(ModelService).filter(ModelService.model_service_id == env_id).first()
        if not ms:
            raise RuntimeError(f"VELA_DEMO_MODEL_SERVICE_ID not found: {env_id}")
        return env_id
    ms = db.query(ModelService).order_by(ModelService.created_at.asc()).first()
    if not ms:
        raise RuntimeError(
            "No ModelService found. Create a model service in UI or set VELA_DEMO_MODEL_SERVICE_ID."
        )
    return ms.model_service_id


# --- tool schemas ---

AUDIT_TOOLS_SPEC = [
    (
        "audit_lookup_employee",
        "审计·查被审计人",
        "按姓名或工号查询任职档案",
        "audit_lookup_employee",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "姓名，模糊匹配"},
                "emp_id": {"type": "string", "description": "员工编号"},
            },
        },
    ),
    (
        "audit_list_oa_docs",
        "审计·OA档案列表",
        "列出被审计人 OA 档案",
        "audit_list_oa_docs",
        {
            "type": "object",
            "properties": {
                "emp_id": {"type": "string"},
                "doc_type": {"type": "string", "description": "可选：任职文件/述职报告/会议纪要等"},
            },
            "required": ["emp_id"],
        },
    ),
    (
        "audit_query_gl",
        "审计·总账科目余额",
        "按组织与期间查询科目余额",
        "audit_query_gl",
        {
            "type": "object",
            "properties": {
                "org_id": {"type": "string"},
                "period_from": {"type": "string", "description": "YYYY-MM"},
                "period_to": {"type": "string", "description": "YYYY-MM"},
                "account_code": {"type": "string"},
            },
            "required": ["org_id", "period_from", "period_to"],
        },
    ),
    (
        "audit_query_related_party",
        "审计·关联往来",
        "查询往来款项，突出关联方与账龄异常",
        "audit_query_related_party",
        {
            "type": "object",
            "properties": {
                "org_id": {"type": "string"},
                "period": {"type": "string"},
            },
            "required": ["org_id"],
        },
    ),
    (
        "audit_list_contracts",
        "审计·重大合同",
        "列出重大合同并标记缺审批号",
        "audit_list_contracts",
        {
            "type": "object",
            "properties": {
                "org_id": {"type": "string"},
                "min_amount": {"type": "number"},
            },
            "required": ["org_id"],
        },
    ),
    (
        "audit_list_capex",
        "审计·投资项目",
        "列出 Capex 项目与超预算标志",
        "audit_list_capex",
        {
            "type": "object",
            "properties": {"org_id": {"type": "string"}},
            "required": ["org_id"],
        },
    ),
    (
        "audit_submit_engagement_draft",
        "审计·提交立项草案",
        "将经济责任审计立项说明书写入 outbox，等待人工审批",
        "audit_submit_engagement_draft",
        {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "markdown_body": {"type": "string"},
            },
            "required": ["title", "markdown_body"],
        },
    ),
]

HR_TOOLS_SPEC = [
    (
        "hr_search_employees",
        "人力·搜索员工",
        "按部门/职级/姓名搜索员工（默认脱敏薪资带宽）",
        "hr_search_employees",
        {
            "type": "object",
            "properties": {
                "department": {"type": "string"},
                "level": {"type": "string"},
                "name": {"type": "string"},
                "include_compensation": {"type": "boolean", "default": False},
            },
        },
    ),
    (
        "hr_get_leave_balance",
        "人力·年假余额TopN",
        "查询年假/调休余额 TopN，可按部门过滤",
        "hr_get_leave_balance",
        {
            "type": "object",
            "properties": {
                "department": {"type": "string"},
                "top_n": {"type": "integer", "default": 3},
                "leave_type": {"type": "string", "enum": ["annual", "compensatory"]},
            },
        },
    ),
    (
        "hr_list_open_requisitions",
        "人力·在招岗位",
        "列出 open 状态的招聘需求",
        "hr_list_open_requisitions",
        {
            "type": "object",
            "properties": {"department": {"type": "string"}},
        },
    ),
    (
        "hr_get_candidate",
        "人力·候选人详情",
        "查询候选人状态与面试轮次",
        "hr_get_candidate",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "candidate_id": {"type": "string"},
            },
        },
    ),
    (
        "hr_create_interview_note",
        "人力·写面试纪要",
        "将面试纪要写入 outbox（需审批）",
        "hr_create_interview_note",
        {
            "type": "object",
            "properties": {
                "candidate_name": {"type": "string"},
                "round_name": {"type": "string"},
                "note_markdown": {"type": "string"},
            },
            "required": ["candidate_name", "round_name", "note_markdown"],
        },
    ),
]

OFFICE_TOOLS_SPEC = [
    (
        "office_list_meetings",
        "办公·会议列表",
        "按状态/组织人/日期列出会议",
        "office_list_meetings",
        {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "organizer_name": {"type": "string"},
                "date_from": {"type": "string"},
            },
        },
    ),
    (
        "office_get_meeting",
        "办公·会议详情",
        "查询会议、纪要与督办待办",
        "office_get_meeting",
        {
            "type": "object",
            "properties": {
                "meeting_id": {"type": "string"},
                "title": {"type": "string"},
            },
        },
    ),
    (
        "office_list_action_items",
        "办公·督办待办",
        "列出督办事项，可筛逾期",
        "office_list_action_items",
        {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "owner_name": {"type": "string"},
                "overdue_only": {"type": "boolean", "default": False},
            },
        },
    ),
    (
        "office_list_travel",
        "办公·差旅申请",
        "查询差旅申请单",
        "office_list_travel",
        {
            "type": "object",
            "properties": {
                "emp_name": {"type": "string"},
                "status": {"type": "string"},
            },
        },
    ),
    (
        "office_get_expense_claim",
        "办公·报销单详情",
        "查询报销单明细与关联差旅",
        "office_get_expense_claim",
        {
            "type": "object",
            "properties": {
                "claim_id": {"type": "string"},
                "emp_name": {"type": "string"},
            },
        },
    ),
    (
        "office_list_rooms",
        "办公·会议室",
        "列出会议室及状态",
        "office_list_rooms",
        {
            "type": "object",
            "properties": {"status": {"type": "string"}},
        },
    ),
    (
        "office_list_seal_requests",
        "办公·用印申请",
        "查询印章使用申请",
        "office_list_seal_requests",
        {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "seal_type": {"type": "string"},
            },
        },
    ),
    (
        "office_list_supplies",
        "办公·物资库存",
        "查询办公用品库存与领用单",
        "office_list_supplies",
        {
            "type": "object",
            "properties": {"low_stock_only": {"type": "boolean", "default": False}},
        },
    ),
    (
        "office_submit_minutes_draft",
        "办公·提交纪要草案",
        "将会议纪要草案写入 outbox（需审批）",
        "office_submit_minutes_draft",
        {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "markdown_body": {"type": "string"},
            },
            "required": ["title", "markdown_body"],
        },
    ),
    (
        "office_submit_expense_review_note",
        "办公·提交报销预审意见",
        "将报销预审意见写入 outbox（需审批）",
        "office_submit_expense_review_note",
        {
            "type": "object",
            "properties": {
                "claim_id": {"type": "string"},
                "conclusion": {"type": "string"},
                "note_markdown": {"type": "string"},
            },
            "required": ["claim_id", "conclusion", "note_markdown"],
        },
    ),
]

PM_TOOLS_SPEC = [
    (
        "pm_list_products",
        "产品·产品列表",
        "列出产品线",
        "pm_list_products",
        {"type": "object", "properties": {}},
    ),
    (
        "pm_list_roadmap",
        "产品·Roadmap",
        "按产品/季度查询路线图",
        "pm_list_roadmap",
        {
            "type": "object",
            "properties": {
                "product_code": {"type": "string"},
                "quarter": {"type": "string"},
            },
        },
    ),
    (
        "pm_list_backlog",
        "产品·Backlog",
        "按优先级列出 backlog",
        "pm_list_backlog",
        {
            "type": "object",
            "properties": {
                "product_code": {"type": "string"},
                "status": {"type": "string"},
                "top_n": {"type": "integer", "default": 10},
            },
        },
    ),
    (
        "pm_list_competitors",
        "产品·竞品列表",
        "列出竞品档案",
        "pm_list_competitors",
        {
            "type": "object",
            "properties": {"category": {"type": "string"}},
        },
    ),
    (
        "pm_get_competitor_matrix",
        "产品·竞品功能矩阵",
        "查询竞品功能支持度矩阵",
        "pm_get_competitor_matrix",
        {
            "type": "object",
            "properties": {"competitor_name": {"type": "string"}},
        },
    ),
    (
        "pm_list_feedback",
        "产品·用户反馈",
        "查询工单/访谈/NPS 反馈",
        "pm_list_feedback",
        {
            "type": "object",
            "properties": {
                "product_code": {"type": "string"},
                "theme": {"type": "string"},
                "sentiment": {"type": "string"},
            },
        },
    ),
    (
        "pm_list_interviews",
        "产品·访谈记录",
        "列出用户访谈纪要摘要",
        "pm_list_interviews",
        {
            "type": "object",
            "properties": {"product_code": {"type": "string"}},
        },
    ),
    (
        "pm_query_metrics",
        "产品·日指标",
        "查询 DAU/激活/留存/NPS 等日序列",
        "pm_query_metrics",
        {
            "type": "object",
            "properties": {
                "product_code": {"type": "string", "default": "approval-hub"},
                "date_from": {"type": "string"},
                "date_to": {"type": "string"},
            },
        },
    ),
    (
        "pm_query_funnel",
        "产品·AARRR漏斗",
        "查询周度获客-激活-留存-推荐-收入漏斗",
        "pm_query_funnel",
        {
            "type": "object",
            "properties": {
                "product_code": {"type": "string", "default": "approval-hub"},
            },
        },
    ),
    (
        "pm_list_events",
        "产品·埋点事件表",
        "查询埋点事件定义",
        "pm_list_events",
        {
            "type": "object",
            "properties": {
                "product_code": {"type": "string"},
                "status": {"type": "string"},
            },
        },
    ),
    (
        "pm_list_experiments",
        "产品·A/B实验",
        "查询实验与结论",
        "pm_list_experiments",
        {
            "type": "object",
            "properties": {
                "product_code": {"type": "string"},
                "status": {"type": "string"},
            },
        },
    ),
    (
        "pm_list_prds",
        "产品·PRD索引",
        "列出 PRD 文档元数据",
        "pm_list_prds",
        {
            "type": "object",
            "properties": {"product_code": {"type": "string"}},
        },
    ),
    (
        "pm_submit_prd_draft",
        "产品·提交PRD草案",
        "将 PRD 草案写入 outbox（需审批）",
        "pm_submit_prd_draft",
        {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "markdown_body": {"type": "string"},
            },
            "required": ["title", "markdown_body"],
        },
    ),
]


# --- Platform ops assistant (vela CLI wrappers) ---
# Tuple: name, display, desc, function, schema, require_approval
OPS_TOOLS_SPEC = [
    (
        "vela_run",
        "Vela·通用CLI",
        "执行任意 vela CLI 子命令。subcommand 如 'agents list'；args_json 为额外参数 JSON 数组。",
        "vela_run",
        {
            "type": "object",
            "properties": {
                "subcommand": {"type": "string", "description": "如 agents list / tools get"},
                "args_json": {"type": "string", "description": 'JSON 数组，如 ["--page","1"] 或 ["agent_id"]'},
            },
            "required": ["subcommand"],
        },
        False,
    ),
    (
        "vela_agents_list",
        "Vela·列出智能体",
        "列出平台 Agent",
        "vela_agents_list",
        {
            "type": "object",
            "properties": {
                "page": {"type": "integer", "default": 1},
                "page_size": {"type": "integer", "default": 50},
                "keyword": {"type": "string"},
                "status": {"type": "string"},
            },
        },
        False,
    ),
    (
        "vela_agents_get",
        "Vela·获取智能体",
        "按 agent_id 获取详情",
        "vela_agents_get",
        {
            "type": "object",
            "properties": {"agent_id": {"type": "string"}},
            "required": ["agent_id"],
        },
        False,
    ),
    (
        "vela_agents_create",
        "Vela·创建智能体",
        "创建 Agent（草稿）。可传 json_body 覆盖字段，或用 name+model_service_id。",
        "vela_agents_create",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "model_service_id": {"type": "string"},
                "description": {"type": "string"},
                "system_prompt": {"type": "string"},
                "agent_type": {"type": "string", "default": "SINGLE"},
                "json_body": {"type": "string", "description": "完整 AgentCreate JSON 字符串"},
            },
        },
        True,
    ),
    (
        "vela_agents_update",
        "Vela·更新智能体",
        "更新 Agent，json_body 为 AgentUpdate JSON",
        "vela_agents_update",
        {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "json_body": {"type": "string"},
            },
            "required": ["agent_id", "json_body"],
        },
        True,
    ),
    (
        "vela_agents_delete",
        "Vela·删除智能体",
        "删除 Agent（禁止删除 vela-ops-assistant）",
        "vela_agents_delete",
        {
            "type": "object",
            "properties": {"agent_id": {"type": "string"}},
            "required": ["agent_id"],
        },
        True,
    ),
    (
        "vela_agents_publish",
        "Vela·发布智能体",
        "发布 Agent",
        "vela_agents_publish",
        {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "change_summary": {"type": "string"},
            },
            "required": ["agent_id"],
        },
        True,
    ),
    (
        "vela_agents_bind_tools",
        "Vela·绑定工具",
        "替换 Agent 工具绑定；json_body 为 tool_id 列表或绑定对象列表",
        "vela_agents_bind_tools",
        {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "json_body": {"type": "string"},
            },
            "required": ["agent_id", "json_body"],
        },
        True,
    ),
    (
        "vela_tools_list",
        "Vela·列出工具",
        "列出平台工具",
        "vela_tools_list",
        {
            "type": "object",
            "properties": {
                "page": {"type": "integer", "default": 1},
                "page_size": {"type": "integer", "default": 50},
                "keyword": {"type": "string"},
            },
        },
        False,
    ),
    (
        "vela_tools_get",
        "Vela·获取工具",
        "按 tool_id 获取工具",
        "vela_tools_get",
        {
            "type": "object",
            "properties": {"tool_id": {"type": "string"}},
            "required": ["tool_id"],
        },
        False,
    ),
    (
        "vela_tools_create",
        "Vela·创建工具",
        "创建工具；json_body 为 ToolCreate JSON",
        "vela_tools_create",
        {
            "type": "object",
            "properties": {"json_body": {"type": "string"}},
            "required": ["json_body"],
        },
        True,
    ),
    (
        "vela_tools_update",
        "Vela·更新工具",
        "更新工具",
        "vela_tools_update",
        {
            "type": "object",
            "properties": {
                "tool_id": {"type": "string"},
                "json_body": {"type": "string"},
            },
            "required": ["tool_id", "json_body"],
        },
        True,
    ),
    (
        "vela_tools_delete",
        "Vela·删除工具",
        "删除工具",
        "vela_tools_delete",
        {
            "type": "object",
            "properties": {"tool_id": {"type": "string"}},
            "required": ["tool_id"],
        },
        True,
    ),
    (
        "vela_skills_list",
        "Vela·列出Skill",
        "列出 Skill 包",
        "vela_skills_list",
        {
            "type": "object",
            "properties": {
                "page": {"type": "integer", "default": 1},
                "page_size": {"type": "integer", "default": 50},
                "keyword": {"type": "string"},
            },
        },
        False,
    ),
    (
        "vela_skills_get",
        "Vela·获取Skill",
        "获取 Skill 包详情",
        "vela_skills_get",
        {
            "type": "object",
            "properties": {"skill_pack_id": {"type": "string"}},
            "required": ["skill_pack_id"],
        },
        False,
    ),
    (
        "vela_kb_list",
        "Vela·列出知识库",
        "列出知识库",
        "vela_kb_list",
        {
            "type": "object",
            "properties": {
                "page": {"type": "integer", "default": 1},
                "page_size": {"type": "integer", "default": 50},
                "keyword": {"type": "string"},
            },
        },
        False,
    ),
    (
        "vela_kb_get",
        "Vela·获取知识库",
        "获取知识库详情",
        "vela_kb_get",
        {
            "type": "object",
            "properties": {"kb_id": {"type": "string"}},
            "required": ["kb_id"],
        },
        False,
    ),
    (
        "vela_approvals_list",
        "Vela·列出审批",
        "列出审批中心工单",
        "vela_approvals_list",
        {
            "type": "object",
            "properties": {
                "page": {"type": "integer", "default": 1},
                "page_size": {"type": "integer", "default": 50},
                "status": {"type": "string", "default": "PENDING"},
                "category": {"type": "string"},
            },
        },
        False,
    ),
    (
        "vela_approvals_get",
        "Vela·获取审批",
        "获取审批详情",
        "vela_approvals_get",
        {
            "type": "object",
            "properties": {"approval_id": {"type": "string"}},
            "required": ["approval_id"],
        },
        False,
    ),
    (
        "vela_approvals_approve",
        "Vela·批准审批",
        "批准 HITL 审批（需 session_id + approval_id）",
        "vela_approvals_approve",
        {
            "type": "object",
            "properties": {
                "approval_id": {"type": "string"},
                "session_id": {"type": "string"},
                "reviewer": {"type": "string"},
                "comment": {"type": "string"},
            },
            "required": ["approval_id", "session_id"],
        },
        True,
    ),
    (
        "vela_approvals_reject",
        "Vela·拒绝审批",
        "拒绝 HITL 审批",
        "vela_approvals_reject",
        {
            "type": "object",
            "properties": {
                "approval_id": {"type": "string"},
                "session_id": {"type": "string"},
                "reviewer": {"type": "string"},
                "comment": {"type": "string"},
            },
            "required": ["approval_id", "session_id"],
        },
        True,
    ),
    (
        "vela_sessions_list",
        "Vela·列出会话",
        "列出会话（只读）",
        "vela_sessions_list",
        {
            "type": "object",
            "properties": {
                "page": {"type": "integer", "default": 1},
                "page_size": {"type": "integer", "default": 20},
                "agent_id": {"type": "string"},
                "status": {"type": "string"},
            },
        },
        False,
    ),
    (
        "vela_models_list",
        "Vela·列出模型服务",
        "列出模型服务",
        "vela_models_list",
        {
            "type": "object",
            "properties": {
                "page": {"type": "integer", "default": 1},
                "page_size": {"type": "integer", "default": 50},
            },
        },
        False,
    ),
    (
        "vela_schedules_list",
        "Vela·列出定时任务",
        "列出定时任务",
        "vela_schedules_list",
        {
            "type": "object",
            "properties": {
                "page": {"type": "integer", "default": 1},
                "page_size": {"type": "integer", "default": 50},
            },
        },
        False,
    ),
    (
        "vela_connectors_list",
        "Vela·列出连接器",
        "列出连接器",
        "vela_connectors_list",
        {"type": "object", "properties": {}},
        False,
    ),
    (
        "vela_memory_scopes_list",
        "Vela·记忆作用域",
        "列出记忆管理中的 Agent/用户作用域（Letta scopes）。无入参时 arguments 请传 {}。",
        "vela_memory_scopes_list",
        {"type": "object", "properties": {"_unused": {"type": "string", "description": "忽略，保持为空"}}, "additionalProperties": False},
        False,
    ),
    (
        "vela_memory_passages_list",
        "Vela·列出归档记忆",
        "列出指定智能体作用下的归档记忆（记忆管理页面数据）",
        "vela_memory_passages_list",
        {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "user_id": {"type": "string"},
                "page": {"type": "integer", "default": 1},
                "page_size": {"type": "integer", "default": 50},
                "query": {"type": "string"},
            },
            "required": ["agent_id"],
        },
        False,
    ),
    (
        "vela_memory_passages_create",
        "Vela·新增归档记忆",
        "在记忆管理中为指定智能体新增一条归档记忆。必填 agent_id、text；缺参时不要猜测，应提示用户补全。",
        "vela_memory_passages_create",
        {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "目标智能体 ID"},
                "text": {"type": "string", "description": "记忆正文"},
                "user_id": {"type": "string", "description": "可选用户作用域"},
                "tags": {"type": "string", "description": "可选，逗号分隔标签"},
            },
            "required": ["agent_id", "text"],
        },
        False,
    ),
]

OPS_PROMPT = """你是 Vela 平台「应用操作助手」(vela-ops-assistant)。
你通过 vela_* 工具调用真实的 `vela` CLI（再调用 /api/v1），完成智能体、工具、Skill、知识库、审批、模型服务、定时任务、连接器、记忆管理等平台操作。

硬性规则：
1. 必须使用工具获取/变更数据，禁止编造 ID、列表或操作结果；禁止声称已成功但未调用对应工具。
2. 写操作（create/update/delete/publish/approve/reject/bind/记忆写入）若缺少必填参数，必须先向用户追问补全，禁止自行猜测后宣称成功。
3. 禁止删除、下线或重命名名为 vela-ops-assistant 的智能体。
4. 不要对本会话自己的 HITL 审批做无意义的递归批准；审批其他会话时需用户明确授权并提供 session_id。
5. 优先使用专用工具（vela_agents_list、vela_memory_passages_create 等）；未知命令可用 vela_run。
6. 「记忆管理」必须使用 vela_memory_* 工具写入平台归档记忆（Letta passages），禁止使用名为 memory 的本地文件工具。
7. 写入记忆前必须确认 agent_id（可先 vela_agents_list 或 vela_memory_scopes_list）；text 为记忆正文；user_id/tags 可选。
8. 缺 agent_id 时：只调用一次 vela_agents_list（不要同时 scopes_list + agents_list），列出后立即停止本轮，仅用一两句话请用户选择；禁止继续调用 passages_list / 不要罗列全部记忆内容。等用户回复确认后再执行写入。
9. 仅当用户明确要求「查看/列出记忆」时才调用 vela_memory_passages_list；写入流程不要先拉全量 passages。
10. 写入失败时如实说明错误，禁止声称成功；不要用 vela_run 重复同一写入。
11. 回复简洁，用中文；展示工具返回的关键非空字段即可，忽略空值字段。
"""


# Demo agents force eager tool loading so bound local_python tools are visible
# without tool_search (system default may be deferred).
_EAGER_TOOLS = {"tool_loading": {"enabled": True, "mode": "eager"}}

COLLECTOR_PROMPT = """你是经济责任审计「资料收集」专员（星河控股 Demo）。
职责：通过审计工具从 OA/财务 mock 系统取数，输出资料清单表（资料名|来源|关键字段/摘要|状态）。
规则：禁止编造金额；所有数字必须来自工具返回；先查员工档案再查财务。
可用工具：audit_lookup_employee、audit_list_oa_docs、audit_query_gl、audit_query_related_party、audit_list_contracts、audit_list_capex。
"""

RISK_PROMPT = """你是经济责任审计「风险识别」专员。
职责：基于已收集资料与 kb_search 法规知识库，输出风险点（标题/等级/法规依据/证据/建议程序）。
禁止在无证据时下追责结论，只能写风险关注与建议核实。
可用工具：audit_query_related_party、audit_list_contracts、audit_list_capex、kb_search。
"""

REPORTER_PROMPT = """你是经济责任审计「报告撰写」专员。
职责：按立项说明书模板起草草案；数字与风险必须来自上游结果；缺失标注【待补充】。
正式提交时调用 audit_submit_engagement_draft。
可用工具：kb_search、audit_submit_engagement_draft。
"""

COORD_PROMPT = """你是经济责任审计立项 Coordinator。
职责：根据子 Agent 职责对用户任务做拆解、规划与编排，并汇总结果。
典型审计链路：资料收集 → 风险识别 →（需要时）报告撰写。
闲聊或不需要子 Agent 时由你直接回答；汇总时保留证据引用；交付前系统可能触发 HITL 审批。
"""

HR_PROMPT = """你是星河控股 HR 智能助手（Demo）。
- 制度问答必须 kb_search，以知识库为准
- 人事数据必须直接调用已绑定的 hr_* 工具（勿用 tool_search），禁止臆造
- 可用工具：hr_search_employees、hr_get_leave_balance、hr_list_open_requisitions、hr_get_candidate、hr_create_interview_note
- 默认不展示薪资带宽（include_compensation=false）
- 简历筛选按技能输出匹配度、硬性对照、风险点、3道面试题
"""

OFFICE_MEETING_PROMPT = """你是星河控股行政「会议与督办」专员（Demo）。
职责：查询会议/纪要/督办，对照制度给出逾期升级建议；需要时可起草纪要并提交审批。
规则：禁止编造待办状态；数字与责任人必须来自 office_* 工具。
可用工具：office_list_meetings、office_get_meeting、office_list_action_items、office_submit_minutes_draft、kb_search。
"""

OFFICE_EXPENSE_PROMPT = """你是星河控股行政「差旅报销预审」专员（Demo）。
职责：核对差旅单与报销明细，对照《差旅与费用报销制度》给出合规结论。
规则：禁止编造金额；输出明细对照表；正式预审意见用 office_submit_expense_review_note。
可用工具：office_list_travel、office_get_expense_claim、office_submit_expense_review_note、kb_search。
"""

OFFICE_FACILITY_PROMPT = """你是星河控股行政「行政事务」专员（Demo）。
职责：会议室可用性、用印进度、办公用品库存与补货建议。
可用工具：office_list_rooms、office_list_seal_requests、office_list_supplies、kb_search。
"""

OFFICE_COORD_PROMPT = """你是星河控股日常办公 Coordinator。
职责：将用户行政诉求分派给会议督办 / 报销预审 / 行政事务子 Agent，并汇总可执行结果。
闲聊或纯制度问答可直接 kb 风格简答；涉及系统数据必须分派或说明需查数。
"""

PM_RESEARCH_PROMPT = """你是星河控股产品「调研与竞品」专员（Demo）。
职责：竞品矩阵、用户反馈、访谈证据 → 输出一页纸结论与 backlog 启示。
禁止编造客户原话；引用 feedback_id / interview_id。
可用工具：pm_list_competitors、pm_get_competitor_matrix、pm_list_feedback、pm_list_interviews、pm_list_backlog、kb_search。
"""

PM_ANALYTICS_PROMPT = """你是星河控股产品「数据分析」专员（Demo）。
职责：日指标、AARRR 漏斗、实验结论 → 洞察与建议动作。
禁止编造指标；对比须基于工具返回。
可用工具：pm_query_metrics、pm_query_funnel、pm_list_experiments、pm_list_events、pm_list_roadmap。
"""

PM_PRD_PROMPT = """你是星河控股产品「PRD 撰写」专员（Demo）。
职责：综合 backlog/反馈/访谈/埋点，按规范起草 PRD；提交草案需审批。
可用工具：pm_list_backlog、pm_list_feedback、pm_list_interviews、pm_list_events、pm_list_prds、pm_submit_prd_draft、kb_search。
"""

PM_COORD_PROMPT = """你是星河控股产品经理工作台 Coordinator。
典型链路：调研竞品/反馈 → 数据验证 →（需要时）PRD 起草。
汇总时保留证据 ID（FB/RI/BL/EV）；交付 PRD 前可能触发 HITL。
"""


def seed_all() -> Dict[str, Any]:
    init_db()
    _build_sqlite("audit")
    _build_sqlite("hr")
    _build_sqlite("office")
    _build_sqlite("pm")

    db = SessionLocal()
    summary: Dict[str, Any] = {"agents": {}, "skills": [], "kbs": [], "tools": []}
    try:
        model_service_id = _resolve_model_service_id(db)
        _log(f"model_service_id={model_service_id}")
        ks = KnowledgeService()

        # Skills
        skill_map: Dict[str, SkillPack] = {}
        for domain in ("audit", "hr", "office", "pm"):
            for path in sorted((_DEMOS / domain / "skills").glob("*.md")):
                skill_map[path.stem] = _upsert_skill(db, path)
        summary["skills"] = list(skill_map.keys())

        # KBs
        kb_reg = _upsert_kb(
            db,
            ks,
            "demo-audit-regulations",
            "经济责任审计法规与操作指引（Demo）",
            _DEMOS / "audit" / "kb" / "regulations",
        )
        kb_tpl = _upsert_kb(
            db,
            ks,
            "demo-audit-templates",
            "经济责任审计报告模板与历史案例（Demo）",
            _DEMOS / "audit" / "kb" / "templates",
        )
        kb_pol = _upsert_kb(
            db,
            ks,
            "demo-hr-policies",
            "人事制度：考勤休假/招聘/试用期（Demo）",
            _DEMOS / "hr" / "kb" / "policies",
        )
        kb_jd = _upsert_kb(
            db,
            ks,
            "demo-hr-jd-resume",
            "JD 与候选人简历（Demo）",
            _DEMOS / "hr" / "kb" / "jd-resume",
        )
        kb_office_pol = _upsert_kb(
            db,
            ks,
            "demo-office-policies",
            "行政制度：会议督办/差旅报销/用印/物资（Demo）",
            _DEMOS / "office" / "kb" / "policies",
        )
        kb_office_tpl = _upsert_kb(
            db,
            ks,
            "demo-office-templates",
            "行政模板：会议纪要等（Demo）",
            _DEMOS / "office" / "kb" / "templates",
        )
        kb_pm_play = _upsert_kb(
            db,
            ks,
            "demo-pm-playbooks",
            "产品方法论：PRD/竞品/埋点/访谈（Demo）",
            _DEMOS / "pm" / "kb" / "playbooks",
        )
        kb_pm_art = _upsert_kb(
            db,
            ks,
            "demo-pm-artifacts",
            "产品制品：竞品快报/PRD摘录/访谈纪要（Demo）",
            _DEMOS / "pm" / "kb" / "artifacts",
        )
        summary["kbs"] = [
            kb_reg.name,
            kb_tpl.name,
            kb_pol.name,
            kb_jd.name,
            kb_office_pol.name,
            kb_office_tpl.name,
            kb_pm_play.name,
            kb_pm_art.name,
        ]

        # Tools
        audit_tools: Dict[str, Tool] = {}
        for name, display, desc, fn, schema in AUDIT_TOOLS_SPEC:
            audit_tools[name] = _upsert_tool(
                db,
                name=name,
                display_name=display,
                description=desc,
                function=fn,
                parameters_schema=schema,
            )
        hr_tools: Dict[str, Tool] = {}
        for name, display, desc, fn, schema in HR_TOOLS_SPEC:
            hr_tools[name] = _upsert_tool(
                db,
                name=name,
                display_name=display,
                description=desc,
                function=fn,
                parameters_schema=schema,
            )
        office_tools: Dict[str, Tool] = {}
        for name, display, desc, fn, schema in OFFICE_TOOLS_SPEC:
            office_tools[name] = _upsert_tool(
                db,
                name=name,
                display_name=display,
                description=desc,
                function=fn,
                parameters_schema=schema,
            )
        pm_tools: Dict[str, Tool] = {}
        for name, display, desc, fn, schema in PM_TOOLS_SPEC:
            pm_tools[name] = _upsert_tool(
                db,
                name=name,
                display_name=display,
                description=desc,
                function=fn,
                parameters_schema=schema,
            )
        ops_tools: Dict[str, Tool] = {}
        ops_bindings: List[Tuple[str, bool]] = []
        for name, display, desc, fn, schema, require_approval in OPS_TOOLS_SPEC:
            t = _upsert_tool(
                db,
                name=name,
                display_name=display,
                description=desc,
                function=fn,
                parameters_schema=schema,
                module="services.ops_cli_tools",
            )
            ops_tools[name] = t
            ops_bindings.append((t.tool_id, bool(require_approval)))
        summary["tools"] = (
            list(audit_tools)
            + list(hr_tools)
            + list(office_tools)
            + list(pm_tools)
            + list(ops_tools)
        )
        db.commit()

        # --- Audit specialists ---
        collector_bindings = [
            (audit_tools["audit_lookup_employee"].tool_id, False),
            (audit_tools["audit_list_oa_docs"].tool_id, False),
            (audit_tools["audit_query_gl"].tool_id, False),
            (audit_tools["audit_query_related_party"].tool_id, False),
            (audit_tools["audit_list_contracts"].tool_id, False),
            (audit_tools["audit_list_capex"].tool_id, False),
        ]
        collector = _upsert_agent(
            db,
            name="demo-audit-collector",
            description="经济责任审计·资料收集 Specialist",
            model_service_id=model_service_id,
            system_prompt=COLLECTOR_PROMPT,
            agent_type="SINGLE",
            tags=["demo", "demo-audit", "specialist"],
            skill_ids=[skill_map["demo-audit-collect-checklist"].skill_pack_id],
            kb_ids=[],
            tool_bindings=collector_bindings,
            composition_config=dict(_EAGER_TOOLS),
        )
        _publish(db, collector)

        risk = _upsert_agent(
            db,
            name="demo-audit-risk",
            description="经济责任审计·风险识别 Specialist",
            model_service_id=model_service_id,
            system_prompt=RISK_PROMPT,
            agent_type="SINGLE",
            tags=["demo", "demo-audit", "specialist"],
            skill_ids=[skill_map["demo-audit-risk-identify"].skill_pack_id],
            kb_ids=[kb_reg.kb_id],
            tool_bindings=[
                (audit_tools["audit_query_related_party"].tool_id, False),
                (audit_tools["audit_list_contracts"].tool_id, False),
                (audit_tools["audit_list_capex"].tool_id, False),
            ],
            composition_config=dict(_EAGER_TOOLS),
        )
        _publish(db, risk)

        reporter = _upsert_agent(
            db,
            name="demo-audit-reporter",
            description="经济责任审计·报告撰写 Specialist",
            model_service_id=model_service_id,
            system_prompt=REPORTER_PROMPT,
            agent_type="SINGLE",
            tags=["demo", "demo-audit", "specialist"],
            skill_ids=[skill_map["demo-audit-report-draft"].skill_pack_id],
            kb_ids=[kb_tpl.kb_id],
            tool_bindings=[
                (audit_tools["audit_submit_engagement_draft"].tool_id, True),
            ],
            composition_config=dict(_EAGER_TOOLS),
        )
        _publish(db, reporter)

        coord_cfg = {
            "dispatch_strategy": "llm",
            "max_dispatch_rounds": 3,
            "result_integration": "coordinator",
            "hitl_before_delivery": True,
            "total_token_budget": 800000,
            "max_a2a_calls": 12,
            "max_calls_per_agent": 2,
            "child_max_iterations": 6,
            "min_tokens_for_dispatch": 40000,
            **_EAGER_TOOLS,
        }
        coordinator = _upsert_agent(
            db,
            name="demo-audit-coordinator",
            description="经济责任审计立项 Coordinator（COMPOSITE Demo）",
            model_service_id=model_service_id,
            system_prompt=COORD_PROMPT,
            agent_type="COMPOSITE",
            tags=["demo", "demo-audit", "coordinator"],
            skill_ids=[],
            kb_ids=[],
            tool_bindings=[],
            composition_config=coord_cfg,
            max_iterations=8,
        )
        _ensure_composition(
            db,
            coordinator,
            [
                {
                    "agent_id": collector.agent_id,
                    "role_name": "资料收集",
                    "role_description": "从 OA/财务取数并输出资料清单",
                    "task_keywords": [
                        "资料", "收集", "OA", "财务", "任职", "合同", "总账",
                        "取数", "重大事项", "决策", "会议", "纪要", "三重一大", "集体", "Q1",
                    ],
                },
                {
                    "agent_id": risk.agent_id,
                    "role_name": "风险识别",
                    "role_description": "对照法规识别风险点",
                    "task_keywords": [
                        "风险", "关联交易", "异常", "超预算", "法规",
                        "集体决策", "个人决定", "合规", "三重一大", "核查", "审计问题",
                    ],
                },
                {
                    "agent_id": reporter.agent_id,
                    "role_name": "报告撰写",
                    "role_description": "起草经济责任审计立项说明书",
                    "task_keywords": ["立项", "说明书", "报告", "草案", "撰写"],
                },
            ],
        )
        db.commit()
        _publish(db, coordinator)

        # --- HR ---
        hr = _upsert_agent(
            db,
            name="demo-hr-assistant",
            description="HR 智能助手（制度问答 + 简历筛选 + HRIS 查数）",
            model_service_id=model_service_id,
            system_prompt=HR_PROMPT,
            agent_type="SINGLE",
            tags=["demo", "demo-hr"],
            skill_ids=[
                skill_map["demo-hr-resume-screen"].skill_pack_id,
                skill_map["demo-hr-onboarding"].skill_pack_id,
            ],
            kb_ids=[kb_pol.kb_id, kb_jd.kb_id],
            tool_bindings=[
                (hr_tools["hr_search_employees"].tool_id, False),
                (hr_tools["hr_get_leave_balance"].tool_id, False),
                (hr_tools["hr_list_open_requisitions"].tool_id, False),
                (hr_tools["hr_get_candidate"].tool_id, False),
                (hr_tools["hr_create_interview_note"].tool_id, True),
            ],
            composition_config=dict(_EAGER_TOOLS),
            max_iterations=12,
        )
        _publish(db, hr)
        db.commit()

        # --- Office COMPOSITE ---
        office_meeting = _upsert_agent(
            db,
            name="demo-office-meeting",
            description="日常办公·会议督办 Specialist",
            model_service_id=model_service_id,
            system_prompt=OFFICE_MEETING_PROMPT,
            agent_type="SINGLE",
            tags=["demo", "demo-office", "specialist"],
            skill_ids=[skill_map["demo-office-meeting-followup"].skill_pack_id],
            kb_ids=[kb_office_pol.kb_id, kb_office_tpl.kb_id],
            tool_bindings=[
                (office_tools["office_list_meetings"].tool_id, False),
                (office_tools["office_get_meeting"].tool_id, False),
                (office_tools["office_list_action_items"].tool_id, False),
                (office_tools["office_submit_minutes_draft"].tool_id, True),
            ],
            composition_config=dict(_EAGER_TOOLS),
        )
        _publish(db, office_meeting)

        office_expense = _upsert_agent(
            db,
            name="demo-office-expense",
            description="日常办公·差旅报销预审 Specialist",
            model_service_id=model_service_id,
            system_prompt=OFFICE_EXPENSE_PROMPT,
            agent_type="SINGLE",
            tags=["demo", "demo-office", "specialist"],
            skill_ids=[skill_map["demo-office-expense-check"].skill_pack_id],
            kb_ids=[kb_office_pol.kb_id],
            tool_bindings=[
                (office_tools["office_list_travel"].tool_id, False),
                (office_tools["office_get_expense_claim"].tool_id, False),
                (office_tools["office_submit_expense_review_note"].tool_id, True),
            ],
            composition_config=dict(_EAGER_TOOLS),
        )
        _publish(db, office_expense)

        office_facility = _upsert_agent(
            db,
            name="demo-office-facility",
            description="日常办公·会议室/用印/物资 Specialist",
            model_service_id=model_service_id,
            system_prompt=OFFICE_FACILITY_PROMPT,
            agent_type="SINGLE",
            tags=["demo", "demo-office", "specialist"],
            skill_ids=[skill_map["demo-office-facility-ops"].skill_pack_id],
            kb_ids=[kb_office_pol.kb_id],
            tool_bindings=[
                (office_tools["office_list_rooms"].tool_id, False),
                (office_tools["office_list_seal_requests"].tool_id, False),
                (office_tools["office_list_supplies"].tool_id, False),
            ],
            composition_config=dict(_EAGER_TOOLS),
        )
        _publish(db, office_facility)

        office_coord_cfg = {
            "dispatch_strategy": "llm",
            "max_dispatch_rounds": 3,
            "result_integration": "coordinator",
            "hitl_before_delivery": True,
            "total_token_budget": 800000,
            "max_a2a_calls": 12,
            "max_calls_per_agent": 2,
            "child_max_iterations": 6,
            "min_tokens_for_dispatch": 40000,
            **_EAGER_TOOLS,
        }
        office_coord = _upsert_agent(
            db,
            name="demo-office-coordinator",
            description="日常办公 Coordinator（会议/报销/行政 COMPOSITE Demo）",
            model_service_id=model_service_id,
            system_prompt=OFFICE_COORD_PROMPT,
            agent_type="COMPOSITE",
            tags=["demo", "demo-office", "coordinator"],
            skill_ids=[],
            kb_ids=[kb_office_pol.kb_id],
            tool_bindings=[],
            composition_config=office_coord_cfg,
            max_iterations=8,
        )
        _ensure_composition(
            db,
            office_coord,
            [
                {
                    "agent_id": office_meeting.agent_id,
                    "role_name": "会议督办",
                    "role_description": "会议查询、纪要与督办闭环",
                    "task_keywords": [
                        "会议", "纪要", "督办", "待办", "周会", "逾期", "行动项",
                    ],
                },
                {
                    "agent_id": office_expense.agent_id,
                    "role_name": "报销预审",
                    "role_description": "差旅与费用报销合规预审",
                    "task_keywords": [
                        "报销", "差旅", "费用", "发票", "招待", "超标", "驳回",
                    ],
                },
                {
                    "agent_id": office_facility.agent_id,
                    "role_name": "行政事务",
                    "role_description": "会议室、用印、办公用品",
                    "task_keywords": [
                        "会议室", "用印", "印章", "办公用品", "库存", "碳粉", "物资",
                    ],
                },
            ],
        )
        db.commit()
        _publish(db, office_coord)

        # --- PM COMPOSITE ---
        pm_research = _upsert_agent(
            db,
            name="demo-pm-research",
            description="产品经理·调研竞品 Specialist",
            model_service_id=model_service_id,
            system_prompt=PM_RESEARCH_PROMPT,
            agent_type="SINGLE",
            tags=["demo", "demo-pm", "specialist"],
            skill_ids=[skill_map["demo-pm-competitor-brief"].skill_pack_id],
            kb_ids=[kb_pm_play.kb_id, kb_pm_art.kb_id],
            tool_bindings=[
                (pm_tools["pm_list_competitors"].tool_id, False),
                (pm_tools["pm_get_competitor_matrix"].tool_id, False),
                (pm_tools["pm_list_feedback"].tool_id, False),
                (pm_tools["pm_list_interviews"].tool_id, False),
                (pm_tools["pm_list_backlog"].tool_id, False),
            ],
            composition_config=dict(_EAGER_TOOLS),
        )
        _publish(db, pm_research)

        pm_analytics = _upsert_agent(
            db,
            name="demo-pm-analytics",
            description="产品经理·数据分析 Specialist",
            model_service_id=model_service_id,
            system_prompt=PM_ANALYTICS_PROMPT,
            agent_type="SINGLE",
            tags=["demo", "demo-pm", "specialist"],
            skill_ids=[skill_map["demo-pm-metrics-insight"].skill_pack_id],
            kb_ids=[kb_pm_play.kb_id],
            tool_bindings=[
                (pm_tools["pm_query_metrics"].tool_id, False),
                (pm_tools["pm_query_funnel"].tool_id, False),
                (pm_tools["pm_list_experiments"].tool_id, False),
                (pm_tools["pm_list_events"].tool_id, False),
                (pm_tools["pm_list_roadmap"].tool_id, False),
            ],
            composition_config=dict(_EAGER_TOOLS),
        )
        _publish(db, pm_analytics)

        pm_prd = _upsert_agent(
            db,
            name="demo-pm-prd",
            description="产品经理·PRD撰写 Specialist",
            model_service_id=model_service_id,
            system_prompt=PM_PRD_PROMPT,
            agent_type="SINGLE",
            tags=["demo", "demo-pm", "specialist"],
            skill_ids=[skill_map["demo-pm-prd-draft"].skill_pack_id],
            kb_ids=[kb_pm_play.kb_id, kb_pm_art.kb_id],
            tool_bindings=[
                (pm_tools["pm_list_backlog"].tool_id, False),
                (pm_tools["pm_list_feedback"].tool_id, False),
                (pm_tools["pm_list_interviews"].tool_id, False),
                (pm_tools["pm_list_events"].tool_id, False),
                (pm_tools["pm_list_prds"].tool_id, False),
                (pm_tools["pm_submit_prd_draft"].tool_id, True),
            ],
            composition_config=dict(_EAGER_TOOLS),
        )
        _publish(db, pm_prd)

        pm_coord_cfg = {
            "dispatch_strategy": "llm",
            "max_dispatch_rounds": 3,
            "result_integration": "coordinator",
            "hitl_before_delivery": True,
            "total_token_budget": 800000,
            "max_a2a_calls": 12,
            "max_calls_per_agent": 2,
            "child_max_iterations": 6,
            "min_tokens_for_dispatch": 40000,
            **_EAGER_TOOLS,
        }
        pm_coord = _upsert_agent(
            db,
            name="demo-pm-coordinator",
            description="产品经理工作台 Coordinator（调研/数据/PRD COMPOSITE Demo）",
            model_service_id=model_service_id,
            system_prompt=PM_COORD_PROMPT,
            agent_type="COMPOSITE",
            tags=["demo", "demo-pm", "coordinator"],
            skill_ids=[],
            kb_ids=[kb_pm_play.kb_id],
            tool_bindings=[],
            composition_config=pm_coord_cfg,
            max_iterations=8,
        )
        _ensure_composition(
            db,
            pm_coord,
            [
                {
                    "agent_id": pm_research.agent_id,
                    "role_name": "调研竞品",
                    "role_description": "竞品、反馈、访谈证据与 backlog 启示",
                    "task_keywords": [
                        "竞品", "对标", "反馈", "访谈", "用户研究", "一页纸", "FlowApprove",
                    ],
                },
                {
                    "agent_id": pm_analytics.agent_id,
                    "role_name": "数据分析",
                    "role_description": "指标、漏斗、实验洞察",
                    "task_keywords": [
                        "指标", "DAU", "漏斗", "留存", "NPS", "实验", "AARRR", "数据",
                    ],
                },
                {
                    "agent_id": pm_prd.agent_id,
                    "role_name": "PRD撰写",
                    "role_description": "起草 PRD 与埋点方案",
                    "task_keywords": [
                        "PRD", "需求", "埋点", "用户故事", "验收", "草案", "文档",
                    ],
                },
            ],
        )
        db.commit()
        _publish(db, pm_coord)

        # --- Platform ops assistant ---
        ops = _upsert_agent(
            db,
            name="vela-ops-assistant",
            description="应用操作助手：通过 vela CLI 管理智能体、工具、审批等平台资源",
            model_service_id=model_service_id,
            system_prompt=OPS_PROMPT,
            tags=["platform", "ops", "builtin"],
            skill_ids=[],
            kb_ids=[],
            tool_bindings=ops_bindings,
            agent_type="SINGLE",
            composition_config=dict(_EAGER_TOOLS),
            max_iterations=20,
        )
        db.commit()
        _publish(db, ops)

        summary["agents"] = {
            "demo-audit-coordinator": coordinator.agent_id,
            "demo-audit-collector": collector.agent_id,
            "demo-audit-risk": risk.agent_id,
            "demo-audit-reporter": reporter.agent_id,
            "demo-hr-assistant": hr.agent_id,
            "demo-office-coordinator": office_coord.agent_id,
            "demo-office-meeting": office_meeting.agent_id,
            "demo-office-expense": office_expense.agent_id,
            "demo-office-facility": office_facility.agent_id,
            "demo-pm-coordinator": pm_coord.agent_id,
            "demo-pm-research": pm_research.agent_id,
            "demo-pm-analytics": pm_analytics.agent_id,
            "demo-pm-prd": pm_prd.agent_id,
            "vela-ops-assistant": ops.agent_id,
        }
        summary["model_service_id"] = model_service_id
        return summary
    finally:
        db.close()


def main() -> None:
    summary = seed_all()
    print("\n=== Demo seed complete ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\n推荐开场白：")
    print(
        "  [审计 Coordinator] 请对华北分公司总经理张伟开展 2024 年度经济责任审计立项："
        "收集任职期间经营与财务资料，识别主要风险点，并起草立项说明书草案。"
    )
    print(
        "  [HR 助手] 帮我看看候选人李娜是否适合后端高级工程师，"
        "并对照招聘与试用期制度给出面试建议；另外查一下研发中心剩余年假最多的 3 人。"
    )
    print(
        "  [办公 Coordinator] 汇总本周逾期督办，并预审徐娜的差旅报销单 E001 是否合规；"
        "同时看看哪些办公用品低于安全库存。"
    )
    print(
        "  [产品 Coordinator] 针对审批中心：结合 FlowApprove 竞品与用户反馈，"
        "用数据验证优先级，并起草「批量导出」PRD 草案。"
    )
    print(
        "  [应用操作助手] 列出当前所有已发布的智能体，并说明如何创建一个新草稿 Agent。"
    )


if __name__ == "__main__":
    main()
