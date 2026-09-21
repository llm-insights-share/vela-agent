import base64
import os
import shutil
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

from models import gen_uuid
from services.attachment_retrieve import (
    ATTACHMENT_CONTEXT_BUDGET,
    ensure_units,
    format_units_for_prompt,
    resolve_intent,
    select_units,
    units_needing_ocr,
)
from services.document_parser import (
    MAX_EAGER_OCR_PAGES,
    PARSERS,
    chunk_by_paragraph,
    chunks_from_units,
    parse_file,
    parsed_text_from_units,
)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
ATTACHMENTS_DIR = os.path.join(DATA_DIR, "attachments")

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
MAX_ATTACHMENTS_PER_SESSION = 20
MAX_ATTACHMENTS_PER_MESSAGE = 5

# Re-export for existing imports / tests
FULL_INTENT_PATTERNS = [
    "全文", "整份", "整个文档", "全部内容", "总结一下",
    "summarize", "entire document", "full document", "whole document",
]

OCR_TRANSCRIPT_PROMPT = (
    "你是文档转写助手。请完整提取本页/本图中的全部文字，"
    "保留表格结构与关键字段、数值，不要总结、不要回答问题、不要添加解释。"
    "若几乎没有文字，请简要描述可见的版式要素（印章、签名、图表）。"
)

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
    ".csv": "text/csv",
    ".html": "text/html",
    ".htm": "text/html",
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
    try:
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(session, "pending_context")
    except Exception:
        pass


