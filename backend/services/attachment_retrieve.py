"""Intent routing and unit selection for session attachments."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

FULL_INTENT_PATTERNS = [
    "全文", "整份", "整个文档", "全部内容", "总结一下",
    "summarize", "entire document", "full document", "whole document",
]

# 第3页 / 第 3 页 / page 3 / p.3 / P3
_PAGE_PATTERNS = [
    re.compile(r"第\s*(\d+)\s*页"),
    re.compile(r"\bpage\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\bp(?:age)?[.\s]*(\d+)\b", re.IGNORECASE),
]

TOP_K_UNITS = 6
FULL_CONTENT_THRESHOLD = 8000
MAX_EXTRACTED_CHARS = 12000
MAX_FULL_TRUNCATED_CHARS = 50000
# Total chars injected across all attachments in one turn (semantic/full).
ATTACHMENT_CONTEXT_BUDGET = 24000


@dataclass
class QueryIntent:
    kind: str  # "page" | "semantic" | "full"
    page: Optional[int] = None


@dataclass
class SelectedUnit:
    unit_index: int
    text: str
    status: str
    source: str = ""
    stored_path: Optional[str] = None
    mime_type: Optional[str] = None
    filename: Optional[str] = None


@dataclass
class SelectionResult:
    mode: str  # "第N页" | "相关片段" | "全文" | "待解析" | "空内容" | "页不存在"
    units: List[SelectedUnit] = field(default_factory=list)
    message: str = ""  # error / hint for the model


def resolve_intent(message: str) -> QueryIntent:
    text = (message or "").strip()
    lower = text.lower()
    if any(p in lower for p in FULL_INTENT_PATTERNS):
        return QueryIntent(kind="full")
    for pat in _PAGE_PATTERNS:
        m = pat.search(text)
        if m:
            try:
                page = int(m.group(1))
                if page >= 1:
                    return QueryIntent(kind="page", page=page)
            except (TypeError, ValueError):
                pass
    return QueryIntent(kind="semantic")


def _tokenize(text: str) -> List[str]:
    import jieba
    return [t.strip() for t in jieba.lcut(text or "") if t and t.strip()]


def _build_query(message: str, history: Optional[List[Dict[str, Any]]] = None) -> str:
    parts = [(message or "").strip()]
    recent = (history or [])[-4:]
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


def ensure_units(attachment: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Return units list, migrating legacy flat vision_text / parsed_text when needed.
    Does not persist — caller should write back if migration happened.
    """
    units = attachment.get("units")
    if isinstance(units, list) and units:
        return units

    migrated: List[Dict[str, Any]] = []
    vision = (attachment.get("vision_text") or "").strip()
    parsed = (attachment.get("parsed_text") or "").strip()
    text = vision or parsed

    # Try split by [第N页] markers from legacy OCR join
    if text and not text.startswith("[扫描件]") and not text.startswith("[图片]"):
        parts = re.split(r"\[第(\d+)页\]\s*", text)
        # parts: [preamble, num, body, num, body, ...]
        if len(parts) >= 3 and parts[1].isdigit():
            i = 1
            while i + 1 < len(parts):
                try:
                    idx = int(parts[i])
                except ValueError:
                    idx = len(migrated) + 1
                body = (parts[i + 1] or "").strip()
                if body:
                    migrated.append({
                        "unit_index": idx,
                        "text": body,
                        "source": "ocr" if vision else "text_layer",
                        "status": "ready",
                    })
                i += 2
            if migrated:
                # Attach page_images paths if present
                by_page = {
                    p.get("page"): p
                    for p in (attachment.get("page_images") or [])
                    if p.get("page") is not None
                }
                for u in migrated:
                    img = by_page.get(u["unit_index"])
                    if img:
                        u["stored_path"] = img.get("stored_path")
                        u["mime_type"] = img.get("mime_type")
                        u["filename"] = img.get("filename")
                return migrated

        # Single blob → one unit
        migrated.append({
            "unit_index": 1,
            "text": text,
            "source": "ocr" if vision else "text_layer",
            "status": "ready",
        })
        if attachment.get("is_image") and attachment.get("stored_path"):
            migrated[0]["stored_path"] = attachment.get("stored_path")
            migrated[0]["mime_type"] = attachment.get("mime_type")
        elif attachment.get("page_images"):
            img = attachment["page_images"][0]
            migrated[0]["stored_path"] = img.get("stored_path")
            migrated[0]["mime_type"] = img.get("mime_type")
            migrated[0]["filename"] = img.get("filename")
        return migrated

    # Placeholder / empty: build pending units from page_images or image
    if attachment.get("is_image"):
        return [{
            "unit_index": 1,
            "text": "",
            "source": "ocr",
            "status": "pending",
            "stored_path": attachment.get("stored_path"),
            "mime_type": attachment.get("mime_type"),
            "filename": attachment.get("filename"),
        }]

    page_images = attachment.get("page_images") or []
    if page_images:
        out = []
        for img in page_images:
            out.append({
                "unit_index": img.get("page") or (len(out) + 1),
                "text": "",
                "source": "ocr",
                "status": "pending",
                "stored_path": img.get("stored_path"),
                "mime_type": img.get("mime_type"),
                "filename": img.get("filename"),
            })
        return out

    return []


def _unit_to_selected(u: Dict[str, Any]) -> SelectedUnit:
    return SelectedUnit(
        unit_index=int(u.get("unit_index") or 0),
        text=(u.get("text") or "").strip(),
        status=u.get("status") or "pending",
        source=u.get("source") or "",
        stored_path=u.get("stored_path"),
        mime_type=u.get("mime_type"),
        filename=u.get("filename"),
    )


