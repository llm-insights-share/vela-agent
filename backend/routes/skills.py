from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session
from typing import Optional
import zipfile
import io
import json
import yaml
from database import get_db
from models import SkillPack, SkillPackStatus, gen_uuid, now_utc
from schemas import SkillPackCreate, SkillPackUpdate, SkillPackResponse, PaginatedResponse

router = APIRouter(prefix="/api/v1/skills", tags=["skills"])


@router.get("", response_model=PaginatedResponse)
def list_skills(
    scope: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(SkillPack)
    if scope:
        query = query.filter(SkillPack.scope == scope)
    if status:
        query = query.filter(SkillPack.status == status)
    total = query.count()
    skills = query.order_by(SkillPack.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()
    return PaginatedResponse(
        total=total, page=page, page_size=page_size,
        items=[SkillPackResponse.model_validate(s) for s in skills]
    )


@router.post("", response_model=SkillPackResponse, status_code=201)
def create_skill(data: SkillPackCreate, db: Session = Depends(get_db)):
    existing = db.query(SkillPack).filter(SkillPack.name == data.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Skill 包名称已存在")
    skill = SkillPack(
        skill_pack_id=gen_uuid(),
        name=data.name,
        version=data.version,
        scope=data.scope,
        tools=data.tools,
        description=data.description,
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return SkillPackResponse.model_validate(skill)


@router.get("/{skill_pack_id}", response_model=SkillPackResponse)
def get_skill(skill_pack_id: str, db: Session = Depends(get_db)):
    skill = db.query(SkillPack).filter(SkillPack.skill_pack_id == skill_pack_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill 包不存在")
    return SkillPackResponse.model_validate(skill)


@router.put("/{skill_pack_id}", response_model=SkillPackResponse)
def update_skill(skill_pack_id: str, data: SkillPackUpdate, db: Session = Depends(get_db)):
    skill = db.query(SkillPack).filter(SkillPack.skill_pack_id == skill_pack_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill 包不存在")
    update_fields = data.model_dump(exclude_unset=True)
    for key, value in update_fields.items():
        if hasattr(skill, key):
            setattr(skill, key, value)
    db.commit()
    db.refresh(skill)
    return SkillPackResponse.model_validate(skill)


@router.delete("/{skill_pack_id}")
def delete_skill(skill_pack_id: str, db: Session = Depends(get_db)):
    skill = db.query(SkillPack).filter(SkillPack.skill_pack_id == skill_pack_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill 包不存在")
    skill.status = SkillPackStatus.ARCHIVED
    db.commit()
    return {"message": "Skill 包已归档"}


@router.post("/import", response_model=SkillPackResponse, status_code=201)
async def import_skill(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename or not file.filename.lower().endswith('.zip'):
        raise HTTPException(status_code=400, detail="仅支持 .zip 格式的 Skill 包")

    content = await file.read()

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            manifest_data = None
            instructions = ""

            skill_md_name = None
            for name in zf.namelist():
                basename = name.split('/')[-1].lower()
                if basename == 'skill.md':
                    skill_md_name = name
                    break

            if skill_md_name:
                raw = zf.read(skill_md_name).decode('utf-8', errors='replace')
                manifest_data, instructions = _parse_skill_md(raw)

            if not manifest_data:
                for name in zf.namelist():
                    basename = name.split('/')[-1].lower()
                    if basename in ('skill.yaml', 'skill.yml'):
                        manifest_data = yaml.safe_load(zf.read(name))
                    elif basename == 'skill.json':
                        manifest_data = json.loads(zf.read(name))

            if not manifest_data:
                raise HTTPException(status_code=400, detail="Skill 包中未找到 SKILL.md、skill.yaml 或 skill.json 文件")

            if not instructions:
                for name in zf.namelist():
                    if not name.endswith('/') and name.lower() != skill_md_name.lower() if skill_md_name else True:
                        bn = name.split('/')[-1].lower()
                        if bn.endswith('.md') and bn != 'skill.md':
                            instructions += zf.read(name).decode('utf-8', errors='replace') + '\n'
                if not instructions:
                    for name in zf.namelist():
                        if not name.endswith('/') and name.lower() != (skill_md_name.lower() if skill_md_name else ''):
                            bn = name.split('/')[-1].lower()
                            if not bn.startswith('skill.') and not bn.startswith('.'):
                                try:
                                    content_str = zf.read(name).decode('utf-8', errors='replace')
                                    instructions += f"\n--- {name} ---\n{content_str}\n"
                                except Exception:
                                    pass

            if not instructions:
                instructions = manifest_data.get('description', '')

            name = manifest_data.get('name', '')
            if not name:
                raise HTTPException(status_code=400, detail="Skill 清单中缺少 name 字段")

            existing = db.query(SkillPack).filter(SkillPack.name == name).first()
            if existing:
                existing.version = manifest_data.get('version', existing.version)
                existing.description = manifest_data.get('description', existing.description)
                existing.tools = manifest_data.get('tools', [])
                existing.manifest = manifest_data
                existing.skill_content = instructions
                existing.status = SkillPackStatus.ACTIVE
                db.commit()
                db.refresh(existing)
                return SkillPackResponse.model_validate(existing)

            skill = SkillPack(
                skill_pack_id=gen_uuid(),
                name=name,
                version=manifest_data.get('version', '1.0.0'),
                scope=manifest_data.get('scope', 'platform'),
                tools=manifest_data.get('tools', []),
                description=manifest_data.get('description', ''),
                manifest=manifest_data,
                skill_content=instructions,
            )
            db.add(skill)
            db.commit()
            db.refresh(skill)
            return SkillPackResponse.model_validate(skill)

    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="无效的 ZIP 文件")
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"YAML 解析错误: {str(e)}")
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"JSON 解析错误: {str(e)}")


def _parse_skill_md(raw: str):
    raw = raw.strip()
    manifest = {}
    instructions = raw

    if raw.startswith('---'):
        parts = raw.split('---', 2)
        if len(parts) >= 3:
            try:
                manifest = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                manifest = {}
            instructions = parts[2].strip()

    if not manifest.get('name'):
        first_line = raw.split('\n')[0]
        if first_line.startswith('# '):
            manifest['name'] = first_line[2:].strip()

    if not manifest.get('description') and not manifest.get('name'):
        manifest['name'] = 'unnamed-skill'

    return manifest, instructions