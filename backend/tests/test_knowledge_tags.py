"""Tests for knowledge-base document tags, import preview, and tag-filtered search."""

import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from services.knowledge.tag_extractor import (
    extract_tags,
    extract_tags_heuristic,
    suggest_tag_filters_heuristic,
    today_str,
)


TAG_DEFS = [
    {"name": "作者", "type": "text", "hint": ""},
    {"name": "创建时间", "type": "date", "hint": ""},
    {"name": "失效时间", "type": "date", "hint": ""},
    {"name": "发布部门", "type": "text", "hint": ""},
]

LONG_A = (
    "采购办法规定了招标投标的程序、责任部门和监督检查要求，"
    "用于验证知识库按标签筛选后再进行向量与关键词召回。"
)
LONG_B = (
    "采购办法同时明确了废止条款与过渡安排，"
    "用于验证失效文档在无标签条件时仍可被全库召回。"
)


@pytest.fixture
def ks(monkeypatch, tmp_path):
    monkeypatch.setattr("services.knowledge_service.DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        "services.knowledge_service.KB_FILES_DIR",
        str(tmp_path / "kb_files"),
    )
    monkeypatch.setattr(
        "services.knowledge_service.PENDING_DIR",
        str(tmp_path / "kb_pending"),
    )
    from services.knowledge_service import KnowledgeService, SimpleEmbedding

    monkeypatch.setattr(
        "services.knowledge_service._create_embedding_model",
        lambda: SimpleEmbedding(dim=384),
    )
    return KnowledgeService()


def test_heuristic_extracts_and_normalizes_expire_date():
    text = "本办法自公布之日起施行，失效日期 2027年1月1日。"
    result = {item["name"]: item for item in extract_tags_heuristic(TAG_DEFS, text, "办法.txt")}
    assert result["失效时间"]["value"] == "2027/01/01"
    assert result["失效时间"]["source"] == "heuristic"
    assert result["作者"]["value"] == ""
    assert result["作者"]["source"] == "empty"
    assert result["创建时间"]["value"] == today_str()
    assert result["创建时间"]["source"] == "heuristic"


@pytest.mark.asyncio
async def test_extract_tags_llm_json_written(monkeypatch):
    async def fake_llm(tag_defs, document_text, filename, db, model_service_id):
        return {"失效时间": "2027-01-01", "作者": "法规司"}

    monkeypatch.setattr(
        "services.knowledge.tag_extractor._llm_extract_tag_values",
        fake_llm,
    )
    result = {
        item["name"]: item
        for item in await extract_tags(TAG_DEFS, "正文", "f.txt", db=object())
    }
    assert result["失效时间"]["value"] == "2027/01/01"
    assert result["失效时间"]["source"] == "llm"
    assert result["作者"]["value"] == "法规司"
    assert result["作者"]["source"] == "llm"


