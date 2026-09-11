"""Idempotent seed for audit (COMPOSITE) and HR (SINGLE) demos.

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
) -> Tool:
    config = {
        "module": "demo_tools",
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


def seed_all() -> Dict[str, Any]:
    init_db()
    _build_sqlite("audit")
    _build_sqlite("hr")

    db = SessionLocal()
    summary: Dict[str, Any] = {"agents": {}, "skills": [], "kbs": [], "tools": []}
    try:
        model_service_id = _resolve_model_service_id(db)
        _log(f"model_service_id={model_service_id}")
        ks = KnowledgeService()

        # Skills
        skill_map: Dict[str, SkillPack] = {}
        for path in sorted((_DEMOS / "audit" / "skills").glob("*.md")):
            skill_map[path.stem] = _upsert_skill(db, path)
        for path in sorted((_DEMOS / "hr" / "skills").glob("*.md")):
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
        summary["kbs"] = [kb_reg.name, kb_tpl.name, kb_pol.name, kb_jd.name]

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
        summary["tools"] = list(audit_tools) + list(hr_tools)
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

        summary["agents"] = {
            "demo-audit-coordinator": coordinator.agent_id,
            "demo-audit-collector": collector.agent_id,
            "demo-audit-risk": risk.agent_id,
            "demo-audit-reporter": reporter.agent_id,
            "demo-hr-assistant": hr.agent_id,
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


if __name__ == "__main__":
    main()
