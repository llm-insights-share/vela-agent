from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from database import get_db
from models import (
    Agent, AgentVersion, AgentStatus, AgentSkillBinding, AgentKnowledgeBinding,
    AgentToolBinding, ModelService, ModelProvider, SkillPack, KnowledgeBase, Tool,
    gen_uuid, now_utc
)
from schemas import (
    AgentCreate, AgentUpdate, AgentResponse, AgentVersionResponse,
    AgentPublishRequest, ValidationResult, PaginatedResponse
)
from services.agent_service import agent_service

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


@router.get("", response_model=PaginatedResponse)
def list_agents(
    name: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    dept_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(Agent)
    if name:
        query = query.filter(Agent.name.contains(name))
    if status:
        query = query.filter(Agent.status == status)
    if dept_id:
        query = query.filter(Agent.dept_id == dept_id)
    query = query.filter(Agent.status != AgentStatus.DELETED)

    total = query.count()
    agents = query.order_by(Agent.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for a in agents:
        d = _agent_to_dict(a, db)
        items.append(d)

    return PaginatedResponse(total=total, page=page, page_size=page_size, items=items)


@router.post("", response_model=AgentResponse, status_code=201)
def create_agent(data: AgentCreate, db: Session = Depends(get_db)):
    existing = db.query(Agent).filter(Agent.name == data.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Agent 名称已存在")

    model_svc = db.query(ModelService).filter(
        ModelService.model_service_id == data.model_service_id
    ).first()
    if not model_svc:
        raise HTTPException(status_code=400, detail="模型服务不存在")

    agent = agent_service.create_agent(db, data)
    return _agent_to_dict(agent, db)


@router.get("/{agent_id}", response_model=AgentResponse)
def get_agent(agent_id: str, db: Session = Depends(get_db)):
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    return _agent_to_dict(agent, db)


@router.put("/{agent_id}", response_model=AgentResponse)
def update_agent(agent_id: str, data: AgentUpdate, db: Session = Depends(get_db)):
    agent = agent_service.update_agent(db, agent_id, data)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    return _agent_to_dict(agent, db)


@router.delete("/{agent_id}")
def delete_agent(agent_id: str, db: Session = Depends(get_db)):
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    agent.status = AgentStatus.DELETED
    db.commit()
    return {"message": "Agent 已删除"}


@router.post("/{agent_id}/deprecate")
def deprecate_agent(agent_id: str, db: Session = Depends(get_db)):
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    agent.status = AgentStatus.DEPRECATED
    db.commit()
    return {"message": "Agent 已下架"}


@router.post("/{agent_id}/republish")
def republish_agent(agent_id: str, db: Session = Depends(get_db)):
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    if agent.status != AgentStatus.DEPRECATED:
        raise HTTPException(status_code=400, detail="只有已下架的 Agent 才能重新上架")
    agent.status = AgentStatus.PUBLISHED
    db.commit()
    return {"message": "Agent 已重新上架"}


@router.get("/{agent_id}/versions", response_model=list[AgentVersionResponse])
def list_versions(agent_id: str, db: Session = Depends(get_db)):
    versions = db.query(AgentVersion).filter(
        AgentVersion.agent_id == agent_id
    ).order_by(AgentVersion.version_seq.desc()).all()
    return [
        AgentVersionResponse.model_validate(v) for v in versions
    ]


@router.post("/{agent_id}/validate", response_model=ValidationResult)
def validate_agent(agent_id: str, db: Session = Depends(get_db)):
    return agent_service.validate_agent(db, agent_id)


@router.post("/{agent_id}/publish", response_model=AgentResponse)
def publish_agent(agent_id: str, data: AgentPublishRequest, db: Session = Depends(get_db)):
    result = agent_service.validate_agent(db, agent_id)
    if not result.passed:
        raise HTTPException(status_code=400, detail={
            "message": "校验未通过，无法发布",
            "errors": result.errors,
        })

    agent = agent_service.publish_agent(db, agent_id, data.version_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    return _agent_to_dict(agent, db)


@router.post("/{agent_id}/rollback")
def rollback_agent(agent_id: str, version_id: str = Query(...), db: Session = Depends(get_db)):
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")

    target = db.query(AgentVersion).filter(
        AgentVersion.version_id == version_id,
        AgentVersion.agent_id == agent_id
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="版本不存在")

    current = db.query(AgentVersion).filter(
        AgentVersion.version_id == agent.current_version_id
    ).first()
    if current:
        current.status = "DEPRECATED"

    target.status = "PUBLISHED"
    agent.current_version_id = target.version_id
    agent.status = AgentStatus.PUBLISHED
    db.commit()

    return _agent_to_dict(agent, db)


@router.get("/{agent_id}/skills", response_model=list)
def get_agent_skills(agent_id: str, db: Session = Depends(get_db)):
    bindings = db.query(AgentSkillBinding).filter(
        AgentSkillBinding.agent_id == agent_id
    ).all()
    result = []
    for b in bindings:
        skill = db.query(SkillPack).filter(SkillPack.skill_pack_id == b.skill_pack_id).first()
        result.append({
            "skill_pack_id": b.skill_pack_id,
            "name": skill.name if skill else b.skill_pack_id,
            "description": skill.description if skill else "",
            "version": skill.version if skill else "",
            "tool_permissions": b.tool_permissions,
        })
    return result


@router.put("/{agent_id}/skills")
def bind_agent_skills(agent_id: str, skill_pack_ids: list[str], db: Session = Depends(get_db)):
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")

    db.query(AgentSkillBinding).filter(
        AgentSkillBinding.agent_id == agent_id
    ).delete()

    for sp_id in skill_pack_ids:
        binding = AgentSkillBinding(
            agent_id=agent_id,
            skill_pack_id=sp_id,
            tool_permissions=agent.tool_permissions or {},
        )
        db.add(binding)

    db.commit()
    return {"message": "Skill 包绑定已更新", "skill_pack_ids": skill_pack_ids}


@router.get("/{agent_id}/knowledge-bases", response_model=list)
def get_agent_knowledge_bases(agent_id: str, db: Session = Depends(get_db)):
    bindings = db.query(AgentKnowledgeBinding).filter(
        AgentKnowledgeBinding.agent_id == agent_id
    ).all()
    result = []
    for b in bindings:
        kb = db.query(KnowledgeBase).filter(KnowledgeBase.kb_id == b.kb_id).first()
        result.append({
            "kb_id": b.kb_id,
            "name": kb.name if kb else b.kb_id,
            "description": kb.description if kb else "",
            "doc_count": kb.doc_count if kb else 0,
        })
    return result


@router.put("/{agent_id}/knowledge-bases")
def bind_agent_knowledge_bases(agent_id: str, kb_ids: list[str], db: Session = Depends(get_db)):
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")

    db.query(AgentKnowledgeBinding).filter(
        AgentKnowledgeBinding.agent_id == agent_id
    ).delete()

    for kb_id in kb_ids:
        binding = AgentKnowledgeBinding(agent_id=agent_id, kb_id=kb_id)
        db.add(binding)

    db.commit()
    return {"message": "知识库绑定已更新", "kb_ids": kb_ids}


@router.get("/{agent_id}/tools", response_model=list)
def get_agent_tools(agent_id: str, db: Session = Depends(get_db)):
    bindings = db.query(AgentToolBinding).filter(
        AgentToolBinding.agent_id == agent_id
    ).all()
    result = []
    for b in bindings:
        tool = db.query(Tool).filter(Tool.tool_id == b.tool_id).first()
        result.append({
            "tool_id": b.tool_id,
            "name": tool.name if tool else b.tool_id,
            "display_name": tool.display_name if tool else "",
            "description": tool.description if tool else "",
            "tool_type": tool.tool_type.value if tool and tool.tool_type else "",
            "permission": b.permission,
        })
    return result


@router.put("/{agent_id}/tools")
def bind_agent_tools(agent_id: str, tool_ids: list[str], db: Session = Depends(get_db)):
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")

    db.query(AgentToolBinding).filter(
        AgentToolBinding.agent_id == agent_id
    ).delete()

    for tid in tool_ids:
        binding = AgentToolBinding(
            agent_id=agent_id,
            tool_id=tid,
            permission="allowed",
        )
        db.add(binding)

    db.commit()
    return {"message": "工具绑定已更新", "tool_ids": tool_ids}


def _agent_to_dict(agent: Agent, db: Session) -> dict:
    model_svc = db.query(ModelService).filter(
        ModelService.model_service_id == agent.model_service_id
    ).first()
    model_name = model_svc.display_name if model_svc else ""

    current_version = None
    if agent.current_version_id:
        ver = db.query(AgentVersion).filter(
            AgentVersion.version_id == agent.current_version_id
        ).first()
        if ver:
            current_version = ver.version

    skill_ids = [
        b.skill_pack_id for b in db.query(AgentSkillBinding).filter(
            AgentSkillBinding.agent_id == agent.agent_id
        ).all()
    ]
    skill_names = []
    for sid in skill_ids:
        sk = db.query(SkillPack).filter(SkillPack.skill_pack_id == sid).first()
        skill_names.append(sk.name if sk else sid)
    kb_ids = [
        b.kb_id for b in db.query(AgentKnowledgeBinding).filter(
            AgentKnowledgeBinding.agent_id == agent.agent_id
        ).all()
    ]
    kb_names = []
    for kid in kb_ids:
        kb = db.query(KnowledgeBase).filter(KnowledgeBase.kb_id == kid).first()
        kb_names.append(kb.name if kb else kid)

    tool_ids = [
        b.tool_id for b in db.query(AgentToolBinding).filter(
            AgentToolBinding.agent_id == agent.agent_id
        ).all()
    ]
    tool_names = []
    for tid in tool_ids:
        t = db.query(Tool).filter(Tool.tool_id == tid).first()
        tool_names.append(t.display_name or t.name if t else tid)

    return {
        "agent_id": agent.agent_id,
        "name": agent.name,
        "description": agent.description or "",
        "model_service_id": agent.model_service_id or "",
        "model_name": model_name,
        "system_prompt": agent.system_prompt or "",
        "dept_id": agent.dept_id or "",
        "autonomy_level": agent.autonomy_level or "L2",
        "max_concurrent_sessions": agent.max_concurrent_sessions or 5,
        "token_budget": agent.token_budget or 100000,
        "tool_permissions": agent.tool_permissions or {},
        "tags": agent.tags or [],
        "status": agent.status.value if agent.status else "DRAFT",
        "current_version_id": agent.current_version_id,
        "current_version": current_version,
        "skill_pack_ids": skill_ids,
        "skill_pack_names": skill_names,
        "knowledge_base_ids": kb_ids,
        "knowledge_base_names": kb_names,
        "tool_ids": tool_ids,
        "tool_names": tool_names,
        "created_at": agent.created_at,
        "updated_at": agent.updated_at,
    }