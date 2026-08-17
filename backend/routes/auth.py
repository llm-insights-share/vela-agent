import re
import time
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from auth_config import AVATAR_DIR
from database import get_db
from deps import CurrentUser
from models import User, gen_uuid
from schemas import (
    PasswordUpdateIn,
    ProfileUpdateIn,
    RegisterIn,
    TokenOut,
    UserOut,
)
from security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+$")
USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{2,64}$")


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _normalize_username(username: str) -> str:
    return (username or "").strip()


def _validate_credentials(email: str, username: str, password: str) -> tuple[str, str]:
    email_n = _normalize_email(email)
    username_n = _normalize_username(username)
    if not EMAIL_RE.match(email_n):
        raise HTTPException(status_code=400, detail="Invalid email format")
    if not USERNAME_RE.match(username_n):
        raise HTTPException(
            status_code=400,
            detail="Username must be 2–64 chars: letters, digits, . _ -",
        )
    if len(password or "") < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    return email_n, username_n


def _ensure_unique(
    db: Session,
    *,
    email: str,
    username: str,
    exclude_id: str | None = None,
) -> None:
    existing_u = db.query(User).filter(User.username == username).first()
    existing_e = db.query(User).filter(User.email == email).first()
    if existing_u and existing_u.user_id != exclude_id:
        raise HTTPException(status_code=400, detail="Username already taken")
    if existing_e and existing_e.user_id != exclude_id:
        raise HTTPException(status_code=400, detail="Email already registered")


def _user_out(u: User) -> UserOut:
    return UserOut(
        user_id=u.user_id,
        username=u.username,
        email=u.email or "",
        display_name=u.display_name,
        avatar_url=u.avatar_url or "",
        roles=u.roles,
        is_active=u.is_active,
        created_at=u.created_at,
    )


@router.post("/login", response_model=TokenOut)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="User is blocked")
    token = create_access_token(user.username, {"roles": user.roles})
    return TokenOut(access_token=token)


@router.post("/register", response_model=TokenOut)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    email, username = _validate_credentials(body.email, body.username, body.password)
    _ensure_unique(db, email=email, username=username)
    user = User(
        user_id=gen_uuid(),
        username=username,
        email=email,
        display_name=(body.display_name or "").strip() or username,
        hashed_password=hash_password(body.password),
        roles="member",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(user.username, {"roles": user.roles})
    return TokenOut(access_token=token)


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser):
    return _user_out(user)


@router.patch("/me/profile", response_model=UserOut)
def update_me_profile(body: ProfileUpdateIn, user: CurrentUser, db: Session = Depends(get_db)):
    email_n = _normalize_email(body.email)
    if not EMAIL_RE.match(email_n):
        raise HTTPException(status_code=400, detail="Invalid email format")
    _ensure_unique(db, email=email_n, username=user.username, exclude_id=user.user_id)
    user.email = email_n
    user.display_name = (body.display_name or "").strip() or user.username
    db.add(user)
    db.commit()
    db.refresh(user)
    return _user_out(user)


@router.patch("/me/password")
def update_me_password(body: PasswordUpdateIn, user: CurrentUser, db: Session = Depends(get_db)):
    if not verify_password(body.old_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="旧密码错误")
    if len(body.new_password or "") < 6:
        raise HTTPException(status_code=400, detail="新密码至少 6 位")
    user.hashed_password = hash_password(body.new_password)
    db.add(user)
    db.commit()
    return {"ok": True}


@router.post("/me/avatar", response_model=UserOut)
async def upload_me_avatar(
    user: CurrentUser,
    db: Session = Depends(get_db),
    file: UploadFile = File(...),
):
    ctype = (file.content_type or "").lower()
    if ctype not in {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif"}:
        raise HTTPException(status_code=400, detail="仅支持 png/jpg/webp/gif 图片")
    data = await file.read()
    if len(data) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="头像大小不能超过 2MB")
    ext_map = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }
    ext = ext_map.get(ctype, ".png")
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    for p in AVATAR_DIR.glob(f"{user.user_id}.*"):
        try:
            p.unlink()
        except Exception:
            pass
    target = AVATAR_DIR / f"{user.user_id}{ext}"
    Path(target).write_bytes(data)
    user.avatar_url = f"/avatars/{target.name}?v={int(time.time() * 1000)}"
    db.add(user)
    db.commit()
    db.refresh(user)
    return _user_out(user)
