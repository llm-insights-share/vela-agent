import time
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import Optional, List
from database import get_db
from models import KnowledgeBase, KnowledgeBaseStatus, gen_uuid, now_utc
from schemas import (
    KnowledgeBaseCreate, KnowledgeBaseUpdate, KnowledgeBaseResponse,
    DocumentAddRequest, KnowledgeSearchRequest, KnowledgeSearchResponse,
    KnowledgeSearchResult, PaginatedResponse
)
from services.knowledge_service import knowledge_service as ks

router = APIRouter(prefix="/api/v1/knowledge-bases", tags=["knowledge-bases"])


@router.get("", response_model=PaginatedResponse)
def list_knowledge_bases(
    scope: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(KnowledgeBase)
    if scope:
        query = query.filter(KnowledgeBase.scope == scope)
    if status:
        query = query.filter(KnowledgeBase.status == status)
    total = query.count()
    kbs = query.order_by(KnowledgeBase.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()
    return PaginatedResponse(
        total=total, page=page, page_size=page_size,
        items=[KnowledgeBaseResponse.model_validate(k) for k in kbs]
    )


@router.post("", response_model=KnowledgeBaseResponse, status_code=201)
def create_knowledge_base(data: KnowledgeBaseCreate, db: Session = Depends(get_db)):
    existing = db.query(KnowledgeBase).filter(KnowledgeBase.name == data.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="知识库名称已存在")
    kb = KnowledgeBase(
        kb_id=gen_uuid(),
        name=data.name,
        description=data.description,
        kb_type=data.kb_type,
        scope=data.scope,
    )
    db.add(kb)
    db.commit()
    db.refresh(kb)
    return KnowledgeBaseResponse.model_validate(kb)


@router.get("/{kb_id}", response_model=KnowledgeBaseResponse)
def get_knowledge_base(kb_id: str, db: Session = Depends(get_db)):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.kb_id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return KnowledgeBaseResponse.model_validate(kb)


@router.put("/{kb_id}", response_model=KnowledgeBaseResponse)
def update_knowledge_base(kb_id: str, data: KnowledgeBaseUpdate, db: Session = Depends(get_db)):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.kb_id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    update_fields = data.model_dump(exclude_unset=True)
    for key, value in update_fields.items():
        if hasattr(kb, key):
            setattr(kb, key, value)
    db.commit()
    db.refresh(kb)
    return KnowledgeBaseResponse.model_validate(kb)


@router.delete("/{kb_id}")
def delete_knowledge_base(kb_id: str, db: Session = Depends(get_db)):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.kb_id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    kb.status = KnowledgeBaseStatus.ARCHIVED
    ks.delete_kb(kb_id)
    db.commit()
    return {"message": "知识库已归档"}


@router.post("/{kb_id}/documents")
def add_documents(kb_id: str, data: DocumentAddRequest, db: Session = Depends(get_db)):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.kb_id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")

    doc_count = ks.add_documents(kb_id, [{"content": data.content, "metadata": data.metadata}])
    kb.doc_count = ks.get_doc_count(kb_id)
    kb.status = KnowledgeBaseStatus.ACTIVE
    db.commit()

    return {"message": f"已添加文档，共 {doc_count} 个分块", "chunk_count": doc_count}


@router.post("/{kb_id}/upload")
async def upload_file(
    kb_id: str,
    file: UploadFile = File(...),
    filename: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.kb_id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")

    file_bytes = await file.read()
    name = filename or file.filename or "unknown"

    try:
        result = ks.add_file(kb_id, file_bytes, name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    kb.doc_count = ks.get_doc_count(kb_id)
    kb.status = KnowledgeBaseStatus.ACTIVE
    db.commit()

    return {
        "message": f"已导入文件 {result['filename']}，共 {result['chunk_count']} 个分块",
        "filename": result["filename"],
        "text_length": result["text_length"],
        "chunk_count": result["chunk_count"],
    }


@router.get("/{kb_id}/files")
def list_files(kb_id: str, db: Session = Depends(get_db)):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.kb_id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    files = ks.list_files(kb_id)
    return {"files": files, "total_files": len(files)}


@router.post("/{kb_id}/search", response_model=KnowledgeSearchResponse)
def search_knowledge_base(kb_id: str, data: KnowledgeSearchRequest, db: Session = Depends(get_db)):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.kb_id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")

    start = time.time()
    results = ks.search(kb_id, data.query, data.top_k)
    elapsed = (time.time() - start) * 1000

    return KnowledgeSearchResponse(
        results=[KnowledgeSearchResult(**r) for r in results],
        query_time_ms=round(elapsed, 2),
    )