def _ready_units(units: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        u for u in units
        if (u.get("text") or "").strip() and u.get("status") != "failed"
    ]


def _search_unit_indices(
    query: str,
    units: List[Dict[str, Any]],
    top_k: int = TOP_K_UNITS,
) -> List[int]:
    """BM25 over unit texts; return unit_index list."""
    ready = _ready_units(units)
    if not ready:
        return []
    if not (query or "").strip():
        return [int(u["unit_index"]) for u in ready[:top_k]]

    from rank_bm25 import BM25Okapi

    corpus = [_tokenize(u.get("text") or "") for u in ready]
    if not any(corpus):
        return [int(u["unit_index"]) for u in ready[:top_k]]

    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(_tokenize(query))
    ranked = sorted(range(len(ready)), key=lambda i: scores[i], reverse=True)
    picked = []
    for i in ranked:
        if scores[i] <= 0 and picked:
            break
        picked.append(int(ready[i]["unit_index"]))
        if len(picked) >= top_k:
            break
    return picked or [int(u["unit_index"]) for u in ready[:top_k]]


def select_units(
    attachment: Dict[str, Any],
    message: str,
    history: Optional[List[Dict[str, Any]]] = None,
) -> SelectionResult:
    """
    Choose which document units to inject for this turn.
    Does not perform OCR — pending units are returned for the caller to transcribe.
    """
    filename = attachment.get("filename") or "附件"
    units = ensure_units(attachment)
    intent = resolve_intent(message)

    if not units:
        return SelectionResult(
            mode="空内容",
            message=f"[附件 {filename} 无可用文本内容]",
        )

    by_index = {int(u.get("unit_index") or 0): u for u in units}

    if intent.kind == "page":
        page = intent.page or 0
        u = by_index.get(page)
        if not u:
            total = len(units)
            return SelectionResult(
                mode="页不存在",
                message=f"[附件 {filename} 没有第{page}页，共 {total} 页]",
            )
        return SelectionResult(
            mode=f"第{page}页",
            units=[_unit_to_selected(u)],
        )

    if intent.kind == "full":
        selected = [_unit_to_selected(u) for u in units]
        # Prefer ready first but include pending so OCR can fill
        return SelectionResult(mode="全文", units=selected)

    # semantic
    ready = _ready_units(units)
    total_chars = sum(len((u.get("text") or "")) for u in ready)
    if total_chars <= FULL_CONTENT_THRESHOLD and ready and not any(
        u.get("status") == "pending" for u in units
    ):
        return SelectionResult(
            mode="全文",
            units=[_unit_to_selected(u) for u in ready],
        )

    query = _build_query(message, history)
    indices = _search_unit_indices(query, units, top_k=TOP_K_UNITS)
    if indices:
        selected = [_unit_to_selected(by_index[i]) for i in indices if i in by_index]
        return SelectionResult(mode="相关片段", units=selected)

    # Nothing ready yet — return pending units (eager first pages) for OCR
    pending = [u for u in units if u.get("status") == "pending"]
    if pending:
        return SelectionResult(
            mode="待解析",
            units=[_unit_to_selected(u) for u in pending[:TOP_K_UNITS]],
        )

    return SelectionResult(
        mode="空内容",
        message=f"[附件 {filename} 无可用文本内容]",
    )


def format_units_for_prompt(
    filename: str,
    selection: SelectionResult,
    char_budget: Optional[int] = None,
) -> str:
    """Render selected units as a cited text block for the model."""
    if selection.message and not selection.units:
        return f"【附件: {filename}】({selection.mode})\n{selection.message}"

    parts: List[str] = []
    total_len = 0
    default_limit = MAX_FULL_TRUNCATED_CHARS if selection.mode == "全文" else MAX_EXTRACTED_CHARS
    limit = min(char_budget, default_limit) if char_budget is not None else default_limit

    for u in selection.units:
        if u.status == "pending" and not u.text:
            block = f"【附件: {filename} · 第{u.unit_index}页】(待视觉解析)"
        elif u.status == "failed" and not u.text:
            block = f"【附件: {filename} · 第{u.unit_index}页】(解析失败)"
        else:
            body = u.text
            header = f"【附件: {filename} · 第{u.unit_index}页】"
            block = f"{header}\n{body}" if body else header

        if total_len + len(block) > limit:
            remaining = limit - total_len
            if remaining > 80:
                parts.append(block[:remaining] + "\n...(内容已截断)")
            else:
                parts.append("...(内容已截断)")
            break
        parts.append(block)
        total_len += len(block)

    if not parts:
        return f"【附件: {filename}】({selection.mode})\n{selection.message or '无内容'}"

    return "\n\n".join(parts)


def units_needing_ocr(
    attachment: Dict[str, Any],
    selected: Optional[List[SelectedUnit]] = None,
    eager_limit: int = 20,
) -> List[int]:
    """unit_index values that need OCR (pending + have image path)."""
    units = ensure_units(attachment)
    by_index = {int(u.get("unit_index") or 0): u for u in units}

    if selected is not None:
        targets = [s.unit_index for s in selected]
    else:
        # Eager: first N pending pages
        targets = [
            int(u.get("unit_index") or 0)
            for u in units
            if u.get("status") == "pending"
        ][:eager_limit]

    out = []
    for idx in targets:
        u = by_index.get(idx)
        if not u:
            continue
        if (u.get("text") or "").strip() and u.get("status") == "ready":
            continue
        if u.get("status") == "failed" and not u.get("stored_path"):
            continue
        # Need an image to OCR
        has_img = bool(u.get("stored_path"))
        if not has_img and attachment.get("is_image"):
            has_img = bool(attachment.get("stored_path"))
        if has_img or u.get("status") == "pending":
            out.append(idx)
    return out
