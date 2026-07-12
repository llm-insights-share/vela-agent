"""ScreenPilot 驭屏引擎 Admin API"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models import ScreenCredential, ScreenSystem, UiAuditLog, gen_uuid, now_utc
from services.screenpilot.config import SCREENPILOT_ENABLED
from services.screenpilot.crypto_util import decrypt_secret, encrypt_secret

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/screenpilot", tags=["screenpilot"])


def _require_enabled():
    if not SCREENPILOT_ENABLED:
        raise HTTPException(status_code=503, detail="ScreenPilot 未启用，请设置 SCREENPILOT_ENABLED=true")


class ScreenSystemCreate(BaseModel):
    name: str = Field(..., max_length=128)
    entry_url: str = Field(default="", max_length=512)
    login_type: str = Field(default="form", max_length=32)
    exec_mode: str = Field(default="browser", max_length=16)
    allowed_domains: List[str] = Field(default_factory=list)
    login_macro: dict = Field(default_factory=dict)
    risk_rules: dict = Field(default_factory=dict)


class ScreenSystemUpdate(BaseModel):
    name: Optional[str] = None
    entry_url: Optional[str] = None
    login_type: Optional[str] = None
    exec_mode: Optional[str] = None
    allowed_domains: Optional[List[str]] = None
    login_macro: Optional[dict] = None
    risk_rules: Optional[dict] = None
    status: Optional[str] = None


class ScreenSystemResponse(BaseModel):
    system_id: str
    name: str
    entry_url: str
    login_type: str
    exec_mode: str
    allowed_domains: List[str] = []
    login_macro: dict = {}
    risk_rules: dict = {}
    status: str
    model_config = {"from_attributes": True}


class ScreenCredentialCreate(BaseModel):
    system_id: str
    label: str = "default"
    username: str = ""
    password: str = ""
    extra: dict = Field(default_factory=dict)


class ScreenCredentialResponse(BaseModel):
    credential_id: str
    system_id: str
    label: str
    username: str
    has_secret: bool = False
    model_config = {"from_attributes": True}


class McpTemplateResponse(BaseModel):
    name: str
    tool_type: str
    config: dict


@router.get("/status")
def screenpilot_status():
    return {"enabled": SCREENPILOT_ENABLED, "service": "vela-screenpilot"}


@router.get("/systems", response_model=List[ScreenSystemResponse])
def list_systems(db: Session = Depends(get_db)):
    _require_enabled()
    return db.query(ScreenSystem).order_by(ScreenSystem.created_at.desc()).all()


@router.post("/systems", response_model=ScreenSystemResponse, status_code=201)
def create_system(data: ScreenSystemCreate, db: Session = Depends(get_db)):
    _require_enabled()
    if db.query(ScreenSystem).filter(ScreenSystem.name == data.name).first():
        raise HTTPException(status_code=400, detail="系统名称已存在")
    row = ScreenSystem(
        system_id=gen_uuid(),
        name=data.name,
        entry_url=data.entry_url,
        login_type=data.login_type,
        exec_mode=data.exec_mode,
        allowed_domains=data.allowed_domains,
        login_macro=data.login_macro,
        risk_rules=data.risk_rules,
        status="ACTIVE",
        created_at=now_utc(),
        updated_at=now_utc(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/systems/{system_id}", response_model=ScreenSystemResponse)
def get_system(system_id: str, db: Session = Depends(get_db)):
    _require_enabled()
    row = db.query(ScreenSystem).filter(ScreenSystem.system_id == system_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="系统不存在")
    return row


@router.put("/systems/{system_id}", response_model=ScreenSystemResponse)
def update_system(system_id: str, data: ScreenSystemUpdate, db: Session = Depends(get_db)):
    _require_enabled()
    row = db.query(ScreenSystem).filter(ScreenSystem.system_id == system_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="系统不存在")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    row.updated_at = now_utc()
    db.commit()
    db.refresh(row)
    return row


@router.delete("/systems/{system_id}")
def delete_system(system_id: str, db: Session = Depends(get_db)):
    _require_enabled()
    row = db.query(ScreenSystem).filter(ScreenSystem.system_id == system_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="系统不存在")
    db.delete(row)
    db.commit()
    return {"success": True}


@router.post("/credentials", response_model=ScreenCredentialResponse, status_code=201)
def create_credential(data: ScreenCredentialCreate, db: Session = Depends(get_db)):
    _require_enabled()
    system = db.query(ScreenSystem).filter(ScreenSystem.system_id == data.system_id).first()
    if not system:
        raise HTTPException(status_code=404, detail="系统不存在")
    row = ScreenCredential(
        credential_id=gen_uuid(),
        system_id=data.system_id,
        label=data.label,
        username=data.username,
        secret_enc=encrypt_secret(data.password),
        extra=data.extra,
        created_at=now_utc(),
        updated_at=now_utc(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return ScreenCredentialResponse(
        credential_id=row.credential_id,
        system_id=row.system_id,
        label=row.label,
        username=row.username,
        has_secret=bool(row.secret_enc),
    )


@router.get("/systems/{system_id}/credentials", response_model=List[ScreenCredentialResponse])
def list_credentials(system_id: str, db: Session = Depends(get_db)):
    _require_enabled()
    rows = db.query(ScreenCredential).filter(ScreenCredential.system_id == system_id).all()
    return [
        ScreenCredentialResponse(
            credential_id=r.credential_id,
            system_id=r.system_id,
            label=r.label,
            username=r.username,
            has_secret=bool(r.secret_enc),
        )
        for r in rows
    ]


@router.get("/audit-logs")
def list_audit_logs(
    screen_session_id: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    _require_enabled()
    q = db.query(UiAuditLog).order_by(UiAuditLog.created_at.desc())
    if screen_session_id:
        q = q.filter(UiAuditLog.screen_session_id == screen_session_id)
    rows = q.limit(min(limit, 200)).all()
    return [
        {
            "log_id": r.log_id,
            "screen_session_id": r.screen_session_id,
            "action": r.action,
            "risk_tier": r.risk_tier,
            "payload": r.payload,
            "screenshot_path": r.screenshot_path,
            "approval_id": r.approval_id,
            "prev_hash": r.prev_hash,
            "content_hash": r.content_hash,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.get("/mcp-template", response_model=McpTemplateResponse)
def get_mcp_template():
    """一键注册 ScreenPilot MCP 工具的配置模板。"""
    import sys
    import os

    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    python = sys.executable
    return McpTemplateResponse(
        name="vela-screenpilot",
        tool_type="MCP",
        config={
            "mcp_command": python,
            "mcp_args": ["-m", "services.screenpilot.mcp_server"],
            "mcp_env": {"SCREENPILOT_ENABLED": "true", "PYTHONPATH": backend_dir},
            "mcp_tool_name": "ui_navigate,ui_observe,ui_act,ui_extract,ui_replay_skill,ui_compile_skill,ui_search_skills",
            "description": "驭屏引擎 ScreenPilot — 企业内系统 UI 自动化（P1 含技能编译/重放）",
        },
    )


class SkillCompileRequest(BaseModel):
    screen_session_id: str
    name: str
    description: str = ""
    scope: str = "default"


class SkillSearchRequest(BaseModel):
    query: str
    scope: str = "default"
    top_k: int = 5


class SkillReplayRequest(BaseModel):
    skill_id: str
    screen_session_id: str
    params: dict = Field(default_factory=dict)
    vela_session_id: str = ""
    agent_id: str = ""


@router.get("/skills")
def list_skills(scope: Optional[str] = None, db: Session = Depends(get_db)):
    _require_enabled()
    from models import UiSkill, UiSkillStep

    q = db.query(UiSkill).filter(UiSkill.status == "ACTIVE")
    if scope:
        q = q.filter(UiSkill.scope == scope)
    skills = q.order_by(UiSkill.created_at.desc()).all()
    out = []
    for s in skills:
        step_count = db.query(UiSkillStep).filter(UiSkillStep.skill_id == s.skill_id).count()
        out.append(
            {
                "skill_id": s.skill_id,
                "name": s.name,
                "description": s.description,
                "system_id": s.system_id,
                "scope": s.scope,
                "step_count": step_count,
                "param_schema": s.param_schema,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
        )
    return out


@router.get("/skills/{skill_id}")
def get_skill_detail(skill_id: str, db: Session = Depends(get_db)):
    _require_enabled()
    from services.screenpilot.skill_store import skill_store

    skill = skill_store.get_skill(db, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")
    steps = skill_store.get_steps(db, skill_id)
    return {
        "skill_id": skill.skill_id,
        "name": skill.name,
        "description": skill.description,
        "system_id": skill.system_id,
        "scope": skill.scope,
        "param_schema": skill.param_schema,
        "steps": [
            {
                "step_id": st.step_id,
                "step_order": st.step_order,
                "action": st.action,
                "target_label": st.target_label,
                "value_template": st.value_template,
                "fingerprints": st.fingerprints,
            }
            for st in steps
        ],
    }


@router.post("/skills/compile")
async def compile_skill_api(body: SkillCompileRequest, db: Session = Depends(get_db)):
    _require_enabled()
    from services.screenpilot.service import compile_skill

    return await compile_skill(
        db,
        screen_session_id=body.screen_session_id,
        name=body.name,
        description=body.description,
        scope=body.scope,
    )


@router.post("/skills/search")
async def search_skills_api(body: SkillSearchRequest, db: Session = Depends(get_db)):
    _require_enabled()
    from services.screenpilot.service import search_skills

    return await search_skills(db, query=body.query, scope=body.scope, top_k=body.top_k)


@router.post("/skills/replay")
async def replay_skill_api(body: SkillReplayRequest, db: Session = Depends(get_db)):
    _require_enabled()
    from services.screenpilot.service import replay_skill

    return await replay_skill(
        db,
        skill_id=body.skill_id,
        screen_session_id=body.screen_session_id,
        params=body.params,
        vela_session_id=body.vela_session_id,
        agent_id=body.agent_id,
    )
