import base64
import os
import re
import shutil
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

from models import gen_uuid
from services.document_parser import (
    IMAGE_EXTS,
    PARSERS,
    chunk_by_paragraph,
    parse_file,
)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
ATTACHMENTS_DIR = os.path.join(DATA_DIR, "attachments")

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
MAX_ATTACHMENTS_PER_SESSION = 20
MAX_ATTACHMENTS_PER_MESSAGE = 5
FULL_CONTENT_THRESHOLD = 8000
MAX_EXTRACTED_CHARS = 12000
MAX_FULL_TRUNCATED_CHARS = 50000

FULL_INTENT_PATTERNS = [
    "全文", "整份", "整个文档", "全部内容", "总结一下",
    "summarize", "entire document", "full document", "whole document",
]

MIME_TYPES = {
    ".html": "text/html",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
}


def _session_dir(session_id: str) -> str:
    return os.path.join(ATTACHMENTS_DIR, session_id)


def _resolve_stored_path(stored_path: str) -> str:
    if os.path.isabs(stored_path):
        return stored_path
    return os.path.join(DATA_DIR, stored_path)


def resolve_unique_filename(directory: str, filename: str) -> str:
    base, ext = os.path.splitext(filename)
    candidate = filename
    counter = 1
    while os.path.exists(os.path.join(directory, candidate)):
        candidate = f"{base}({counter}){ext}"
        counter += 1
    return candidate


def _get_attachments_registry(session) -> Dict[str, Any]:
    pending = dict(session.pending_context or {})
    return dict(pending.get("attachments") or {})


def _save_attachments_registry(session, registry: Dict[str, Any]) -> None:
    pending = dict(session.pending_context or {})
    pending["attachments"] = registry
    session.pending_context = pending


def _mime_for_filename(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    return MIME_TYPES.get(ext, "application/octet-stream")


def _tokenize(text: str) -> List[str]:
    import jieba
    return [t.strip() for t in jieba.lcut(text or "") if t and t.strip()]


def _search_chunks(query: str, chunks: List[str], top_k: int = 5) -> List[str]:
    if not chunks:
        return []
    if not query.strip():
        return chunks[:top_k]

    from rank_bm25 import BM25Okapi

    corpus = [_tokenize(c) for c in chunks]
    if not any(corpus):
        return chunks[:top_k]

    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(_tokenize(query))
    ranked = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)
    return [chunks[i] for i in ranked[:top_k] if scores[i] > 0] or chunks[:top_k]


def _wants_full_content(message: str) -> bool:
    lower = (message or "").lower()
    return any(p in lower for p in FULL_INTENT_PATTERNS)


def _build_query(message: str, history: List[Dict[str, Any]]) -> str:
    parts = [(message or "").strip()]
    recent = history[-4:] if history else []
    for msg in recent:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if isinstance(content, list):
            text_parts = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            content = " ".join(text_parts)
        if role in ("user", "assistant") and content:
            parts.append(str(content)[:500])
    return " ".join(p for p in parts if p)


def _extract_attachment_text(
    attachment: Dict[str, Any],
    message: str,
    history: List[Dict[str, Any]],
) -> Tuple[str, str]:
    """Return (content, mode_label) where mode_label is '全文' or '相关片段'."""
    text = attachment.get("parsed_text") or ""
    chunks = attachment.get("chunks") or []
    filename = attachment.get("filename", "附件")

    if not text.strip() and not attachment.get("is_image"):
        return f"[附件 {filename} 无可用文本内容]", "空内容"

    if len(text) <= FULL_CONTENT_THRESHOLD or _wants_full_content(message):
        content = text
        if len(content) > MAX_FULL_TRUNCATED_CHARS:
            content = content[:MAX_FULL_TRUNCATED_CHARS] + "\n...(内容已截断)"
        mode = "全文"
    else:
        query = _build_query(message, history)
        selected = _search_chunks(query, chunks, top_k=5)
        content = "\n\n---\n\n".join(selected)
        if len(content) > MAX_EXTRACTED_CHARS:
            content = content[:MAX_EXTRACTED_CHARS] + "\n...(片段已截断)"
        mode = "相关片段"

    return content, mode


def model_supports_vision(capabilities: Optional[List[str]]) -> bool:
    caps = [c.lower() for c in (capabilities or [])]
    return any(c in caps for c in ("vision", "image", "multimodal"))


