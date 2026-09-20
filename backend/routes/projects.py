"""Claude-style Projects API."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from database import get_db
from deps import CurrentUser
from models import (
    Agent,
    KnowledgeBase,
    KnowledgeBaseStatus,
    Project,
    ProjectMember,
    ProjectMemberRole,
    ProjectStar,
    ProjectStatus,
    Session as SessionModel,
    User,
    now_utc,
)
from schemas import (
    PaginatedResponse,
    ProjectCreate,
    ProjectMemberAdd,
    ProjectMemberOut,
    ProjectMemberUpdate,
    ProjectResponse,
    ProjectUpdate,
    SessionResponse,
)
from services import project_service as ps
from services.knowledge_service import knowledge_service as ks
from services.session_title import ensure_session_title
from services.agent_service import _ensure_files_for_session

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


async def _maybe_contextualize(kb, db, chunks, document_text, filename):
    from services.knowledge.config import (
        is_contextual_retrieval_enabled_for_kb,
        load_contextual_retrieval_config,
    )
    from services.knowledge.contextualizer import contextualize_chunks

    cfg = load_contextual_retrieval_config()
    if not is_contextual_retrieval_enabled_for_kb(kb.contextual_retrieval_enabled, cfg):
        return None
    if not chunks:
        return None
    return await contextualize_chunks(
        chunks,
        document_text=document_text,
        filename=filename,
        kb_description=kb.description or "",
        model_service_id=cfg.model_service_id,
        db=db,
        config=cfg,
    )


@router.get("", response_model=PaginatedResponse)
def list_projects(
    user: CurrentUser,
    tab: str = Query("active", pattern="^(starred|active|archived|shared)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    items = ps.list_projects_for_user(db, user.user_id, tab=tab)
    total = len(items)
    start = (page - 1) * page_size
    page_items = items[start : start + page_size]
    return PaginatedResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[ps.serialize_project(db, p, user.user_id) for p in page_items],
    )


@router.post("", response_model=ProjectResponse, status_code=201)
def create_project(
    data: ProjectCreate,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    name = (data.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="项目名称不能为空")
    project = ps.create_project(db, user, name, data.description or "")
    return ps.serialize_project(db, project, user.user_id)


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: str,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    project, _ = ps.require_membership(db, project_id, user.user_id, min_role="viewer")
    return ps.serialize_project(db, project, user.user_id)


@router.patch("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: str,
    data: ProjectUpdate,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    # instructions/name/description: editor+; archive: owner
    if data.status is not None:
        project, _ = ps.require_membership(db, project_id, user.user_id, min_role="owner")
    else:
        project, _ = ps.require_membership(db, project_id, user.user_id, min_role="editor")

    if data.name is not None:
        name = data.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="项目名称不能为空")
        project.name = name
    if data.description is not None:
        project.description = data.description
    if data.instructions is not None:
        project.instructions = data.instructions
    if data.status is not None:
        project.status = ProjectStatus(data.status)
    if data.last_agent_id is not None:
        agent_id = (data.last_agent_id or "").strip() or None
        if agent_id and not db.query(Agent).filter(Agent.agent_id == agent_id).first():
            raise HTTPException(status_code=400, detail="智能体不存在")
        project.last_agent_id = agent_id
    project.updated_at = now_utc()
    db.commit()
    db.refresh(project)
    return ps.serialize_project(db, project, user.user_id)


@router.delete("/{project_id}")
def delete_project(
    project_id: str,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    project, _ = ps.require_membership(db, project_id, user.user_id, min_role="owner")
    ps.delete_project(db, project)
    return {"message": "项目已删除"}


@router.post("/{project_id}/star")
def star_project(
    project_id: str,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    ps.require_membership(db, project_id, user.user_id, min_role="viewer")
    existing = (
        db.query(ProjectStar)
        .filter(
            ProjectStar.project_id == project_id,
            ProjectStar.user_id == user.user_id,
        )
        .first()
    )
    if not existing:
        db.add(ProjectStar(project_id=project_id, user_id=user.user_id))
        db.commit()
    return {"starred": True}


@router.delete("/{project_id}/star")
def unstar_project(
    project_id: str,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    ps.require_membership(db, project_id, user.user_id, min_role="viewer")
    db.query(ProjectStar).filter(
        ProjectStar.project_id == project_id,
        ProjectStar.user_id == user.user_id,
    ).delete(synchronize_session=False)
    db.commit()
    return {"starred": False}


@router.get("/{project_id}/members", response_model=List[ProjectMemberOut])
def list_members(
    project_id: str,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    ps.require_membership(db, project_id, user.user_id, min_role="viewer")
    rows = (
        db.query(ProjectMember)
        .filter(ProjectMember.project_id == project_id)
        .order_by(ProjectMember.created_at.asc())
        .all()
    )
    out = []
    for m in rows:
        u = db.query(User).filter(User.user_id == m.user_id).first()
        out.append(
            ProjectMemberOut(
                user_id=m.user_id,
                username=u.username if u else "",
                display_name=(u.display_name if u else "") or (u.username if u else ""),
                role=m.role.value if hasattr(m.role, "value") else str(m.role),
                created_at=m.created_at,
            )
        )
    return out


@router.post("/{project_id}/members", response_model=ProjectMemberOut, status_code=201)
def add_member(
    project_id: str,
    data: ProjectMemberAdd,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    ps.require_membership(db, project_id, user.user_id, min_role="editor")
    target = db.query(User).filter(User.username == data.username.strip()).first()
    if not target or not target.is_active:
        raise HTTPException(status_code=404, detail="用户不存在")
    role = ProjectMemberRole(data.role)
    existing = ps.get_membership(db, project_id, target.user_id)
    if existing:
        existing.role = role
        db.commit()
        member = existing
    else:
        member = ProjectMember(
            project_id=project_id,
            user_id=target.user_id,
            role=role,
        )
        db.add(member)
        db.commit()
        db.refresh(member)
    return ProjectMemberOut(
        user_id=target.user_id,
        username=target.username,
        display_name=target.display_name or target.username,
        role=member.role.value if hasattr(member.role, "value") else str(member.role),
        created_at=member.created_at,
    )


@router.patch("/{project_id}/members/{member_user_id}", response_model=ProjectMemberOut)
def update_member(
    project_id: str,
    member_user_id: str,
    data: ProjectMemberUpdate,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    ps.require_membership(db, project_id, user.user_id, min_role="editor")
    member = ps.get_membership(db, project_id, member_user_id)
    if not member:
        raise HTTPException(status_code=404, detail="成员不存在")
    new_role = ProjectMemberRole(data.role)
    if member.role == ProjectMemberRole.OWNER and new_role != ProjectMemberRole.OWNER:
        owner_count = (
            db.query(ProjectMember)
            .filter(
                ProjectMember.project_id == project_id,
                ProjectMember.role == ProjectMemberRole.OWNER,
            )
            .count()
        )
        if owner_count <= 1:
            raise HTTPException(status_code=400, detail="不能移除最后一个 owner")
    member.role = new_role
    db.commit()
    u = db.query(User).filter(User.user_id == member.user_id).first()
    return ProjectMemberOut(
        user_id=member.user_id,
        username=u.username if u else "",
        display_name=(u.display_name if u else "") or "",
        role=member.role.value if hasattr(member.role, "value") else str(member.role),
        created_at=member.created_at,
    )


@router.delete("/{project_id}/members/{member_user_id}")
def remove_member(
    project_id: str,
    member_user_id: str,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    ps.require_membership(db, project_id, user.user_id, min_role="editor")
    member = ps.get_membership(db, project_id, member_user_id)
    if not member:
        raise HTTPException(status_code=404, detail="成员不存在")
    if member.role == ProjectMemberRole.OWNER:
        owner_count = (
            db.query(ProjectMember)
            .filter(
                ProjectMember.project_id == project_id,
                ProjectMember.role == ProjectMemberRole.OWNER,
            )
            .count()
        )
        if owner_count <= 1:
            raise HTTPException(status_code=400, detail="不能移除最后一个 owner")
    db.delete(member)
    db.commit()
    return {"message": "已移除成员"}


@router.get("/{project_id}/files")
def list_files(
    project_id: str,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    project, _ = ps.require_membership(db, project_id, user.user_id, min_role="viewer")
    if not project.kb_id:
        return {"files": [], "total_files": 0}
    files = ks.list_files(project.kb_id)
    return {"files": files, "total_files": len(files)}


@router.post("/{project_id}/files")
async def upload_file(
    project_id: str,
    user: CurrentUser,
    file: UploadFile = File(...),
    filename: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    project, _ = ps.require_membership(db, project_id, user.user_id, min_role="editor")
    if not project.kb_id:
        raise HTTPException(status_code=400, detail="项目知识库未初始化")
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.kb_id == project.kb_id).first()
    if not kb:
        raise HTTPException(status_code=400, detail="项目知识库不存在")

    file_bytes = await file.read()
    name = filename or file.filename or "unknown"
    try:
        parsed = ks.parse_file_to_chunks(file_bytes, name)
        prefixes = await _maybe_contextualize(
            kb, db, parsed["chunks"], parsed["text"], name
        )
        result = ks.add_file(project.kb_id, file_bytes, name, prefixes=prefixes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    kb.doc_count = ks.get_doc_count(project.kb_id)
    kb.status = KnowledgeBaseStatus.ACTIVE
    project.updated_at = now_utc()
    db.commit()
    return {
        "message": f"已导入文件 {result['filename']}，共 {result['chunk_count']} 个分块",
        "doc_id": result.get("doc_id"),
        "filename": result["filename"],
        "text_length": result["text_length"],
        "chunk_count": result["chunk_count"],
    }


@router.delete("/{project_id}/files/{doc_id}")
def delete_file(
    project_id: str,
    doc_id: str,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    project, _ = ps.require_membership(db, project_id, user.user_id, min_role="editor")
    if not project.kb_id:
        raise HTTPException(status_code=400, detail="项目知识库未初始化")
    try:
        result = ks.delete_document(project.kb_id, doc_id)
    except ValueError as e:
        raise HTTPException(status_code=404 if "不存在" in str(e) else 400, detail=str(e))
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.kb_id == project.kb_id).first()
    if kb:
        kb.doc_count = ks.get_doc_count(project.kb_id)
    project.updated_at = now_utc()
    db.commit()
    return {"message": "文档已删除", **result}


@router.get("/{project_id}/sessions", response_model=PaginatedResponse)
def list_project_sessions(
    project_id: str,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    ps.require_membership(db, project_id, user.user_id, min_role="viewer")
    query = db.query(SessionModel).filter(SessionModel.project_id == project_id)
    total = query.count()
    sessions = (
        query.order_by(SessionModel.last_active_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = []
    for s in sessions:
        _ensure_files_for_session(s, db)
        ensure_session_title(s)
        agent = db.query(Agent).filter(Agent.agent_id == s.agent_id).first()
        caller = db.query(User).filter(User.user_id == s.caller_id).first()
        item = SessionResponse.model_validate(s)
        item.agent_name = agent.name if agent else ""
        item.caller_display_name = (
            (caller.display_name or caller.username) if caller else (s.caller_id or "")
        )
        item.can_write = ps.can_write_session(db, s, user.user_id)
        items.append(item)
    db.commit()
    return PaginatedResponse(
        total=total, page=page, page_size=page_size, items=items
    )
