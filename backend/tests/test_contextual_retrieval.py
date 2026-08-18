"""Tests for contextual retrieval in knowledge base pipeline."""

import asyncio
import uuid
from unittest.mock import MagicMock

import pytest

from services.knowledge.config import (
    ContextualRetrievalConfig,
    is_contextual_retrieval_enabled_for_kb,
)
from services.knowledge.contextualizer import build_index_texts, contextualize_chunks


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


def test_build_index_texts_with_prefix():
    chunks = ["chunk one", "chunk two"]
    prefixes = ["doc intro", ""]
    index_texts = build_index_texts(chunks, prefixes)
    assert index_texts[0] == "doc intro\n\nchunk one"
    assert index_texts[1] == "chunk two"


def test_is_contextual_retrieval_enabled_for_kb():
    cfg = ContextualRetrievalConfig(enabled=True)
    assert is_contextual_retrieval_enabled_for_kb(None, cfg) is True
    assert is_contextual_retrieval_enabled_for_kb(True, cfg) is True
    assert is_contextual_retrieval_enabled_for_kb(False, cfg) is False


def test_add_chunks_without_contextual_prefix(ks):
    kb_id = f"kb-{uuid.uuid4().hex[:8]}"
    ks._ensure_index(kb_id)
    count = ks._add_chunks(
        kb_id,
        ["这是一段足够长的测试文本内容，用于验证知识库分块入库逻辑是否正常工作。"],
        {"doc_id": "d1", "filename": "t.txt", "status": "ACTIVE"},
    )
    assert count == 1
    chunk = ks._chunks[kb_id][0]
    assert "index_text" not in chunk
    assert chunk["content"].startswith("这是一段足够长")


def test_add_chunks_with_contextual_prefix(ks):
    kb_id = f"kb-{uuid.uuid4().hex[:8]}"
    ks._ensure_index(kb_id)
    content = "这是一段足够长的测试文本内容，用于验证上下文前缀索引是否正确写入。"
    prefix = "该片段来自一份关于知识库检索优化的技术说明文档。"
    index_texts = build_index_texts([content], [prefix])
    ks._add_chunks(
        kb_id,
        [content],
        {"doc_id": "d1", "filename": "t.txt", "status": "ACTIVE"},
        index_texts=index_texts,
        prefixes=[prefix],
    )
    chunk = ks._chunks[kb_id][0]
    assert chunk["content"] == content
    assert chunk["index_text"] == f"{prefix}\n\n{content}"
    assert chunk["metadata"]["contextualized"] is True
    assert chunk["metadata"]["contextual_prefix"] == prefix


def test_index_text_for_chunk_legacy_compat(ks):
    legacy = {"content": "legacy chunk text here long enough"}
    assert ks._index_text_for_chunk(legacy) == legacy["content"]
    modern = {
        "content": "original",
        "index_text": "prefix\n\noriginal",
    }
    assert ks._index_text_for_chunk(modern) == "prefix\n\noriginal"


def test_search_returns_original_content_not_index_text(ks):
    kb_id = f"kb-{uuid.uuid4().hex[:8]}"
    ks._ensure_index(kb_id)
    content = "向量检索应返回原始分块文本而不是索引拼接文本，便于 Agent 消费。"
    prefix = "该片段讨论检索结果返回策略。"
    index_texts = build_index_texts([content], [prefix])
    ks._add_chunks(
        kb_id,
        [content],
        {"doc_id": "d1", "filename": "t.txt", "status": "ACTIVE"},
        index_texts=index_texts,
        prefixes=[prefix],
    )
    results = ks.search(kb_id, "检索结果返回", top_k=1)
    assert results
    assert results[0]["content"] == content
    assert prefix not in results[0]["content"]


@pytest.mark.asyncio
async def test_contextualize_timeout_degrades(monkeypatch):
    from services.knowledge import contextualizer as ctx_mod

    provider = MagicMock()
    model_svc = MagicMock(model_name="test-model")

    async def slow_call(**kwargs):
        await asyncio.sleep(0.2)
        return {"choices": [{"message": {"content": "prefix"}}]}

    monkeypatch.setattr(ctx_mod, "resolve_model_service", lambda db, mid: (provider, model_svc))
    monkeypatch.setattr(ctx_mod, "_generate_prefix_for_chunk", slow_call)

    cfg = ContextualRetrievalConfig(chunk_timeout_seconds=1, min_chunk_length=10)
    db = MagicMock()
    chunk = "这是一段足够长的测试文本，用于验证超时降级逻辑是否按预期返回空前缀。"
    prefixes = await contextualize_chunks(
        [chunk],
        document_text="full document text for contextual retrieval testing",
        filename="test.txt",
        model_service_id="ms-1",
        db=db,
        config=cfg,
    )
    assert prefixes == [""]


@pytest.mark.asyncio
async def test_reindex_contextual_updates_index_text(ks, monkeypatch):
    kb_id = f"kb-{uuid.uuid4().hex[:8]}"
    ks._ensure_index(kb_id)
    content = "重建索引测试：该段落应在 reindex 后写入上下文前缀并更新 index_text 字段。"
    ks._add_chunks(
        kb_id,
        [content],
        {"doc_id": "d1", "filename": "t.txt", "status": "ACTIVE"},
    )

    async def fake_contextualize(chunks, **kwargs):
        return ["重建后的上下文前缀"] * len(chunks)

    monkeypatch.setattr(
        "services.knowledge.contextualizer.contextualize_chunks",
        fake_contextualize,
    )
    monkeypatch.setattr(
        "services.knowledge.config.load_contextual_retrieval_config",
        lambda: ContextualRetrievalConfig(enabled=True),
    )
    monkeypatch.setattr(
        "services.knowledge.config.is_contextual_retrieval_enabled_for_kb",
        lambda override, cfg: True,
    )

    db = MagicMock()
    result = await ks.reindex_contextual(
        kb_id,
        kb_description="测试知识库",
        kb_override=True,
        db=db,
    )
    chunk = ks._chunks[kb_id][0]
    assert result["processed_chunks"] == 1
    assert result["contextualized_count"] == 1
    assert chunk["metadata"]["contextualized"] is True
    assert "重建后的上下文前缀" in chunk["index_text"]
    assert chunk["content"] == content