class AttachmentService:
    def save_attachment(
        self,
        session,
        file_bytes: bytes,
        filename: str,
    ) -> Dict[str, Any]:
        if len(file_bytes) > MAX_FILE_SIZE:
            raise ValueError(f"文件大小超过限制 ({MAX_FILE_SIZE // (1024 * 1024)}MB)")

        registry = _get_attachments_registry(session)
        if len(registry) >= MAX_ATTACHMENTS_PER_SESSION:
            raise ValueError(f"会话附件数量已达上限 ({MAX_ATTACHMENTS_PER_SESSION})")

        ext = os.path.splitext(filename)[1].lower()
        if ext not in PARSERS:
            supported = ", ".join(sorted(PARSERS.keys()))
            raise ValueError(f"不支持的文件格式 {ext or '(无扩展名)'}，支持: {supported}")

        session_dir = _session_dir(session.session_id)
        os.makedirs(session_dir, exist_ok=True)
        unique_name = resolve_unique_filename(session_dir, filename)
        abs_path = os.path.join(session_dir, unique_name)

        with open(abs_path, "wb") as f:
            f.write(file_bytes)

        rel_path = os.path.join("attachments", session.session_id, unique_name)
        text, is_image = parse_file(file_bytes, unique_name)

        if is_image:
            chunks = [text]
        else:
            chunks = chunk_by_paragraph(text)
            if not chunks:
                chunks = [text.strip()] if text.strip() else [f"[文件] {unique_name}"]

        attachment_id = f"att_{gen_uuid()[:12]}"
        meta = {
            "attachment_id": attachment_id,
            "filename": unique_name,
            "stored_path": rel_path,
            "mime_type": _mime_for_filename(unique_name),
            "size_bytes": len(file_bytes),
            "text_length": len(text),
            "parsed_text": text,
            "chunks": chunks,
            "is_image": is_image,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        }
        registry[attachment_id] = meta
        _save_attachments_registry(session, registry)

        return {
            "attachment_id": attachment_id,
            "filename": unique_name,
            "mime_type": meta["mime_type"],
            "size_bytes": meta["size_bytes"],
            "text_length": meta["text_length"],
            "is_image": is_image,
        }

    def list_attachments(self, session) -> List[Dict[str, Any]]:
        registry = _get_attachments_registry(session)
        items = []
        for att_id, meta in registry.items():
            items.append({
                "attachment_id": att_id,
                "filename": meta.get("filename"),
                "mime_type": meta.get("mime_type"),
                "size_bytes": meta.get("size_bytes"),
                "text_length": meta.get("text_length"),
                "is_image": meta.get("is_image", False),
                "uploaded_at": meta.get("uploaded_at"),
            })
        items.sort(key=lambda x: x.get("uploaded_at") or "", reverse=True)
        return items

    def get_attachment(self, session, attachment_id: str) -> Optional[Dict[str, Any]]:
        registry = _get_attachments_registry(session)
        return registry.get(attachment_id)

    def delete_attachment(self, session, attachment_id: str) -> bool:
        registry = _get_attachments_registry(session)
        meta = registry.pop(attachment_id, None)
        if not meta:
            return False

        abs_path = _resolve_stored_path(meta.get("stored_path", ""))
        if abs_path and os.path.isfile(abs_path):
            try:
                os.remove(abs_path)
            except OSError:
                pass

        _save_attachments_registry(session, registry)
        return True

    def cleanup_session(self, session_id: str) -> None:
        session_dir = _session_dir(session_id)
        if os.path.isdir(session_dir):
            try:
                shutil.rmtree(session_dir)
            except OSError:
                pass

    def get_attachment_metadata_for_message(
        self,
        session,
        attachment_ids: List[str],
    ) -> List[Dict[str, str]]:
        registry = _get_attachments_registry(session)
        result = []
        for att_id in attachment_ids:
            meta = registry.get(att_id)
            if meta:
                result.append({
                    "id": att_id,
                    "filename": meta.get("filename", ""),
                })
        return result

    def build_context(
        self,
        session,
        message: str,
        attachment_ids: List[str],
        history: Optional[List[Dict[str, Any]]] = None,
        model_capabilities: Optional[List[str]] = None,
    ) -> Tuple[str, Optional[List[Dict[str, Any]]], List[Dict[str, str]]]:
        """
        Build enriched user message text and optional multimodal image blocks.

        Returns:
            (text_suffix, image_blocks, attachment_metadata)
        """
        if not attachment_ids:
            return "", None, []

        if len(attachment_ids) > MAX_ATTACHMENTS_PER_MESSAGE:
            raise ValueError(f"单条消息最多引用 {MAX_ATTACHMENTS_PER_MESSAGE} 个附件")

        registry = _get_attachments_registry(session)
        history = history or []
        vision = model_supports_vision(model_capabilities)

        text_sections: List[str] = []
        image_blocks: List[Dict[str, Any]] = []
        metadata: List[Dict[str, str]] = []

        for att_id in attachment_ids:
            meta = registry.get(att_id)
            if not meta:
                raise ValueError(f"附件不存在: {att_id}")

            filename = meta.get("filename", "附件")
            metadata.append({"id": att_id, "filename": filename})

            if meta.get("is_image"):
                if vision:
                    abs_path = _resolve_stored_path(meta.get("stored_path", ""))
                    if abs_path and os.path.isfile(abs_path):
                        with open(abs_path, "rb") as f:
                            b64 = base64.b64encode(f.read()).decode("ascii")
                        mime = meta.get("mime_type") or "image/png"
                        image_blocks.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}"},
                        })
                    text_sections.append(f"【附件: {filename}】(图片，已作为视觉输入)")
                else:
                    text_sections.append(
                        f"【附件: {filename}】[图片附件: {filename}]，当前模型不支持视觉理解"
                    )
            else:
                content, mode = _extract_attachment_text(meta, message, history)
                text_sections.append(f"【附件: {filename}】({mode})\n{content}")

        suffix = ""
        if text_sections:
            suffix = "\n\n---\n" + "\n\n---\n".join(text_sections) + "\n---"

        return suffix, (image_blocks or None), metadata

    def build_user_content(
        self,
        message: str,
        text_suffix: str,
        image_blocks: Optional[List[Dict[str, Any]]],
    ) -> Union[str, List[Dict[str, Any]]]:
        """Combine user text, attachment suffix, and optional image blocks."""
        full_text = (message or "").strip()
        if text_suffix:
            full_text = full_text + text_suffix if full_text else text_suffix.strip()

        if not image_blocks:
            return full_text or "请分析附件"

        content_blocks: List[Dict[str, Any]] = []
        if full_text:
            content_blocks.append({"type": "text", "text": full_text})
        content_blocks.extend(image_blocks)
        return content_blocks


attachment_service = AttachmentService()