def set_pending_context(session, new_pending: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Replace pending_context while preserving the attachments registry."""
    registry = (session.pending_context or {}).get("attachments")
    pending = dict(new_pending or {})
    if registry:
        pending["attachments"] = registry
    session.pending_context = pending
    try:
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(session, "pending_context")
    except Exception:
        pass
    return pending


def _mime_for_filename(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    return MIME_TYPES.get(ext, "application/octet-stream")


def _persist_unit_images(
    session_id: str,
    session_dir: str,
    stem: str,
    units: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Write ephemeral _image_bytes to disk and return (clean_units, page_image_meta).
    """
    clean: List[Dict[str, Any]] = []
    page_image_meta: List[Dict[str, Any]] = []

    for u in units:
        unit = {
            "unit_index": u.get("unit_index"),
            "text": u.get("text") or "",
            "source": u.get("source") or "text_layer",
            "status": u.get("status") or "pending",
        }
        raw = u.get("_image_bytes")
        if raw:
            page_no = unit["unit_index"] or (len(page_image_meta) + 1)
            img_ext = u.get("_image_ext") or ".jpg"
            img_name = resolve_unique_filename(session_dir, f"{stem}.page{page_no}{img_ext}")
            img_abs = os.path.join(session_dir, img_name)
            with open(img_abs, "wb") as img_f:
                img_f.write(raw)
            rel = os.path.join("attachments", session_id, img_name)
            mime = u.get("_image_mime") or "image/jpeg"
            unit["stored_path"] = rel
            unit["mime_type"] = mime
            unit["filename"] = img_name
            page_image_meta.append({
                "page": page_no,
                "filename": img_name,
                "stored_path": rel,
                "mime_type": mime,
                "size_bytes": len(raw),
            })
        elif u.get("stored_path"):
            unit["stored_path"] = u.get("stored_path")
            unit["mime_type"] = u.get("mime_type")
            unit["filename"] = u.get("filename")
        clean.append(unit)

    return clean, page_image_meta


def _refresh_derived_fields(meta: Dict[str, Any]) -> None:
    """Update parsed_text, chunks, vision_text, text_length from units."""
    units = meta.get("units") or []
    filename = meta.get("filename") or ""
    text = parsed_text_from_units(units, filename)
    meta["parsed_text"] = text
    meta["chunks"] = chunks_from_units(units) or (
        chunk_by_paragraph(text) if text and not text.startswith("[") else []
    )
    if not meta["chunks"] and text and not text.startswith("[扫描件]") and not text.startswith("[图片]"):
        meta["chunks"] = [text]
    meta["text_length"] = len(text)
    # vision_text = joined OCR/ready texts for legacy consumers
    ready_bits = []
    for u in units:
        t = (u.get("text") or "").strip()
        if t and u.get("source") in ("ocr", "mixed"):
            idx = u.get("unit_index")
            ready_bits.append(f"[第{idx}页]\n{t}" if idx is not None else t)
    if ready_bits:
        meta["vision_text"] = "\n\n".join(ready_bits)
    elif text and not text.startswith("[扫描件]") and not text.startswith("[图片]"):
        # Keep existing vision_text if any; or set from full text when all text_layer
        pass


def _visual_files_for_units(
    meta: Dict[str, Any],
    unit_indices: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    """Resolve visual files, optionally filtered to unit indices."""
    files: List[Dict[str, Any]] = []
    units = ensure_units(meta)
    index_filter = set(unit_indices) if unit_indices is not None else None

    if meta.get("is_image"):
        if index_filter is None or 1 in index_filter:
            abs_path = _resolve_stored_path(meta.get("stored_path", ""))
            if abs_path and os.path.isfile(abs_path):
                files.append({
                    "unit_index": 1,
                    "filename": meta.get("filename") or "image",
                    "mime_type": meta.get("mime_type") or "image/png",
                    "abs_path": abs_path,
                })
        return files

    for u in units:
        idx = int(u.get("unit_index") or 0)
        if index_filter is not None and idx not in index_filter:
            continue
        path = u.get("stored_path")
        if not path:
            # Fall back to page_images
            for page in meta.get("page_images") or []:
                if page.get("page") == idx:
                    path = page.get("stored_path")
                    mime = page.get("mime_type")
                    fname = page.get("filename")
                    break
            else:
                continue
        else:
            mime = u.get("mime_type")
            fname = u.get("filename")
        abs_path = _resolve_stored_path(path)
        if abs_path and os.path.isfile(abs_path):
            files.append({
                "unit_index": idx,
                "filename": fname or f"{meta.get('filename')}-p{idx}",
                "mime_type": mime or "image/png",
                "abs_path": abs_path,
            })
    return files


def _visual_files_for_attachment(meta: Dict[str, Any]) -> List[Dict[str, str]]:
    """Legacy helper: all visual files for an attachment."""
    return [
        {
            "filename": f["filename"],
            "mime_type": f["mime_type"],
            "abs_path": f["abs_path"],
        }
        for f in _visual_files_for_units(meta)
    ]


def _attachment_has_usable_text(attachment: Dict[str, Any]) -> bool:
    units = ensure_units(attachment)
    for u in units:
        text = (u.get("text") or "").strip()
        if text and u.get("status") != "failed":
            return True
    vision = (attachment.get("vision_text") or "").strip()
    if vision:
        return True
    text = (attachment.get("parsed_text") or "").strip()
    if not text:
        return False
    if text.startswith("[扫描件]") or text.startswith("[图片]"):
        return False
    return True


_VISION_NAME_NEEDLES = (
    "-vl", "/vl", "vl-", "vl_", "vision", "gpt-4o", "gpt-4.1",
    "qvq", "-ocr", "/ocr", "ocr-", "ocr_",
)


def model_name_looks_like_vision(model_name: Optional[str]) -> bool:
    name = (model_name or "").lower()
    if not name:
        return False
    return any(n in name for n in _VISION_NAME_NEEDLES)


def infer_model_capabilities(model_name: Optional[str], existing: Optional[List[str]] = None) -> List[str]:
    caps = list(existing or [])
    if not caps:
        caps = ["text"]
    lower = [c.lower() for c in caps]
    if model_name_looks_like_vision(model_name) and not any(
        c in lower for c in ("vision", "image", "multimodal")
    ):
        caps.append("vision")
    return caps


def model_supports_vision(
    capabilities: Optional[List[str]],
    model_name: Optional[str] = None,
) -> bool:
    caps = [c.lower() for c in (capabilities or [])]
    if any(c in caps for c in ("vision", "image", "multimodal")):
        return True
    return model_name_looks_like_vision(model_name)


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
        text, is_image, _page_images_raw, raw_units = parse_file(file_bytes, unique_name)

        stem = os.path.splitext(unique_name)[0]
        units, page_image_meta = _persist_unit_images(
            session.session_id, session_dir, stem, raw_units
        )

        # Image attachments use the original file as the visual
        if is_image and units:
            units[0]["stored_path"] = rel_path
            units[0]["mime_type"] = _mime_for_filename(unique_name)
            units[0]["filename"] = unique_name

        chunks = chunks_from_units(units)
        if not chunks:
            if text.strip() and not text.startswith("[扫描件]") and not text.startswith("[图片]"):
                chunks = chunk_by_paragraph(text) or [text.strip()]
            else:
                chunks = [f"[文件] {unique_name}"]

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
            "units": units,
            "is_image": is_image,
            "page_images": page_image_meta,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        }
        registry[attachment_id] = meta
        _save_attachments_registry(session, registry)

        ready = sum(1 for u in units if u.get("status") == "ready")
        return {
            "attachment_id": attachment_id,
            "filename": unique_name,
            "mime_type": meta["mime_type"],
            "size_bytes": meta["size_bytes"],
            "text_length": meta["text_length"],
            "is_image": is_image,
            "units_ready": ready,
            "units_total": len(units),
        }

    def list_attachments(self, session) -> List[Dict[str, Any]]:
        registry = _get_attachments_registry(session)
        items = []
        for att_id, meta in registry.items():
            units = meta.get("units") or []
            items.append({
                "attachment_id": att_id,
                "filename": meta.get("filename"),
                "mime_type": meta.get("mime_type"),
                "size_bytes": meta.get("size_bytes"),
                "text_length": meta.get("text_length"),
                "is_image": meta.get("is_image", False),
                "uploaded_at": meta.get("uploaded_at"),
                "units_ready": sum(1 for u in units if u.get("status") == "ready"),
                "units_total": len(units) if units else 0,
            })
        items.sort(key=lambda x: x.get("uploaded_at") or "", reverse=True)
        return items

    def list_session_attachment_ids(self, session) -> List[str]:
        registry = _get_attachments_registry(session)
        items = sorted(
            registry.items(),
            key=lambda kv: (kv[1] or {}).get("uploaded_at") or "",
        )
        return [att_id for att_id, _ in items]

    def resolve_turn_attachment_ids(
        self,
        session,
        request_ids: Optional[List[str]] = None,
        scope: str = "session",
    ) -> Tuple[List[str], List[str]]:
        """Return (ids_for_context, new_ids_this_turn).

        scope=session → all session attachments (default).
        scope=message → only request_ids (this-turn uploads).
        """
        registry = _get_attachments_registry(session)
        session_ids = self.list_session_attachment_ids(session)
        new_ids = [aid for aid in (request_ids or []) if aid in registry]
        if (scope or "session") == "message":
            all_ids = list(new_ids)
            # Preserve session upload order among the requested ids
            ordered = [aid for aid in session_ids if aid in set(all_ids)]
            for aid in new_ids:
                if aid not in ordered:
                    ordered.append(aid)
            return ordered, new_ids
        all_ids = list(session_ids)
        for aid in new_ids:
            if aid not in all_ids:
                all_ids.append(aid)
        return all_ids, new_ids

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
        for page in meta.get("page_images") or []:
            page_path = _resolve_stored_path(page.get("stored_path", ""))
            if page_path and os.path.isfile(page_path):
                try:
                    os.remove(page_path)
                except OSError:
                    pass
        for u in meta.get("units") or []:
            up = u.get("stored_path")
            if up and up != meta.get("stored_path"):
                page_path = _resolve_stored_path(up)
                if page_path and os.path.isfile(page_path):
                    try:
                        os.remove(page_path)
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

    def _ensure_units_persisted(self, session, attachment_id: str, meta: Dict[str, Any]) -> List[Dict[str, Any]]:
        units = ensure_units(meta)
        if not meta.get("units"):
            meta["units"] = units
            _refresh_derived_fields(meta)
            registry = _get_attachments_registry(session)
            registry[attachment_id] = meta
            _save_attachments_registry(session, registry)
        return units

    def build_context(
        self,
        session,
        message: str,
        attachment_ids: List[str],
        history: Optional[List[Dict[str, Any]]] = None,
        model_capabilities: Optional[List[str]] = None,
        model_name: Optional[str] = None,
        new_attachment_ids: Optional[List[str]] = None,
    ) -> Tuple[str, Optional[List[Dict[str, Any]]], List[Dict[str, str]]]:
        """
        Build enriched user message text and optional multimodal image blocks.

        Uses unit-level retrieval (page / semantic / full). Image blocks are only
        attached for selected units that still need visual input this turn
        (new uploads with vision-capable models, or layout-sensitive pages).

        Returns:
            (text_suffix, image_blocks, attachment_metadata)
        """
        if not attachment_ids:
            return "", None, []

        if len(attachment_ids) > MAX_ATTACHMENTS_PER_SESSION:
            raise ValueError(f"会话附件数量已达上限 ({MAX_ATTACHMENTS_PER_SESSION})")

        registry = _get_attachments_registry(session)
        history = history or []
        vision = model_supports_vision(model_capabilities, model_name=model_name)
        new_set = set(new_attachment_ids or [])
        intent = resolve_intent(message)

        text_sections: List[str] = []
        image_blocks: List[Dict[str, Any]] = []
        metadata: List[Dict[str, str]] = []
        max_images = 8
        budget_remaining = ATTACHMENT_CONTEXT_BUDGET
        n_atts = max(len(attachment_ids), 1)
        per_att_budget = max(2000, budget_remaining // n_atts)

        # Inventory header for multi-attachment turns
        inventory_lines: List[str] = []
        if len(attachment_ids) > 1:
            inventory_lines.append("[会话附件清单]")
            for att_id in attachment_ids:
                m = registry.get(att_id) or {}
                units = m.get("units") or ensure_units(m)
                ready = sum(1 for u in units if u.get("status") == "ready")
                total = len(units)
                inventory_lines.append(
                    f"- {m.get('filename') or att_id}（已解析 {ready}/{total}）"
                )

        for att_id in attachment_ids:
            meta = registry.get(att_id)
            if not meta:
                raise ValueError(f"附件不存在: {att_id}")

            filename = meta.get("filename", "附件")
            metadata.append({"id": att_id, "filename": filename})
            self._ensure_units_persisted(session, att_id, meta)

            selection = select_units(meta, message, history)
            section = format_units_for_prompt(
                filename, selection, char_budget=min(per_att_budget, budget_remaining)
            )
            budget_remaining = max(0, budget_remaining - len(section))
            text_sections.append(section)

            selected_indices = [u.unit_index for u in selection.units]
            is_new = att_id in new_set
            need_visual = [
                u for u in selection.units
                if (not u.text or u.status == "pending") and (
                    u.stored_path or meta.get("is_image")
                )
            ]
            send_indices: List[int] = []
            if vision and need_visual:
                send_indices = [u.unit_index for u in need_visual]
            elif vision and is_new and intent.kind == "page" and selected_indices:
                send_indices = selected_indices[:1]
            elif vision and is_new and not _attachment_has_usable_text(meta):
                send_indices = selected_indices[:max_images] or [
                    int(u.get("unit_index") or 0)
                    for u in (meta.get("units") or [])[:3]
                ]

            if send_indices:
                for vis in _visual_files_for_units(meta, send_indices):
                    if len(image_blocks) >= max_images:
                        break
                    with open(vis["abs_path"], "rb") as f:
                        b64 = base64.b64encode(f.read()).decode("ascii")
                    mime = vis.get("mime_type") or "image/png"
                    image_blocks.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    })

        if inventory_lines:
            text_sections.insert(0, "\n".join(inventory_lines))

        suffix = ""
        if text_sections:
            suffix = "\n\n---\n" + "\n\n---\n".join(text_sections) + "\n---"

        return suffix, (image_blocks or None), metadata

    def ids_needing_vision_ocr(
        self,
        session,
        attachment_ids: List[str],
        skip_ids: Optional[List[str]] = None,
        message: Optional[str] = None,
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> List[str]:
        """
        Attachments that still have pending units needing OCR.
        skip_ids is ignored for transcription (plan: always persist unit text);
        kept for API compatibility.
        """
        del skip_ids  # transcription always runs for pending units
        registry = _get_attachments_registry(session)
        out: List[str] = []
        for att_id in attachment_ids or []:
            meta = registry.get(att_id)
            if not meta:
                continue
            self._ensure_units_persisted(session, att_id, meta)
            if message is not None:
                selection = select_units(meta, message, history)
                need = units_needing_ocr(meta, selected=selection.units)
            else:
                need = units_needing_ocr(meta, selected=None, eager_limit=MAX_EAGER_OCR_PAGES)
            if need:
                out.append(att_id)
        return out

    def unit_indices_needing_ocr(
        self,
        session,
        attachment_id: str,
        message: Optional[str] = None,
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> List[int]:
        meta = self.get_attachment(session, attachment_id)
        if not meta:
            return []
        self._ensure_units_persisted(session, attachment_id, meta)
        if message is not None:
            selection = select_units(meta, message, history)
            need = units_needing_ocr(meta, selected=selection.units)
            if resolve_intent(message).kind == "full":
                need = need[:MAX_EAGER_OCR_PAGES]
            return need
        return units_needing_ocr(meta, selected=None, eager_limit=MAX_EAGER_OCR_PAGES)

    def cache_unit_text(
        self,
        session,
        attachment_id: str,
        unit_index: int,
        text: str,
        vision_model: Optional[str] = None,
        source: str = "ocr",
    ) -> None:
        """Write OCR/transcript text into a single unit without touching others."""
        registry = _get_attachments_registry(session)
        meta = registry.get(attachment_id)
        if not meta:
            return
        cleaned = (text or "").strip()
        if not cleaned or "视觉解析失败" in cleaned:
            return
        units = self._ensure_units_persisted(session, attachment_id, meta)
        found = False
        for u in units:
            if int(u.get("unit_index") or 0) == int(unit_index):
                u["text"] = cleaned
                u["status"] = "ready"
                u["source"] = source
                found = True
                break
        if not found:
            units.append({
                "unit_index": unit_index,
                "text": cleaned,
                "source": source,
                "status": "ready",
            })
        meta["units"] = units
        if vision_model:
            meta["vision_model"] = vision_model
        _refresh_derived_fields(meta)
        registry[attachment_id] = meta
        _save_attachments_registry(session, registry)

    def cache_vision_text(
        self,
        session,
        attachment_id: str,
        text: str,
        vision_model: Optional[str] = None,
    ) -> None:
        """
        Legacy whole-blob cache. Prefer cache_unit_text.
        Splits [第N页] markers into units when possible.
        """
        cleaned = (text or "").strip()
        if not cleaned or "视觉解析失败" in cleaned:
            return
        registry = _get_attachments_registry(session)
        meta = registry.get(attachment_id)
        if not meta:
            return

        # Try to split into pages
        import re
        parts = re.split(r"\[第(\d+)页\]\s*", cleaned)
        if len(parts) >= 3 and parts[1].isdigit():
            i = 1
            while i + 1 < len(parts):
                try:
                    idx = int(parts[i])
                except ValueError:
                    idx = i
                body = (parts[i + 1] or "").strip()
                if body:
                    self.cache_unit_text(
                        session, attachment_id, idx, body,
                        vision_model=vision_model, source="ocr",
                    )
                i += 2
            return

        # Single unit (image or one-page)
        self.cache_unit_text(
            session, attachment_id, 1, cleaned,
            vision_model=vision_model, source="ocr",
        )

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

    @staticmethod
    def flatten_user_content(content: Union[str, List[Dict[str, Any]], None]) -> str:
        """Flatten multimodal user content to a string for text-only engines (WF/MA)."""
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    parts.append(block.get("text") or "")
                elif btype == "image_url":
                    parts.append("[图像附件]")
            return "\n".join(p for p in parts if p).strip()
        return str(content)

    def list_image_attachments(
        self,
        session,
        attachment_ids: List[str],
        unit_indices_by_att: Optional[Dict[str, List[int]]] = None,
    ) -> List[Dict[str, Any]]:
        registry = _get_attachments_registry(session)
        out: List[Dict[str, Any]] = []
        for att_id in attachment_ids or []:
            meta = registry.get(att_id)
            if not meta:
                continue
            indices = (unit_indices_by_att or {}).get(att_id)
            for vis in _visual_files_for_units(meta, indices):
                out.append({
                    "attachment_id": att_id,
                    "unit_index": vis.get("unit_index"),
                    "filename": vis.get("filename") or "image",
                    "mime_type": vis.get("mime_type") or "image/png",
                    "abs_path": vis["abs_path"],
                })
        return out

    @staticmethod
    def resolve_vision_model_service(db) -> Tuple[Any, Any, str]:
        """Pick an active ModelService+Provider that can accept image_url inputs."""
        from models import ModelProvider, ModelService, ModelServiceStatus, ProviderStatus

        candidates = (
            db.query(ModelService)
            .filter(ModelService.status == ModelServiceStatus.ACTIVE)
            .all()
        )
        ranked: List[Any] = []
        for row in candidates:
            name = (row.model_name or "").lower()
            caps = [c.lower() for c in (row.capabilities or [])]
            score = 0
            if any(c in caps for c in ("vision", "image", "multimodal")):
                score += 3
            if model_name_looks_like_vision(name):
                score += 2
            if "ocr" in name:
                score += 1
            if "vl-plus" in name or "vl-max" in name or "qwen3-vl" in name:
                score += 1
            if score > 0:
                if name.startswith("qwen") and "/" not in name:
                    score += 1
                if "aliyun/" in name or "vanchin/" in name:
                    score -= 0.5
                ranked.append((score, row))
        ranked.sort(key=lambda x: (-x[0], (x[1].model_name or "")))

        for _, svc in ranked:
            provider = (
                db.query(ModelProvider)
                .filter(
                    ModelProvider.provider_id == svc.provider_id,
                    ModelProvider.status == ProviderStatus.ACTIVE,
                )
                .first()
            )
            if provider and (provider.api_key or "").strip():
                return provider, svc, ""
        return None, None, "未找到可用的视觉/OCR 模型服务"

    async def transcribe_units(
        self,
        db,
        session,
        attachment_ids: List[str],
        message: Optional[str] = None,
        history: Optional[List[Dict[str, Any]]] = None,
        unit_indices_by_att: Optional[Dict[str, List[int]]] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Question-agnostic OCR for pending units. Caches per-unit text.
        Returns a text suffix summarizing what was transcribed (for immediate use).
        """
        info: Dict[str, Any] = {
            "image_count": 0,
            "vision_model": None,
            "ok": False,
            "error": None,
            "chars": 0,
            "units_done": 0,
        }

        indices_map: Dict[str, List[int]] = dict(unit_indices_by_att or {})
        if not indices_map:
            for att_id in attachment_ids or []:
                need = self.unit_indices_needing_ocr(session, att_id, message, history)
                if need:
                    indices_map[att_id] = need

        if not indices_map:
            return "", info

        images = self.list_image_attachments(
            session, list(indices_map.keys()), unit_indices_by_att=indices_map
        )
        info["image_count"] = len(images)
        if not images:
            return "", info

        provider, svc, err = self.resolve_vision_model_service(db)
        if not provider or not svc:
            info["error"] = err or "no_vision_model"
            return "", info

        info["vision_model"] = svc.model_name
        from services.model_provider import model_provider_service

        sections: List[str] = []
        by_att: Dict[str, List[Dict[str, Any]]] = {}
        for img in images:
            by_att.setdefault(img["attachment_id"], []).append(img)

        for att_id, pages in by_att.items():
            meta = self.get_attachment(session, att_id) or {}
            display_name = meta.get("filename") or "image"
            page_parts: List[str] = []
            failed = False
            for img in pages:
                unit_index = img.get("unit_index") or 1
                with open(img["abs_path"], "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("ascii")
                mime = img["mime_type"]
                messages = [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": OCR_TRANSCRIPT_PROMPT},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:{mime};base64,{b64}"},
                            },
                        ],
                    }
                ]
                try:
                    completion = await model_provider_service.chat_completion(
                        provider,
                        svc.model_name,
                        messages,
                        max_tokens=min(int(svc.max_tokens or 2048), 4096),
                        temperature=0.1,
                        source="attachment_vision",
                    )
                    answer = ""
                    choices = completion.get("choices") or []
                    if choices:
                        answer = ((choices[0].get("message") or {}).get("content") or "").strip()
                    if not answer:
                        answer = "(视觉模型未返回内容)"
                    if "视觉解析失败" not in answer and answer != "(视觉模型未返回内容)":
                        self.cache_unit_text(
                            session, att_id, int(unit_index), answer,
                            vision_model=svc.model_name, source="ocr",
                        )
                        info["units_done"] += 1
                    page_parts.append(f"【附件: {display_name} · 第{unit_index}页】\n{answer}")
                except Exception as e:
                    info["error"] = str(e)[:300]
                    failed = True
                    page_parts.append(
                        f"【附件: {display_name} · 第{unit_index}页】(视觉解析失败: {str(e)[:200]})"
                    )

            if page_parts:
                sections.append("\n\n".join(page_parts))
            if not failed:
                info["ok"] = True

        if not sections:
            return "", info

        suffix = "\n\n---\n" + "\n\n---\n".join(sections) + "\n---"
        info["chars"] = len(suffix)
        return suffix, info

    async def describe_images_for_text_model(
        self,
        db,
        session,
        attachment_ids: List[str],
        question: str,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Backward-compatible wrapper: question-agnostic unit transcription.
        The question is only used to select which pending units to OCR first.
        """
        return await self.transcribe_units(
            db,
            session,
            attachment_ids,
            message=question,
            history=None,
        )


attachment_service = AttachmentService()
