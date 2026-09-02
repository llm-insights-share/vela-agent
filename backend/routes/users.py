from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from deps import require_roles
from models import User, gen_uuid
from schemas import ActiveIn, AdminCreateUserIn, RolesIn, UserOut
from security import hash_password
from routes import auth as auth_helpers
from services.connector_service import purge_user_owned_resources

router = APIRouter(prefix="/api/v1/users", tags=["users"])

AdminUser = Annotated[User, Depends(require_roles("admin"))]


def _role_set(roles: str) -> set[str]:
    return {r.strip() for r in (roles or "").split(",") if r.strip()}


def _count_active_admins(db: Session, *, exclude_id: str | None = None) -> int:
    n = 0
    for u in db.query(User).filter(User.is_active == True).all():  # noqa: E712
        if exclude_id is not None and u.user_id == exclude_id:
            continue
        if "admin" in _role_set(u.roles):
            n += 1
    return n


@router.get("", response_model=List[UserOut])
def list_users(_admin: AdminUser, db: Session = Depends(get_db)):
    rows = db.query(User).order_by(User.created_at.asc()).all()
    return [auth_helpers._user_out(u) for u in rows]


@router.post("", response_model=UserOut)
def create_user(body: AdminCreateUserIn, _admin: AdminUser, db: Session = Depends(get_db)):
    email, username = auth_helpers._validate_credentials(body.email, body.username, body.password)
    auth_helpers._ensure_unique(db, email=email, username=username)
    roles = ",".join(sorted(_role_set(body.roles))) or "member"
    user = User(
        user_id=gen_uuid(),
        username=username,
        email=email,
        display_name=(body.display_name or "").strip() or username,
        hashed_password=hash_password(body.password),
        roles=roles,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return auth_helpers._user_out(user)


@router.patch("/{user_id}/active", response_model=UserOut)
def set_user_active(
    user_id: str,
    body: ActiveIn,
    admin: AdminUser,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.user_id == admin.user_id:
        raise HTTPException(status_code=400, detail="Cannot block yourself")
    if not body.is_active and "admin" in _role_set(user.roles):
        if _count_active_admins(db, exclude_id=user.user_id) < 1:
            raise HTTPException(status_code=400, detail="Cannot block the last admin")
    user.is_active = body.is_active
    db.add(user)
    db.commit()
    db.refresh(user)
    return auth_helpers._user_out(user)


@router.patch("/{user_id}/roles", response_model=UserOut)
def set_user_roles(
    user_id: str,
    body: RolesIn,
    admin: AdminUser,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    roles = ",".join(sorted(_role_set(body.roles))) or "member"
    next_roles = _role_set(roles)
    if "admin" not in next_roles and "admin" in _role_set(user.roles):
        if _count_active_admins(db, exclude_id=user.user_id) < 1:
            raise HTTPException(status_code=400, detail="Cannot remove the last admin")
    user.roles = roles
    db.add(user)
    db.commit()
    db.refresh(user)
    return auth_helpers._user_out(user)


@router.delete("/{user_id}")
def delete_user(user_id: str, admin: AdminUser, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.user_id == admin.user_id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    if "admin" in _role_set(user.roles) and user.is_active:
        if _count_active_admins(db, exclude_id=user.user_id) < 1:
            raise HTTPException(status_code=400, detail="Cannot delete the last admin")

    try:
        purge_user_owned_resources(db, user_id)
        db.delete(user)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="无法删除用户：仍存在关联数据，请先清理连接器或 MCP 资源",
        ) from exc
    return {"ok": True}
