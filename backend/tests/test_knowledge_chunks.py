"""Tests for listing document chunks in a knowledge base."""

import uuid

import pytest

from services.knowledge.contextualizer import build_index_texts


@pytest.fixture
def ks(monkeypatch, tmp_path):
    monkeypatch.setattr("services.knowledge_service.DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        "services.knowledge_service.KB_FILES_DIR",
        str(tmp_path / "kb_files"),
    )
    from services.knowledge_service import KnowledgeService, SimpleEmbedding

    monkeypatch.setattr(
        "services.knowledge_service._create_embedding_model",
        lambda: SimpleEmbedding(dim=384),
    )
    return KnowledgeService()


def test_list_document_chunks_returns_count_and_fields(ks):
    kb_id = f"kb-{uuid.uuid4().hex[:8]}"
    ks._ensure_index(kb_id)
    texts = [
        "第一段足够长的测试文本内容，用于验证分块列表序号与字段。",
        "第二段足够长的测试文本内容，用于验证分块列表数量是否正确。",
    ]
    ks._add_chunks(
        kb_id,
        texts,
        {"doc_id": "doc-a", "filename": "采购制度.txt", "status": "ACTIVE"},
    )
    result = ks.list_document_chunks(kb_id, "doc-a")
    assert result["doc_id"] == "doc-a"
    assert result["filename"] == "采购制度.txt"
    assert result["total"] == 2
    assert len(result["chunks"]) == 2
    first = result["chunks"][0]
    assert first["index"] == 1
    assert first["content"] == texts[0]
    assert first["char_count"] == len(texts[0])
    assert first["status"] == "ACTIVE"
    assert first["contextualized"] is False
    assert first["has_index_text"] is False
    assert result["chunks"][1]["index"] == 2


def test_list_document_chunks_includes_contextual_prefix(ks):
    kb_id = f"kb-{uuid.uuid4().hex[:8]}"
    ks._ensure_index(kb_id)
    content = "该段落讨论招标投标法的适用范围，用于验证上下文前缀字段是否正确返回。"
    prefix = "该片段摘自《中华人民共和国招标投标法》。"
    ks._add_chunks(
        kb_id,
        [content],
        {"doc_id": "doc-b", "filename": "招标投标法.pdf", "status": "ACTIVE"},
        index_texts=build_index_texts([content], [prefix]),
        prefixes=[prefix],
    )
    result = ks.list_document_chunks(kb_id, "doc-b")
    item = result["chunks"][0]
    assert item["contextualized"] is True
    assert item["contextual_prefix"] == prefix
    assert item["has_index_text"] is True
    assert item["content"] == content


def test_list_document_chunks_missing_doc_raises(ks):
    kb_id = f"kb-{uuid.uuid4().hex[:8]}"
    ks._ensure_index(kb_id)
    with pytest.raises(ValueError, match="文档不存在"):
        ks.list_document_chunks(kb_id, "missing-doc")
