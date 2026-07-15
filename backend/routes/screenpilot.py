"""ScreenPilot 驭屏引擎 Admin API"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models import ScreenCredential, ScreenSystem, UiAuditLog, gen_uuid, now_utc
from services.screenpilot.config import is_screenpilot_enabled
from services.screenpilot.crypto_util import decrypt_secret, encrypt_secret

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/screenpilot", tags=["screenpilot"])


def _require_enabled():
    if not is_screenpilot_enabled():
        raise HTTPException(status_code=503, detail="ScreenPilot 未启用，请在系统配置中打开驭屏系统")


class ScreenSystemCreate(BaseModel):
    name: str = Field(..., max_length=128)
    entry_url: str = Field(default="", max_length=512)
    login_type: str = Field(default="form", max_length=32)
    exec_mode: str = Field(default="browser", max_length=16)
    allowed_domains: List[str] = Field(default_factory=list)
    login_macro: dict = Field(default_factory=dict)
    risk_rules: dict = Field(default_factory=dict)
    reuse_local_browser: bool = False
    cdp_url: str = Field(default="", max_length=512)


class ScreenSystemUpdate(BaseModel):
    name: Optional[str] = None
    entry_url: Optional[str] = None
    login_type: Optional[str] = None
    exec_mode: Optional[str] = None
    allowed_domains: Optional[List[str]] = None
    login_macro: Optional[dict] = None
    risk_rules: Optional[dict] = None
    reuse_local_browser: Optional[bool] = None
    cdp_url: Optional[str] = None
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
    reuse_local_browser: bool = False
    cdp_url: str = ""
    status: str
    model_config = {"from_attributes": True}


class ScreenCredentialCreate(BaseModel):
    system_id: str
    name: str
    value: str = ""


class ScreenCredentialUpdate(BaseModel):
    value: str = ""


class ScreenCredentialResponse(BaseModel):
    credential_id: str
    system_id: str
    name: str
    has_value: bool = False
    model_config = {"from_attributes": True}


class McpTemplateResponse(BaseModel):
    name: str
    tool_type: str
    config: dict


@router.get("/mcp/status")
def mcp_pool_status():
    _require_enabled()
    from services.screenpilot.mcp_pool import screenpilot_mcp_pool

    alive = (
        screenpilot_mcp_pool._process is not None
        and screenpilot_mcp_pool._process.returncode is None
    )
    return {
        "adapter": "screenpilot",
        "inprocess_available": True,
        "pool_process_alive": alive,
        "tools": 8,
    }


@router.get("/status")
def screenpilot_status(db: Session = Depends(get_db)):
    from services.screenpilot.mcp_tools import list_registered_cu_tools

    tools = list_registered_cu_tools(db)
    return {
        "enabled": is_screenpilot_enabled(),
        "service": "vela-screenpilot",
        "mcp_registered": len(tools) >= 8,
        "mcp_tools": tools,
    }


@router.get("/cdp/status")
async def cdp_status(url: Optional[str] = None):
    """探测本机 Chrome/Edge CDP 是否可达（复用本地浏览器会话）。"""
    _require_enabled()
    from services.screenpilot.session_manager import probe_cdp

    return await probe_cdp(url or "")


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
        reuse_local_browser=bool(data.reuse_local_browser),
        cdp_url=(data.cdp_url or "").strip(),
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
    payload = data.model_dump(exclude_unset=True)
    if "status" in payload and payload["status"] not in ("ACTIVE", "INACTIVE"):
        raise HTTPException(status_code=400, detail="status 仅支持 ACTIVE 或 INACTIVE")
    if "name" in payload and payload["name"] != row.name:
        clash = (
            db.query(ScreenSystem)
            .filter(ScreenSystem.name == payload["name"], ScreenSystem.system_id != system_id)
            .first()
        )
        if clash:
            raise HTTPException(status_code=400, detail="系统名称已存在")
    for k, v in payload.items():
        setattr(row, k, v)
    row.updated_at = now_utc()
    db.commit()
    db.refresh(row)
    return row


@router.delete("/systems/{system_id}")
def delete_system(system_id: str, db: Session = Depends(get_db)):
    _require_enabled()
    from models import ScreenSession, UiSkill, UiSkillStep

    row = db.query(ScreenSystem).filter(ScreenSystem.system_id == system_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="系统不存在")

    skill_ids = [
        s.skill_id
        for s in db.query(UiSkill).filter(UiSkill.system_id == system_id).all()
    ]
    if skill_ids:
        db.query(UiSkillStep).filter(UiSkillStep.skill_id.in_(skill_ids)).delete(
            synchronize_session=False
        )
        db.query(UiSkill).filter(UiSkill.system_id == system_id).delete(synchronize_session=False)
    db.query(ScreenCredential).filter(ScreenCredential.system_id == system_id).delete(
        synchronize_session=False
    )
    db.query(ScreenSession).filter(ScreenSession.system_id == system_id).delete(
        synchronize_session=False
    )
    db.delete(row)
    db.commit()
    return {"success": True}


@router.post("/credentials", response_model=ScreenCredentialResponse, status_code=201)
def create_credential(data: ScreenCredentialCreate, db: Session = Depends(get_db)):
    _require_enabled()
    system = db.query(ScreenSystem).filter(ScreenSystem.system_id == data.system_id).first()
    if not system:
        raise HTTPException(status_code=404, detail="系统不存在")
    name = (data.name or "").strip()
    if not name or name.startswith("__"):
        raise HTTPException(status_code=400, detail="凭证 name 无效")
    existing = (
        db.query(ScreenCredential)
        .filter(
            ScreenCredential.system_id == data.system_id,
            ScreenCredential.name == name,
        )
        .first()
    )
    if existing:
        existing.value_enc = encrypt_secret(data.value or "")
        existing.updated_at = now_utc()
        db.commit()
        db.refresh(existing)
        return ScreenCredentialResponse(
            credential_id=existing.credential_id,
            system_id=existing.system_id,
            name=existing.name,
            has_value=bool(existing.value_enc),
        )
    row = ScreenCredential(
        credential_id=gen_uuid(),
        system_id=data.system_id,
        name=name,
        value_enc=encrypt_secret(data.value or ""),
        created_at=now_utc(),
        updated_at=now_utc(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return ScreenCredentialResponse(
        credential_id=row.credential_id,
        system_id=row.system_id,
        name=row.name,
        has_value=bool(row.value_enc),
    )


@router.get("/systems/{system_id}/credentials", response_model=List[ScreenCredentialResponse])
def list_credentials(system_id: str, db: Session = Depends(get_db)):
    _require_enabled()
    rows = (
        db.query(ScreenCredential)
        .filter(ScreenCredential.system_id == system_id)
        .order_by(ScreenCredential.name.asc())
        .all()
    )
    return [
        ScreenCredentialResponse(
            credential_id=r.credential_id,
            system_id=r.system_id,
            name=r.name,
            has_value=bool(r.value_enc),
        )
        for r in rows
        if not (r.name or "").startswith("__")
    ]


@router.put("/credentials/{credential_id}", response_model=ScreenCredentialResponse)
def update_credential(
    credential_id: str,
    data: ScreenCredentialUpdate,
    db: Session = Depends(get_db),
):
    _require_enabled()
    row = db.query(ScreenCredential).filter(ScreenCredential.credential_id == credential_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="凭证不存在")
    if (row.name or "").startswith("__"):
        raise HTTPException(status_code=400, detail="系统内部凭证不可修改")
    row.value_enc = encrypt_secret(data.value or "")
    row.updated_at = now_utc()
    db.commit()
    db.refresh(row)
    return ScreenCredentialResponse(
        credential_id=row.credential_id,
        system_id=row.system_id,
        name=row.name,
        has_value=bool(row.value_enc),
    )


@router.delete("/credentials/{credential_id}")
def delete_credential(credential_id: str, db: Session = Depends(get_db)):
    _require_enabled()
    row = db.query(ScreenCredential).filter(ScreenCredential.credential_id == credential_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="凭证不存在")
    if (row.name or "").startswith("__"):
        raise HTTPException(status_code=400, detail="系统内部凭证不可删除")
    db.delete(row)
    db.commit()
    return {"success": True}


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
    """ScreenPilot MCP 工具配置模板（cu_*）。"""
    from services.screenpilot.config import CU_TOOL_NAMES
    from services.screenpilot.mcp_tools import mcp_runtime_config

    cfg = mcp_runtime_config()
    cfg["mcp_tool_name"] = ",".join(CU_TOOL_NAMES)
    return McpTemplateResponse(
        name="vela-screenpilot",
        tool_type="MCP",
        config=cfg,
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
                "visibility": getattr(s, "visibility", "PRIVATE") or "PRIVATE",
                "step_count": step_count,
                "param_schema": s.param_schema,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
        )
    return out


# --- P2: 技能商店（须在 /skills/{skill_id} 之前注册） ---


class SkillPublishRequest(BaseModel):
    visibility: str = Field(default="DEPARTMENT", pattern="^(DEPARTMENT|PUBLIC)$")
    publisher_id: str = ""


class SkillImportRequest(BaseModel):
    target_scope: str = "default"
    new_name: Optional[str] = None


@router.get("/skills/shop")
def list_skill_shop(
    scope: Optional[str] = None,
    visibility: Optional[str] = None,
    query: Optional[str] = None,
    top_k: int = 20,
    db: Session = Depends(get_db),
):
    _require_enabled()
    from services.screenpilot.skill_shop import list_shop_skills

    return list_shop_skills(
        db, scope=scope, visibility=visibility, query=query, top_k=top_k
    )


class SkillUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class SkillStepUpdateRequest(BaseModel):
    action: Optional[str] = None
    target_label: Optional[str] = None
    value_template: Optional[str] = None
    note: Optional[str] = None
    fingerprints: Optional[dict] = None


def _step_to_dict(st) -> dict:
    meta = st.meta or {}
    return {
        "step_id": st.step_id,
        "step_order": st.step_order,
        "action": st.action,
        "target_label": st.target_label or "",
        "value_template": st.value_template or "",
        "note": (meta.get("note") if isinstance(meta, dict) else "") or "",
        "fingerprints": st.fingerprints or {},
        "meta": meta if isinstance(meta, dict) else {},
    }


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
        "description": skill.description or "",
        "system_id": skill.system_id,
        "scope": skill.scope,
        "status": skill.status or "ACTIVE",
        "visibility": getattr(skill, "visibility", "PRIVATE") or "PRIVATE",
        "param_schema": skill.param_schema,
        "steps": [_step_to_dict(st) for st in steps],
    }


@router.put("/skills/{skill_id}")
def update_skill_api(skill_id: str, body: SkillUpdateRequest, db: Session = Depends(get_db)):
    _require_enabled()
    from services.screenpilot.skill_store import skill_store

    skill = skill_store.update_skill_meta(
        db,
        skill_id,
        name=body.name,
        description=body.description,
    )
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")
    return {
        "skill_id": skill.skill_id,
        "name": skill.name,
        "description": skill.description or "",
        "visibility": getattr(skill, "visibility", "PRIVATE") or "PRIVATE",
        "status": skill.status or "ACTIVE",
    }


@router.put("/skills/{skill_id}/steps/{step_id}")
def update_skill_step_api(
    skill_id: str,
    step_id: str,
    body: SkillStepUpdateRequest,
    db: Session = Depends(get_db),
):
    _require_enabled()
    from services.screenpilot.skill_store import skill_store

    if not skill_store.get_skill(db, skill_id):
        raise HTTPException(status_code=404, detail="技能不存在")
    step = skill_store.update_step(
        db,
        skill_id,
        step_id,
        action=body.action,
        target_label=body.target_label,
        value_template=body.value_template,
        note=body.note,
        fingerprints=body.fingerprints,
    )
    if not step:
        raise HTTPException(status_code=404, detail="步骤不存在")
    return _step_to_dict(step)


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


# --- P2: 技能商店 API ---


@router.post("/skills/{skill_id}/publish")
def publish_skill_api(skill_id: str, body: SkillPublishRequest, db: Session = Depends(get_db)):
    _require_enabled()
    from services.screenpilot.skill_shop import publish_skill

    skill = publish_skill(
        db, skill_id, visibility=body.visibility, publisher_id=body.publisher_id
    )
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")
    return {
        "skill_id": skill.skill_id,
        "visibility": skill.visibility,
        "published_at": skill.published_at.isoformat() if skill.published_at else None,
    }


@router.post("/skills/{skill_id}/unpublish")
def unpublish_skill_api(skill_id: str, db: Session = Depends(get_db)):
    _require_enabled()
    from services.screenpilot.skill_shop import unpublish_skill

    skill = unpublish_skill(db, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")
    return {"skill_id": skill.skill_id, "visibility": skill.visibility}


@router.delete("/skills/{skill_id}")
def delete_skill_api(skill_id: str, db: Session = Depends(get_db)):
    """仅允许删除未发布（私有/已下架）技能。"""
    _require_enabled()
    from services.screenpilot.skill_store import skill_store

    skill = skill_store.get_skill(db, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")
    visibility = (getattr(skill, "visibility", None) or "PRIVATE").upper()
    if visibility in ("DEPARTMENT", "PUBLIC"):
        raise HTTPException(status_code=400, detail="请先下架后再删除该技能")
    ok = skill_store.delete_skill(db, skill_id)
    if not ok:
        raise HTTPException(status_code=404, detail="技能不存在")
    return {"success": True, "skill_id": skill_id}


@router.post("/skills/{skill_id}/import")
def import_skill_api(skill_id: str, body: SkillImportRequest, db: Session = Depends(get_db)):
    _require_enabled()
    from services.screenpilot.skill_shop import import_skill_to_scope

    skill = import_skill_to_scope(
        db, skill_id, body.target_scope, new_name=body.new_name
    )
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在或不可导入")
    return {"skill_id": skill.skill_id, "name": skill.name, "scope": skill.scope}


@router.post("/skills/reindex")
def reindex_skills(scope: str = "default", db: Session = Depends(get_db)):
    _require_enabled()
    from services.screenpilot.skill_store import skill_store

    skill_store.rebuild_scope_from_db(db, scope)
    return {"success": True, "scope": scope, "message": "FAISS 索引已重建"}


# --- P2: 风险策略优化 ---


@router.get("/risk/analyze")
def analyze_risk_strategy(limit: int = 500, db: Session = Depends(get_db)):
    _require_enabled()
    from services.screenpilot.risk_optimizer import analyze_audit_samples

    return analyze_audit_samples(db, limit=limit)


class RiskApplyRequest(BaseModel):
    system_id: str
    min_confidence: float = 0.7


@router.post("/risk/optimize")
def optimize_risk_rules(body: RiskApplyRequest, db: Session = Depends(get_db)):
    _require_enabled()
    from services.screenpilot.risk_optimizer import analyze_audit_samples, apply_suggestions_to_rules

    system = db.query(ScreenSystem).filter(ScreenSystem.system_id == body.system_id).first()
    if not system:
        raise HTTPException(status_code=404, detail="系统不存在")

    analysis = analyze_audit_samples(db)
    new_rules = apply_suggestions_to_rules(
        system.risk_rules or {},
        analysis.get("suggestions") or [],
        min_confidence=body.min_confidence,
    )
    system.risk_rules = new_rules
    system.updated_at = now_utc()
    db.commit()
    return {
        "system_id": system.system_id,
        "risk_rules": new_rules,
        "applied_suggestions": len(analysis.get("suggestions") or []),
        "analysis": analysis,
    }


# --- P2: Integration Gateway ---


@router.get("/gateway/status")
async def gateway_status():
    _require_enabled()
    from services.screenpilot.integration_gateway import oauth_configured, get_access_token

    token_ok = False
    if oauth_configured():
        token = await get_access_token()
        token_ok = bool(token)

    return {
        "oauth_configured": oauth_configured(),
        "oauth_token_ok": token_ok,
    }


# --- P2: Vela 内置审批流（T3 收件箱） ---


class ApprovalReviewRequest(BaseModel):
    reviewer: str = ""
    comment: str = ""
    otp_code: str = ""


@router.get("/approvals")
def list_approvals(
    risk_tier: Optional[str] = None,
    status: str = "PENDING",
    limit: int = 50,
    db: Session = Depends(get_db),
):
    _require_enabled()
    from services.screenpilot.internal_approval import list_pending_approvals

    return list_pending_approvals(db, risk_tier=risk_tier, status=status, limit=limit)


@router.get("/approvals/{approval_id}")
def get_approval(approval_id: str, db: Session = Depends(get_db)):
    _require_enabled()
    from services.screenpilot.internal_approval import get_approval_detail

    detail = get_approval_detail(db, approval_id)
    if not detail:
        raise HTTPException(status_code=404, detail="审批工单不存在")
    return detail


@router.post("/approvals/{approval_id}/approve")
def approve_screenpilot(
    approval_id: str,
    body: ApprovalReviewRequest,
    db: Session = Depends(get_db),
):
    """平台审批收件箱：批准 ScreenPilot 工单（复用 HITL 执行链路）。"""
    _require_enabled()
    from models import HITLApproval
    from routes.hitl import approve_action
    from schemas import HITLReview

    row = db.query(HITLApproval).filter(HITLApproval.approval_id == approval_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="审批工单不存在")

    # #region agent log
    try:
        import json as _json, time as _time
        with open("/Users/zhangjr/apps/LlmDemo/vibe-project/vela-agent/.cursor/debug-66b153.log", "a") as _f:
            _f.write(_json.dumps({
                "sessionId": "66b153", "runId": "hitl-fix", "hypothesisId": "H1",
                "location": "routes/screenpilot.py:approve_screenpilot",
                "message": "approve inbox request",
                "data": {
                    "approval_id": approval_id,
                    "tool_name": row.tool_name,
                    "session_id": (row.session_id or "")[:40],
                    "has_otp": bool((body.otp_code or "").strip() or (body.comment or "").strip()),
                },
                "timestamp": int(_time.time() * 1000),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # #endregion

    review = HITLReview(
        approved=True,
        reviewer=body.reviewer or "vela_approver",
        comment=body.comment or "",
        otp_code=(body.otp_code or None) or None,
    )
    return approve_action(row.session_id, approval_id, review, db)


@router.post("/approvals/{approval_id}/reject")
def reject_screenpilot(
    approval_id: str,
    body: ApprovalReviewRequest,
    db: Session = Depends(get_db),
):
    _require_enabled()
    from models import HITLApproval
    from routes.hitl import reject_action
    from schemas import HITLReview

    row = db.query(HITLApproval).filter(HITLApproval.approval_id == approval_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="审批工单不存在")

    # #region agent log
    try:
        import json as _json, time as _time
        with open("/Users/zhangjr/apps/LlmDemo/vibe-project/vela-agent/.cursor/debug-66b153.log", "a") as _f:
            _f.write(_json.dumps({
                "sessionId": "66b153", "runId": "hitl-fix", "hypothesisId": "H1",
                "location": "routes/screenpilot.py:reject_screenpilot",
                "message": "reject inbox request",
                "data": {
                    "approval_id": approval_id,
                    "tool_name": row.tool_name,
                    "session_id": (row.session_id or "")[:40],
                },
                "timestamp": int(_time.time() * 1000),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # #endregion

    review = HITLReview(
        approved=False,
        reviewer=body.reviewer or "vela_approver",
        comment=body.comment or "",
    )
    return reject_action(row.session_id, approval_id, review, db)