@pytest.mark.asyncio
async def test_extract_tags_llm_failure_leaves_empty(monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("llm down")

    monkeypatch.setattr(
        "services.knowledge.tag_extractor._llm_extract_tag_values",
        boom,
    )
    result = {
        item["name"]: item
        for item in await extract_tags(
            [{"name": "作者", "type": "text", "hint": ""}],
            "没有日期的正文内容",
            "f.txt",
            db=object(),
        )
    }
    assert result["作者"]["value"] == ""
    assert result["作者"]["source"] == "empty"


def test_add_file_and_documents_expose_tags_in_list_files(ks):
    kb_id = f"kb-{uuid.uuid4().hex[:8]}"
    ks._ensure_index(kb_id)
    added = ks.add_file(
        kb_id,
        LONG_A.encode("utf-8"),
        "采购办法.txt",
        tags={"作者": "法规司", "失效时间": "2027/01/01"},
    )
    ks.add_documents(
        kb_id,
        [{"content": LONG_B, "metadata": {"filename": "过渡安排.txt"}}],
        tags={"发布部门": "法规司"},
    )
    files = {item["filename"]: item for item in ks.list_files(kb_id)}
    assert files["采购办法.txt"]["tags"]["作者"] == "法规司"
    assert files["采购办法.txt"]["tags"]["失效时间"] == "2027/01/01"
    assert files["过渡安排.txt"]["tags"]["发布部门"] == "法规司"
    assert added["chunk_count"] >= 1


def test_index_text_has_tag_line_content_does_not(ks):
    kb_id = f"kb-{uuid.uuid4().hex[:8]}"
    ks._ensure_index(kb_id)
    ks.add_documents(
        kb_id,
        [{"content": LONG_A, "metadata": {"filename": "a.txt"}}],
        tags={"失效时间": "2027/01/01", "作者": "法规司"},
    )
    chunk = ks._chunks[kb_id][0]
    assert chunk["content"] == LONG_A
    assert "标签：" not in chunk["content"]
    assert chunk["index_text"].startswith("标签：失效时间=2027/01/01；作者=法规司")
    assert LONG_A in chunk["index_text"]


def test_preview_missing_raises(ks):
    with pytest.raises(ValueError, match="不存在"):
        ks.load_import_preview("kb-missing", "preview-missing")


def test_save_and_load_import_preview(ks):
    kb_id = f"kb-{uuid.uuid4().hex[:8]}"
    saved = ks.save_import_preview(
        kb_id,
        filename="办法.txt",
        file_bytes="正文".encode("utf-8"),
        text="正文",
        source="paste",
        extracted_tags=[{"name": "作者", "type": "text", "value": "", "source": "empty"}],
    )
    loaded = ks.load_import_preview(kb_id, saved["preview_id"])
    assert loaded["filename"] == "办法.txt"
    assert loaded["text"] == "正文"
    assert loaded["file_bytes"] == "正文".encode("utf-8")
    ks.delete_import_preview(kb_id, saved["preview_id"])
    with pytest.raises(ValueError, match="不存在"):
        ks.load_import_preview(kb_id, saved["preview_id"])


@pytest.mark.asyncio
async def test_import_confirm_missing_preview_404(ks, monkeypatch):
    from fastapi import HTTPException
    from routes import knowledge_bases as kb_routes
    from schemas import KnowledgeImportConfirmRequest

    monkeypatch.setattr(kb_routes, "ks", ks)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = MagicMock()
    with pytest.raises(HTTPException) as err:
        await kb_routes.import_confirm(
            "kb1",
            KnowledgeImportConfirmRequest(preview_id="missing", tags={}),
            db=db,
        )
    assert err.value.status_code == 404


def test_suggest_tag_filters_valid_and_expired():
    valid = suggest_tag_filters_heuristic("现行有效的采购办法", TAG_DEFS)
    assert valid == [{"name": "失效时间", "op": "gte", "value": today_str()}]
    expired = suggest_tag_filters_heuristic("已废止的招标投标法", TAG_DEFS)
    assert expired == [{"name": "失效时间", "op": "lt", "value": today_str()}]


def _seed_tagged_docs(ks):
    kb_id = f"kb-{uuid.uuid4().hex[:8]}"
    ks._ensure_index(kb_id)
    past = (date.today() - timedelta(days=30)).strftime("%Y/%m/%d")
    future = (date.today() + timedelta(days=400)).strftime("%Y/%m/%d")
    legal = ks.add_documents(
        kb_id,
        [{"content": LONG_A, "metadata": {"filename": "法规司.txt"}}],
        tags={"发布部门": "法规司", "失效时间": future},
    )
    finance = ks.add_documents(
        kb_id,
        [{"content": LONG_A, "metadata": {"filename": "财务司.txt"}}],
        tags={"发布部门": "财务司", "失效时间": past},
    )
    untagged = ks.add_documents(
        kb_id,
        [{"content": LONG_B, "metadata": {"filename": "无失效.txt"}}],
        tags={"发布部门": "法规司"},
    )
    assert legal and finance and untagged
    files = {item["filename"]: item["doc_id"] for item in ks.list_files(kb_id)}
    return kb_id, files, past, future


def test_empty_tag_filters_include_expired(ks):
    kb_id, files, _past, _future = _seed_tagged_docs(ks)
    results = ks.search(kb_id, "采购办法", top_k=10)
    doc_ids = {r["metadata"]["doc_id"] for r in results}
    assert files["财务司.txt"] in doc_ids
    assert files["法规司.txt"] in doc_ids


def test_search_filters_by_department_eq(ks):
    kb_id, files, _past, _future = _seed_tagged_docs(ks)
    results = ks.search(
        kb_id,
        "采购办法",
        top_k=10,
        tag_filters=[{"name": "发布部门", "op": "eq", "value": "法规司"}],
        tag_defs=TAG_DEFS,
    )
    assert results
    assert all(r["tags"]["发布部门"] == "法规司" for r in results)
    doc_ids = {r["metadata"]["doc_id"] for r in results}
    assert files["财务司.txt"] not in doc_ids
    assert files["法规司.txt"] in doc_ids


def test_date_gte_keeps_docs_without_expire(ks):
    kb_id, files, _past, _future = _seed_tagged_docs(ks)
    allowed = ks._docs_matching_tag_filters(
        kb_id,
        [{"name": "失效时间", "op": "gte", "value": today_str()}],
        TAG_DEFS,
    )
    assert files["无失效.txt"] in allowed
    assert files["法规司.txt"] in allowed
    assert files["财务司.txt"] not in allowed
    results = ks.search(
        kb_id,
        "采购办法",
        top_k=10,
        tag_filters=[{"name": "失效时间", "op": "gte", "value": today_str()}],
        tag_defs=TAG_DEFS,
    )
    doc_ids = {r["metadata"]["doc_id"] for r in results}
    assert files["无失效.txt"] in doc_ids
    assert files["财务司.txt"] not in doc_ids
