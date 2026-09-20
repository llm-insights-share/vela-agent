"""Project workspace helpers (Claude-style Projects)."""
from __future__ import annotations

from typing import List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy.orm import Session

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
    gen_uuid,
    now_utc,
)
from services.knowledge_service import knowledge_service as ks

ROLE_RANK = {
    ProjectMemberRole.VIEWER: 1,
    ProjectMemberRole.EDITOR: 2,
    ProjectMemberRole.OWNER: 3,
    "viewer": 1,
    "editor": 2,
    "owner": 3,
}


def _role_value(role) -> str:
    if isinstance(role, ProjectMemberRole):
        return role.value
    return str(role or "viewer")


def get_membership(db: Session, project_id: str, user_id: str) -> Optional[ProjectMember]:
    return (
        db.query(ProjectMember)
        .filter(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
        .first()
    )


def require_membership(
    db: Session,
    project_id: str,
    user_id: str,
    *,
    min_role: str = "viewer",
) -> Tuple[Project, ProjectMember]:
    project = db.query(Project).filter(Project.project_id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    member = get_membership(db, project_id, user_id)
    if not member:
        raise HTTPException(status_code=403, detail="无权访问该项目")
    need = ROLE_RANK.get(min_role, 1)
    have = ROLE_RANK.get(member.role, 0)
    if have < need:
        raise HTTPException(status_code=403, detail="权限不足")
    return project, member


def can_write_session(db: Session, session: SessionModel, user_id: str) -> bool:
    """Whether user may send messages / mutate a session."""
    if not session.project_id:
        return (session.caller_id or "") == user_id
    member = get_membership(db, session.project_id, user_id)
    if not member:
        return False
    # Own sessions: any member role can write
    if (session.caller_id or "") == user_id:
        return True
    # Others' sessions: editor/owner can write (optional); plan says viewer read-only on others
    return ROLE_RANK.get(member.role, 0) >= ROLE_RANK["editor"]


def can_read_session(db: Session, session: SessionModel, user_id: str) -> bool:
    if not session.project_id:
        return (session.caller_id or "") == user_id
    return get_membership(db, session.project_id, user_id) is not None


def _unique_kb_name(db: Session, project_id: str) -> str:
    base = f"proj_{project_id[:8]}"
    name = base
    n = 0
    while db.query(KnowledgeBase).filter(KnowledgeBase.name == name).first():
        n += 1
        name = f"{base}_{n}"
    return name


def create_project(db: Session, user: User, name: str, description: str = "") -> Project:
    project_id = gen_uuid()
    kb = KnowledgeBase(
        kb_id=gen_uuid(),
        name=_unique_kb_name(db, project_id),
        description=f"Project knowledge: {name}",
        kb_type="document",
        scope="project",
        status=KnowledgeBaseStatus.ACTIVE,
    )
    db.add(kb)
    db.flush()

    project = Project(
        project_id=project_id,
        name=(name or "").strip(),
        description=(description or "").strip(),
        instructions="",
        owner_id=user.user_id,
        kb_id=kb.kb_id,
        status=ProjectStatus.ACTIVE,
    )
    db.add(project)
    db.flush()

    db.add(
        ProjectMember(
            project_id=project.project_id,
            user_id=user.user_id,
            role=ProjectMemberRole.OWNER,
        )
    )
    db.commit()
    db.refresh(project)
    return project


def serialize_project(
    db: Session,
    project: Project,
    user_id: str,
) -> dict:
    member = get_membership(db, project.project_id, user_id)
    starred = (
        db.query(ProjectStar)
        .filter(
            ProjectStar.project_id == project.project_id,
            ProjectStar.user_id == user_id,
        )
        .first()
        is not None
    )
    file_count = 0
    if project.kb_id:
        try:
            file_count = len(ks.list_files(project.kb_id))
        except Exception:
            file_count = 0
    session_count = (
        db.query(SessionModel)
        .filter(SessionModel.project_id == project.project_id)
        .count()
    )
    member_count = (
        db.query(ProjectMember)
        .filter(ProjectMember.project_id == project.project_id)
        .count()
    )
    return {
        "project_id": project.project_id,
        "name": project.name,
        "description": project.description or "",
        "instructions": project.instructions or "",
        "owner_id": project.owner_id,
        "kb_id": project.kb_id,
        "status": project.status.value if hasattr(project.status, "value") else str(project.status),
        "last_agent_id": project.last_agent_id,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
        "my_role": _role_value(member.role) if member else None,
        "starred": starred,
        "file_count": file_count,
        "session_count": session_count,
        "member_count": member_count,
    }


def list_projects_for_user(
    db: Session,
    user_id: str,
    *,
    tab: str = "active",
) -> List[Project]:
    memberships = (
        db.query(ProjectMember)
        .filter(ProjectMember.user_id == user_id)
        .all()
    )
    project_ids = [m.project_id for m in memberships]
    if not project_ids:
        return []

    q = db.query(Project).filter(Project.project_id.in_(project_ids))

    if tab == "archived":
        q = q.filter(Project.status == ProjectStatus.ARCHIVED)
    elif tab == "starred":
        starred_ids = [
            s.project_id
            for s in db.query(ProjectStar).filter(ProjectStar.user_id == user_id).all()
        ]
        if not starred_ids:
            return []
        q = q.filter(
            Project.project_id.in_(starred_ids),
            Project.status == ProjectStatus.ACTIVE,
        )
    elif tab == "shared":
        # Member but not owner
        owned = {m.project_id for m in memberships if _role_value(m.role) == "owner"}
        shared_ids = [pid for pid in project_ids if pid not in owned]
        if not shared_ids:
            return []
        q = q.filter(
            Project.project_id.in_(shared_ids),
            Project.status == ProjectStatus.ACTIVE,
        )
    else:  # active — all non-archived memberships
        q = q.filter(Project.status == ProjectStatus.ACTIVE)

    return q.order_by(Project.updated_at.desc()).all()


def delete_project(db: Session, project: Project) -> None:
    pid = project.project_id
    kb_id = project.kb_id

    # Detach sessions (keep chat history)
    db.query(SessionModel).filter(SessionModel.project_id == pid).update(
        {"project_id": None},
        synchronize_session=False,
    )
    db.query(ProjectStar).filter(ProjectStar.project_id == pid).delete(
        synchronize_session=False
    )
    db.query(ProjectMember).filter(ProjectMember.project_id == pid).delete(
        synchronize_session=False
    )
    db.delete(project)

    if kb_id:
        kb = db.query(KnowledgeBase).filter(KnowledgeBase.kb_id == kb_id).first()
        if kb:
            kb.status = KnowledgeBaseStatus.ARCHIVED
    db.commit()


def build_project_prompt_context(db: Session, project: Project) -> str:
    """Inject project instructions + knowledge file list / small snippets."""
    parts: List[str] = []
    instructions = (project.instructions or "").strip()
    if instructions:
        parts.append(f"\n\n## 项目指令\n{instructions}")

    if not project.kb_id:
        return "".join(parts)

    try:
        files = ks.list_files(project.kb_id)
    except Exception:
        files = []

    active_files = [f for f in files if (f.get("status") or "ACTIVE") == "ACTIVE"]
    if not active_files:
        return "".join(parts)

    lines = ["\n\n## 项目知识"]
    lines.append(
        "以下文件属于当前项目，可在回答中引用；需要细节时请使用 kb_search 并指定项目知识库。"
    )
    total_chars = 0
    MAX_INLINE = 12000
    for f in active_files:
        fname = f.get("filename") or f.get("doc_id") or "file"
        doc_id = f.get("doc_id") or ""
        chunk_count = f.get("chunk_count") or 0
        lines.append(f"- {fname} (doc_id={doc_id}, chunks={chunk_count})")

    # Inline small docs when total is small
    try:
        for f in active_files:
            doc_id = f.get("doc_id")
            if not doc_id:
                continue
            chunks_data = ks.list_document_chunks(project.kb_id, doc_id)
            chunk_texts = [
                (c.get("content") or "")
                for c in (chunks_data.get("chunks") or [])
                if (c.get("status") or "ACTIVE") == "ACTIVE"
            ]
            body = "\n".join(chunk_texts).strip()
            if not body:
                continue
            if total_chars + len(body) > MAX_INLINE:
                lines.append(
                    f"\n（其余文件内容较长，请通过 kb_search 检索，kb_id={project.kb_id}）"
                )
                break
            fname = f.get("filename") or doc_id
            lines.append(f"\n### 文件: {fname}\n{body[:4000]}")
            total_chars += min(len(body), 4000)
    except Exception:
        pass

    parts.append("\n".join(lines))
    return "".join(parts)


def resolve_allowed_kb_ids(
    db: Session,
    *,
    agent_id: str,
    project_id: Optional[str] = None,
) -> Tuple[Optional[List[str]], Optional[str]]:
    """
    Returns (allowed_kb_ids, project_kb_id).
    - Non-project: allowed_kb_ids=None means "all platform ACTIVE (exclude scope=project)"
    - Project: allowed_kb_ids = agent bindings + project kb
    """
    project_kb_id = None
    if project_id:
        project = db.query(Project).filter(Project.project_id == project_id).first()
        if project and project.kb_id:
            project_kb_id = project.kb_id

    if not project_id:
        return None, None

    from models import AgentKnowledgeBinding

    bound = [
        b.kb_id
        for b in db.query(AgentKnowledgeBinding)
        .filter(AgentKnowledgeBinding.agent_id == agent_id)
        .all()
    ]
    allowed = list(dict.fromkeys([*bound, *( [project_kb_id] if project_kb_id else []) ]))
    return allowed, project_kb_id


def touch_project(db: Session, project: Project, *, last_agent_id: Optional[str] = None) -> None:
    project.updated_at = now_utc()
    if last_agent_id:
        # Validate agent exists
        if db.query(Agent).filter(Agent.agent_id == last_agent_id).first():
            project.last_agent_id = last_agent_id
