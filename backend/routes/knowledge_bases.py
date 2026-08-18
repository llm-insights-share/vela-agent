import time
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session
from typing import Optional, List
from database import get_db
from models import KnowledgeBase, KnowledgeBaseStatus, gen_uuid, now_utc
from schemas import (
    KnowledgeBaseCreate, KnowledgeBaseUpdate, KnowledgeBaseResponse,
    DocumentAddRequest, KnowledgeFileStatusUpdate,
    KnowledgeSearchRequest, KnowledgeSearchResponse,
    KnowledgeSearchResult, KnowledgeSearchSuggestRequest,
    KnowledgeChunkListResponse, KnowledgeImportConfirmRequest,
    KnowledgeDocumentTagsUpdate, PaginatedResponse
)
from services.knowledge_service import knowledge_service as ks

router = APIRouter(prefix="/api/v1/knowledge-bases", tags=["knowledge-bases"])


async def _maybe_contextualize_prefixes(kb, db, chunks, document_text, filename):
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
    items = []
    for k in kbs:
        item = KnowledgeBaseResponse.model_validate(k)
        # Always report live file count (legacy rows may store chunk count)
        item.doc_count = ks.get_doc_count(k.kb_id)
        items.append(item)
    return PaginatedResponse(
        total=total, page=page, page_size=page_size,
        items=items,
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
        contextual_retrieval_enabled=data.contextual_retrieval_enabled,
        tag_defs=[d.model_dump() for d in data.tag_defs],
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
    item = KnowledgeBaseResponse.model_validate(kb)
    item.doc_count = ks.get_doc_count(kb_id)
    return item


@router.put("/{kb_id}", response_model=KnowledgeBaseResponse)
def update_knowledge_base(kb_id: str, data: KnowledgeBaseUpdate, db: Session = Depends(get_db)):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.kb_id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    update_fields = data.model_dump(exclude_unset=True)
    if "tag_defs" in update_fields and update_fields["tag_defs"] is not None:
        dumped = []
        for item in update_fields["tag_defs"]:
            dumped.append(item.model_dump() if hasattr(item, "model_dump") else item)
        update_fields["tag_defs"] = dumped
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
async def add_documents(kb_id: str, data: DocumentAddRequest, db: Session = Depends(get_db)):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.kb_id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")

    from services.document_parser import chunk_by_paragraph

    chunks = chunk_by_paragraph(data.content)
    if not chunks and data.content.strip():
        chunks = [data.content.strip()]
    filename = (data.metadata or {}).get("filename") or "粘贴文本"
    prefixes = await _maybe_contextualize_prefixes(
        kb, db, chunks, data.content, filename
    )
    doc_prefixes = [prefixes] if prefixes is not None else None

    doc_count = ks.add_documents(
        kb_id,
        [{"content": data.content, "metadata": data.metadata}],
        doc_prefixes=doc_prefixes,
    )
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
        parsed = ks.parse_file_to_chunks(file_bytes, name)
        prefixes = await _maybe_contextualize_prefixes(
            kb, db, parsed["chunks"], parsed["text"], name
        )
        result = ks.add_file(kb_id, file_bytes, name, prefixes=prefixes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    kb.doc_count = ks.get_doc_count(kb_id)
    kb.status = KnowledgeBaseStatus.ACTIVE
    db.commit()

    return {
        "message": f"已导入文件 {result['filename']}，共 {result['chunk_count']} 个分块",
        "doc_id": result.get("doc_id"),
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


@router.patch("/{kb_id}/files/{doc_id}")
def update_file_status(
    kb_id: str,
    doc_id: str,
    data: KnowledgeFileStatusUpdate,
    db: Session = Depends(get_db),
):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.kb_id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    try:
        result = ks.set_document_status(kb_id, doc_id, data.status)
    except ValueError as e:
        raise HTTPException(status_code=404 if "不存在" in str(e) else 400, detail=str(e))
    return {"message": "已更新文档状态", **result}


@router.delete("/{kb_id}/files/{doc_id}")
def delete_file(kb_id: str, doc_id: str, db: Session = Depends(get_db)):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.kb_id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    try:
        result = ks.delete_document(kb_id, doc_id)
    except ValueError as e:
        raise HTTPException(status_code=404 if "不存在" in str(e) else 400, detail=str(e))
    kb.doc_count = ks.get_doc_count(kb_id)
    db.commit()
    return {"message": "文档已删除", **result}


@router.get("/{kb_id}/files/{doc_id}/chunks", response_model=KnowledgeChunkListResponse)
def list_file_chunks(kb_id: str, doc_id: str, db: Session = Depends(get_db)):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.kb_id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    try:
        return ks.list_document_chunks(kb_id, doc_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{kb_id}/files/{doc_id}/content")
def get_file_content(
    kb_id: str,
    doc_id: str,
    as_text: bool = Query(False),
    db: Session = Depends(get_db),
):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.kb_id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    try:
        info = ks.get_document_content(kb_id, doc_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    file_type = (info.get("file_type") or "").lower()
    force_text = as_text or file_type in ("docx", "doc", "xlsx", "xls")

    if info.get("mode") == "file" and not force_text:
        media = {
            "pdf": "application/pdf",
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "webp": "image/webp",
            "gif": "image/gif",
            "txt": "text/plain; charset=utf-8",
            "md": "text/markdown; charset=utf-8",
            "markdown": "text/markdown; charset=utf-8",
        }.get(file_type, "application/octet-stream")
        return FileResponse(
            path=info["path"],
            filename=info.get("filename") or "file",
            media_type=media,
        )

    # text mode: for binary office, re-parse or join chunks — never UTF-8-decode the binary
    content = info.get("content")
    binary_office = {"xls", "xlsx", "doc", "docx"}
    if content is None and info.get("mode") == "file":
        if file_type in binary_office:
            try:
                from services.knowledge_service import PARSERS
                with open(info["path"], "rb") as bf:
                    raw = bf.read()
                parser = PARSERS.get(f".{file_type}")
                if not parser:
                    raise ValueError(f"no parser for .{file_type}")
                content = parser(raw) or ""
            except Exception:
                matched = ks._match_doc_chunks(kb_id, doc_id)
                content = "\n\n".join(c.get("content", "") for c in matched)
        else:
            try:
                with open(info["path"], "r", encoding="utf-8", errors="strict") as f:
                    content = f.read()
            except Exception:
                matched = ks._match_doc_chunks(kb_id, doc_id)
                content = "\n\n".join(c.get("content", "") for c in matched)
    if content is None:
        matched = ks._match_doc_chunks(kb_id, doc_id)
        content = "\n\n".join(c.get("content", "") for c in matched)

    return JSONResponse({
        "doc_id": info["doc_id"],
        "filename": info["filename"],
        "file_type": info.get("file_type") or "txt",
        "mode": "text",
        "content": content or "",
    })


@router.post("/{kb_id}/search", response_model=KnowledgeSearchResponse)
def search_knowledge_base(kb_id: str, data: KnowledgeSearchRequest, db: Session = Depends(get_db)):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.kb_id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")

    from services.knowledge.tag_extractor import normalize_tag_defs, normalize_tag_filters

    filters = [f.model_dump() for f in data.tag_filters]
    start = time.time()
    results = ks.search(
        kb_id,
        data.query,
        data.top_k,
        mode=data.mode,
        tag_filters=filters,
        tag_defs=normalize_tag_defs(kb.tag_defs),
    )
    elapsed = (time.time() - start) * 1000

    return KnowledgeSearchResponse(
        results=[KnowledgeSearchResult(**r) for r in results],
        query_time_ms=round(elapsed, 2),
        applied_filters=normalize_tag_filters(filters),
    )


@router.post("/{kb_id}/search/suggest-filters")
async def suggest_search_filters(
    kb_id: str,
    data: KnowledgeSearchSuggestRequest,
    db: Session = Depends(get_db),
):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.kb_id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    from services.knowledge.config import load_contextual_retrieval_config
    from services.knowledge.tag_extractor import normalize_tag_defs, suggest_tag_filters

    cfg = load_contextual_retrieval_config()
    filters = await suggest_tag_filters(
        data.query,
        normalize_tag_defs(kb.tag_defs),
        db=db,
        model_service_id=cfg.model_service_id,
    )
    return {"filters": filters}


@router.post("/{kb_id}/import/preview")
async def import_preview(kb_id: str, request: Request, db: Session = Depends(get_db)):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.kb_id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")

    from services.knowledge.config import load_contextual_retrieval_config
    from services.knowledge.tag_extractor import extract_tags, normalize_tag_defs

    tag_defs = normalize_tag_defs(kb.tag_defs)
    file_bytes = None
    text = ""
    source = "paste"
    name = "粘贴文本.txt"
    try:
        content_type = (request.headers.get("content-type") or "").lower()
        if "application/json" in content_type:
            data = await request.json() or {}
            text = str(data.get("content") or "").strip()
            name = str(data.get("filename") or name)
            if not text:
                raise ValueError("请上传文件或提供文本内容")
            file_bytes = text.encode("utf-8")
        else:
            form = await request.form()
            upload = form.get("file")
            filename = form.get("filename")
            content = form.get("content")
            if upload is not None and hasattr(upload, "read"):
                file_bytes = await upload.read()
                name = str(filename or getattr(upload, "filename", None) or "unknown")
                parsed = ks.parse_file_to_chunks(file_bytes, name)
                text = parsed["text"]
                source = "upload"
            else:
                text = str(content or "").strip()
                name = str(filename or name)
                if not text:
                    raise ValueError("请上传文件或提供文本内容")
                file_bytes = text.encode("utf-8")
        extracted = []
        if tag_defs:
            cfg = load_contextual_retrieval_config()
            extracted = await extract_tags(
                tag_defs,
                text,
                filename=name,
                db=db,
                model_service_id=cfg.model_service_id,
            )
        return ks.save_import_preview(
            kb_id,
            filename=name,
            file_bytes=file_bytes,
            text=text,
            source=source,
            extracted_tags=extracted,
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{kb_id}/import/confirm")
async def import_confirm(
    kb_id: str,
    data: KnowledgeImportConfirmRequest,
    db: Session = Depends(get_db),
):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.kb_id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    try:
        preview = ks.load_import_preview(kb_id, data.preview_id)
        name = preview.get("filename") or "document"
        file_bytes = preview.get("file_bytes") or b""
        text = preview.get("text") or ""
        source = preview.get("source") or "upload"
        tags = data.tags or {}
        if source == "upload":
            parsed = ks.parse_file_to_chunks(file_bytes, name)
            prefixes = await _maybe_contextualize_prefixes(
                kb, db, parsed["chunks"], parsed["text"], name
            )
            result = ks.add_file(kb_id, file_bytes, name, prefixes=prefixes, tags=tags)
        else:
            from services.document_parser import chunk_by_paragraph

            chunks = chunk_by_paragraph(text)
            if not chunks and text.strip():
                chunks = [text.strip()]
            prefixes = await _maybe_contextualize_prefixes(kb, db, chunks, text, name)
            doc_prefixes = [prefixes] if prefixes is not None else None
            chunk_count = ks.add_documents(
                kb_id,
                [{"content": text, "metadata": {"filename": name, "tags": tags}}],
                doc_prefixes=doc_prefixes,
                tags=tags,
            )
            files = [f for f in ks.list_files(kb_id) if f.get("filename") == name]
            result = {
                "doc_id": files[-1]["doc_id"] if files else "",
                "filename": name,
                "text_length": len(text),
                "chunk_count": chunk_count,
            }
        ks.delete_import_preview(kb_id, data.preview_id)
        kb.doc_count = ks.get_doc_count(kb_id)
        kb.status = KnowledgeBaseStatus.ACTIVE
        db.commit()
        return {
            "message": f"已导入 {result.get('filename')}，共 {result.get('chunk_count')} 个分块",
            **result,
        }
    except ValueError as e:
        raise HTTPException(status_code=404 if "不存在" in str(e) or "过期" in str(e) else 400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{kb_id}/import/preview/{preview_id}")
def import_preview_cancel(kb_id: str, preview_id: str, db: Session = Depends(get_db)):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.kb_id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    ks.delete_import_preview(kb_id, preview_id)
    return {"message": "已取消导入"}


@router.patch("/{kb_id}/files/{doc_id}/tags")
def update_file_tags(
    kb_id: str,
    doc_id: str,
    data: KnowledgeDocumentTagsUpdate,
    db: Session = Depends(get_db),
):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.kb_id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    try:
        result = ks.update_document_tags(kb_id, doc_id, data.tags)
    except ValueError as e:
        raise HTTPException(status_code=404 if "不存在" in str(e) else 400, detail=str(e))
    return {"message": "已更新文档标签", **result}


@router.post("/{kb_id}/reindex-contextual")
async def reindex_contextual(kb_id: str, db: Session = Depends(get_db)):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.kb_id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    try:
        result = await ks.reindex_contextual(
            kb_id,
            kb_description=kb.description or "",
            kb_override=kb.contextual_retrieval_enabled,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"message": "上下文索引重建完成", **result}