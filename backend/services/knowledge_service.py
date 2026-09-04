import os
import re
import json
import numpy as np
from typing import List, Dict, Any, Optional, Tuple, Set
import faiss

from services.document_parser import (
    PARSERS,
    IMAGE_EXTS,
    chunk_by_paragraph,
    SUPPORTED_EXTENSIONS,
)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
KB_FILES_DIR = os.path.join(DATA_DIR, "kb_files")
PENDING_DIR = os.path.join(DATA_DIR, "kb_pending")
PREVIEW_TTL_SECONDS = 30 * 60


import hashlib
import logging

logger = logging.getLogger(__name__)


class SentenceTransformerEmbedding:
    """使用 sentence-transformers 进行语义嵌入"""

    # 优先使用本地已缓存的模型，避免网络下载
    # 注意：bge-large-zh-v1.5 已在本地缓存，优先使用
    _CANDIDATE_MODELS = [
        "BAAI/bge-large-zh-v1.5",                                          # 中文，1024维，本地已缓存
        "BAAI/bge-small-zh-v1.5",                                          # 中文，512维，体积小
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",     # 多语言，384维
        "sentence-transformers/all-MiniLM-L6-v2",                           # 英文，384维
    ]

    def __init__(self, model_name=None):
        import os
        # 设置离线模式，避免 huggingface.co 不可达时长时间超时
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

        os.environ.setdefault("KMP_INIT_AT_FORK", "FALSE")
        os.environ.setdefault("OMP_NUM_THREADS", "1")
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        from sentence_transformers import SentenceTransformer
        if model_name:
            self._model = SentenceTransformer(model_name)
        else:
            # 依次尝试候选模型，使用第一个能加载的（离线模式，仅用本地缓存）
            last_err = None
            for name in self._CANDIDATE_MODELS:
                try:
                    self._model = SentenceTransformer(name)
                    logger.info(f"成功加载嵌入模型: {name}")
                    break
                except Exception as e:
                    last_err = e
                    logger.warning(f"加载模型 {name} 失败: {e}")
            else:
                raise RuntimeError(f"所有候选模型均加载失败，最后一个错误: {last_err}")
        self._dim = self._model.get_sentence_embedding_dimension()

    def encode(self, texts, normalize_embeddings=True):
        embeddings = self._model.encode(
            texts,
            normalize_embeddings=normalize_embeddings,
            show_progress_bar=False,
        )
        return np.array(embeddings, dtype='float32')

    def get_sentence_embedding_dimension(self):
        return self._dim


class SimpleEmbedding:
    """基于 MD5 哈希的随机向量嵌入（降级方案，无语义理解能力）"""

    def __init__(self, dim=384):
        self.dim = dim

    def encode(self, texts, normalize_embeddings=True):
        vectors = []
        for text in texts:
            h = hashlib.md5(text.encode('utf-8')).digest()
            seed = int.from_bytes(h[:8], 'big') % (2**31)
            rng = np.random.RandomState(seed)
            vec = rng.randn(self.dim).astype('float32')
            if normalize_embeddings:
                norm = np.linalg.norm(vec)
                if norm > 0:
                    vec = vec / norm
            vectors.append(vec)
        return np.array(vectors, dtype='float32')

    def get_sentence_embedding_dimension(self):
        return self.dim


def _create_embedding_model():
    """创建嵌入模型，优先使用 sentence-transformers，失败时降级为 SimpleEmbedding"""
    try:
        model = SentenceTransformerEmbedding()
        logger.info("sentence-transformers 模型加载成功")
        return model
    except Exception as e:
        logger.warning(f"sentence-transformers 加载失败，降级为 SimpleEmbedding: {e}")
        return SimpleEmbedding(dim=384)


class KnowledgeService:
    RRF_K = 60

    def __init__(self):
        self._embedding_model = None
        self._indexes: Dict[str, faiss.IndexFlatIP] = {}
        self._chunks: Dict[str, List[Dict[str, Any]]] = {}
        self._bm25_index: Dict[str, Any] = {}
        self._bm25_row_to_chunk_idx: Dict[str, List[int]] = {}
        os.makedirs(DATA_DIR, exist_ok=True)

    @property
    def embedding_model(self):
        if self._embedding_model is None:
            self._embedding_model = _create_embedding_model()
        return self._embedding_model

    def _get_index_path(self, kb_id: str) -> str:
        return os.path.join(DATA_DIR, f"faiss_{kb_id}.index")

    def _get_chunks_path(self, kb_id: str) -> str:
        return os.path.join(DATA_DIR, f"chunks_{kb_id}.json")

    def _doc_dir(self, kb_id: str, doc_id: str) -> str:
        return os.path.join(KB_FILES_DIR, kb_id, doc_id)

    def _store_file(self, kb_id: str, doc_id: str, filename: str, file_bytes: bytes) -> str:
        doc_dir = self._doc_dir(kb_id, doc_id)
        os.makedirs(doc_dir, exist_ok=True)
        safe_name = os.path.basename(filename) or "file"
        abs_path = os.path.join(doc_dir, safe_name)
        with open(abs_path, "wb") as f:
            f.write(file_bytes)
        return os.path.relpath(abs_path, DATA_DIR).replace("\\", "/")

    def _resolve_stored_path(self, stored_path: str) -> Optional[str]:
        if not stored_path:
            return None
        abs_path = stored_path if os.path.isabs(stored_path) else os.path.join(DATA_DIR, stored_path)
        if os.path.isfile(abs_path):
            return abs_path
        return None

    @staticmethod
    def _is_active(meta: Dict[str, Any]) -> bool:
        return (meta or {}).get("status", "ACTIVE") != "INACTIVE"

    @staticmethod
    def _index_text_for_chunk(chunk: Dict[str, Any]) -> str:
        return chunk.get("index_text") or chunk.get("content") or ""

    def parse_file_to_chunks(self, file_bytes: bytes, filename: str) -> Dict[str, Any]:
        ext = os.path.splitext(filename)[1].lower()
        parser = PARSERS.get(ext)
        if parser is None:
            supported = ", ".join(sorted(PARSERS.keys()))
            raise ValueError(f"不支持的文件格式 {ext or '(无扩展名)'}，支持: {supported}")

        text = parser(file_bytes)
        if ext in IMAGE_EXTS:
            text = f"[图片] {filename}"
        elif not text or not text.strip():
            raise ValueError("文件内容为空或无法解析")

        if ext in IMAGE_EXTS:
            chunks = [text]
        else:
            chunks = chunk_by_paragraph(text)
            if not chunks:
                chunks = [text.strip()] if text and text.strip() else [f"[文件] {filename}"]

        return {
            "text": text,
            "chunks": chunks,
            "ext": ext,
            "is_image": ext in IMAGE_EXTS,
        }

    @staticmethod
    def _legacy_doc_id(filename: str) -> str:
        digest = hashlib.md5(filename.encode("utf-8")).hexdigest()[:12]
        return f"legacy-{digest}"

    def _chunk_doc_id(self, chunk: Dict[str, Any]) -> str:
        meta = chunk.get("metadata") or {}
        filename = meta.get("filename", "手动粘贴")
        return meta.get("doc_id") or self._legacy_doc_id(filename)

    @staticmethod
    def _clean_tags(tags: Optional[Dict[str, Any]]) -> Dict[str, str]:
        cleaned: Dict[str, str] = {}
        for key, value in (tags or {}).items():
            name = str(key or "").strip()
            text = str(value or "").strip()
            if name and text:
                cleaned[name] = text
        return cleaned

    @staticmethod
    def _with_tag_index_texts(
        chunks: List[str],
        index_texts: Optional[List[str]],
        tags: Dict[str, str],
    ) -> Optional[List[str]]:
        from services.knowledge.tag_extractor import apply_tags_to_index_text

        if not tags and index_texts is None:
            return None
        base = index_texts if index_texts is not None else list(chunks)
        if not tags:
            return base
        return [apply_tags_to_index_text(text, tags) for text in base]

    def _match_doc_chunks(self, kb_id: str, doc_id: str) -> List[Dict[str, Any]]:
        self._ensure_index(kb_id)
        chunks = self._chunks[kb_id]
        matched = []
        for chunk in chunks:
            meta = chunk.get("metadata") or {}
            cid = meta.get("doc_id")
            if cid and cid == doc_id:
                matched.append(chunk)
                continue
            if not cid and doc_id.startswith("legacy-"):
                filename = meta.get("filename", "手动粘贴")
                if self._legacy_doc_id(filename) == doc_id:
                    matched.append(chunk)
        return matched

    def _rebuild_index(self, kb_id: str):
        dim = self.embedding_model.get_sentence_embedding_dimension()
        new_index = faiss.IndexFlatIP(dim)
        chunks = self._chunks.get(kb_id) or []
        if chunks:
            texts = [self._index_text_for_chunk(c) for c in chunks]
            embeddings = self.embedding_model.encode(texts, normalize_embeddings=True)
            embeddings = np.array(embeddings).astype("float32")
            new_index.add(embeddings)
        self._indexes[kb_id] = new_index
        self._save(kb_id)
        self._rebuild_bm25(kb_id)

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        import jieba
        return [t.strip() for t in jieba.lcut(text or "") if t and t.strip()]

    def _rebuild_bm25(self, kb_id: str):
        """Build BM25 over ACTIVE chunks only; map BM25 row -> chunk index."""
        import math
        from rank_bm25 import BM25Okapi

        class BM25OkapiSmooth(BM25Okapi):
            """Lucene-style IDF so tiny corpora still yield positive scores."""

            def _calc_idf(self, nd):
                for word, freq in nd.items():
                    self.idf[word] = math.log(
                        1.0 + (self.corpus_size - freq + 0.5) / (freq + 0.5)
                    )

        chunks = self._chunks.get(kb_id) or []
        corpus = []
        row_map: List[int] = []
        for idx, chunk in enumerate(chunks):
            meta = chunk.get("metadata") or {}
            if not self._is_active(meta):
                continue
            tokens = self._tokenize(self._index_text_for_chunk(chunk))
            if not tokens:
                continue
            corpus.append(tokens)
            row_map.append(idx)

        if corpus:
            self._bm25_index[kb_id] = BM25OkapiSmooth(corpus)
            self._bm25_row_to_chunk_idx[kb_id] = row_map
        else:
            self._bm25_index.pop(kb_id, None)
            self._bm25_row_to_chunk_idx[kb_id] = []

    def _ensure_bm25(self, kb_id: str):
        self._ensure_index(kb_id)
        if kb_id not in self._bm25_row_to_chunk_idx:
            self._rebuild_bm25(kb_id)

    def _ensure_index(self, kb_id: str):
        if kb_id not in self._indexes:
            index_path = self._get_index_path(kb_id)
            chunks_path = self._get_chunks_path(kb_id)
            if os.path.exists(index_path) and os.path.exists(chunks_path):
                index = faiss.read_index(index_path)
                with open(chunks_path, "r", encoding="utf-8") as f:
                    self._chunks[kb_id] = json.load(f)
                # 检查索引维度是否与当前嵌入模型一致
                expected_dim = self.embedding_model.get_sentence_embedding_dimension()
                if index.d != expected_dim:
                    logger.warning(
                        f"知识库 {kb_id} 的索引维度({index.d})与当前模型维度({expected_dim})不匹配，"
                        f"将使用已有文本块重建索引"
                    )
                    # 用已有 chunks 重建索引
                    chunks = self._chunks[kb_id]
                    new_index = faiss.IndexFlatIP(expected_dim)
                    if chunks:
                        texts = [self._index_text_for_chunk(c) for c in chunks]
                        embeddings = self.embedding_model.encode(texts, normalize_embeddings=True)
                        embeddings = np.array(embeddings).astype("float32")
                        new_index.add(embeddings)
                    self._indexes[kb_id] = new_index
                    self._save(kb_id)
                else:
                    self._indexes[kb_id] = index
            else:
                dim = self.embedding_model.get_sentence_embedding_dimension()
                self._indexes[kb_id] = faiss.IndexFlatIP(dim)
                self._chunks[kb_id] = []
            self._rebuild_bm25(kb_id)

    def _save(self, kb_id: str):
        if kb_id in self._indexes:
            faiss.write_index(self._indexes[kb_id], self._get_index_path(kb_id))
        if kb_id in self._chunks:
            chunks_path = self._get_chunks_path(kb_id)
            with open(chunks_path, "w", encoding="utf-8") as f:
                json.dump(self._chunks[kb_id], f, ensure_ascii=False, default=str)

    def add_file(
        self,
        kb_id: str,
        file_bytes: bytes,
        filename: str,
        metadata: Optional[Dict[str, Any]] = None,
        prefixes: Optional[List[str]] = None,
        tags: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        import uuid

        self._ensure_index(kb_id)
        parsed = self.parse_file_to_chunks(file_bytes, filename)
        text = parsed["text"]
        chunks = parsed["chunks"]
        ext = parsed["ext"]

        doc_id = uuid.uuid4().hex
        stored_path = self._store_file(kb_id, doc_id, filename, file_bytes)

        meta = dict(metadata or {})
        meta.update({
            "doc_id": doc_id,
            "filename": filename,
            "file_type": ext.lstrip(".") or ext,
            "status": "ACTIVE",
            "source": "upload",
            "stored_path": stored_path,
        })
        clean_tags = self._clean_tags(tags if tags is not None else meta.get("tags"))
        if clean_tags:
            meta["tags"] = clean_tags

        index_texts = None
        if prefixes is not None:
            from services.knowledge.contextualizer import build_index_texts
            index_texts = build_index_texts(chunks, prefixes)
        index_texts = self._with_tag_index_texts(chunks, index_texts, clean_tags)

        added = self._add_chunks(
            kb_id, chunks, meta, index_texts=index_texts, prefixes=prefixes
        )
        return {
            "doc_id": doc_id,
            "filename": filename,
            "text_length": len(text),
            "chunk_count": added,
        }

    def add_documents(
        self,
        kb_id: str,
        documents: List[Dict[str, Any]],
        doc_prefixes: Optional[List[List[str]]] = None,
        tags: Optional[Dict[str, Any]] = None,
    ) -> int:
        import uuid

        self._ensure_index(kb_id)

        all_chunks = []
        all_meta = []
        all_index_texts = []
        all_prefixes = []

        for doc_idx, doc in enumerate(documents):
            content = doc.get("content", "")
            meta = dict(doc.get("metadata") or {})
            doc_id = meta.get("doc_id") or uuid.uuid4().hex
            filename = meta.get("filename") or f"粘贴文本-{doc_id[:8]}.txt"
            stored_path = self._store_file(
                kb_id, doc_id, filename, content.encode("utf-8")
            )
            meta.update({
                "doc_id": doc_id,
                "filename": filename,
                "file_type": meta.get("file_type") or "txt",
                "status": meta.get("status") or "ACTIVE",
                "source": "paste",
                "stored_path": stored_path,
            })
            clean_tags = self._clean_tags(
                tags if tags is not None else meta.get("tags")
            )
            if clean_tags:
                meta["tags"] = clean_tags
            else:
                meta.pop("tags", None)
            chunks = chunk_by_paragraph(content)
            if not chunks and content.strip():
                chunks = [content.strip()]
            prefixes = (
                doc_prefixes[doc_idx]
                if doc_prefixes and doc_idx < len(doc_prefixes)
                else [""] * len(chunks)
            )
            if len(prefixes) != len(chunks):
                prefixes = [""] * len(chunks)
            from services.knowledge.contextualizer import build_index_texts
            index_texts = build_index_texts(chunks, prefixes) if doc_prefixes else None
            index_texts = self._with_tag_index_texts(chunks, index_texts, clean_tags)

            all_chunks.extend(chunks)
            all_meta.extend([dict(meta) for _ in chunks])
            if index_texts is not None:
                all_index_texts.extend(index_texts)
                all_prefixes.extend(prefixes)

        if not all_chunks:
            return 0

        return self._add_chunks(
            kb_id,
            all_chunks,
            all_meta,
            index_texts=all_index_texts if len(all_index_texts) == len(all_chunks) else None,
            prefixes=all_prefixes if doc_prefixes else None,
        )

    def _add_chunks(
        self,
        kb_id: str,
        chunks: List[str],
        metadata: Any,
        index_texts: Optional[List[str]] = None,
        prefixes: Optional[List[str]] = None,
    ) -> int:
        index = self._indexes[kb_id]
        existing = self._chunks[kb_id]
        start_idx = len(existing)

        texts_to_embed: List[str] = []
        for i, chunk in enumerate(chunks):
            meta = metadata[i] if isinstance(metadata, list) else metadata
            meta_copy = dict(meta) if isinstance(meta, dict) else {}
            prefix = ""
            if prefixes is not None and i < len(prefixes):
                prefix = (prefixes[i] or "").strip()
            idx_text = chunk
            if index_texts is not None and i < len(index_texts):
                idx_text = index_texts[i]
            if prefix:
                meta_copy["contextual_prefix"] = prefix
                meta_copy["contextualized"] = True
            elif "contextualized" not in meta_copy:
                meta_copy["contextualized"] = False

            entry: Dict[str, Any] = {
                "chunk_id": f"chunk-{start_idx + i}",
                "content": chunk,
                "metadata": meta_copy,
            }
            if idx_text != chunk:
                entry["index_text"] = idx_text
            existing.append(entry)
            texts_to_embed.append(idx_text)

        embeddings = self.embedding_model.encode(texts_to_embed, normalize_embeddings=True)
        embeddings = np.array(embeddings).astype("float32")
        index.add(embeddings)
        self._save(kb_id)
        self._rebuild_bm25(kb_id)

        return len(chunks)

    def _search_vector(
        self, kb_id: str, query: str, top_n: int,
        allowed_doc_ids: Optional[Set[str]] = None,
    ) -> List[Tuple[str, float]]:
        """Return ordered (chunk_id, vector_score) for ACTIVE chunks."""
        index = self._indexes[kb_id]
        chunks = self._chunks[kb_id]
        if index.ntotal == 0 or top_n <= 0:
            return []

        query_embedding = self.embedding_model.encode([query], normalize_embeddings=True)
        query_embedding = np.array(query_embedding).astype("float32")
        fetch_k = index.ntotal if allowed_doc_ids is not None else min(max(top_n * 5, top_n), index.ntotal)
        scores, indices = index.search(query_embedding, fetch_k)

        out: List[Tuple[str, float]] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(chunks):
                continue
            chunk = chunks[idx]
            meta = chunk.get("metadata") or {}
            if not self._is_active(meta):
                continue
            if allowed_doc_ids is not None and self._chunk_doc_id(chunk) not in allowed_doc_ids:
                continue
            out.append((chunk["chunk_id"], float(score)))
            if len(out) >= top_n:
                break
        return out

    def _search_bm25(
        self, kb_id: str, query: str, top_n: int,
        allowed_doc_ids: Optional[Set[str]] = None,
    ) -> List[Tuple[str, float]]:
        """Return ordered (chunk_id, bm25_score) for ACTIVE chunks."""
        self._ensure_bm25(kb_id)
        bm25 = self._bm25_index.get(kb_id)
        row_map = self._bm25_row_to_chunk_idx.get(kb_id) or []
        if not bm25 or not row_map or top_n <= 0:
            return []

        tokens = self._tokenize(query)
        if not tokens:
            return []

        scores = bm25.get_scores(tokens)
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)

        chunks = self._chunks[kb_id]
        out: List[Tuple[str, float]] = []
        for row_i, score in ranked:
            if score <= 0:
                break
            if row_i < 0 or row_i >= len(row_map):
                continue
            chunk_idx = row_map[row_i]
            if chunk_idx < 0 or chunk_idx >= len(chunks):
                continue
            chunk = chunks[chunk_idx]
            meta = chunk.get("metadata") or {}
            if not self._is_active(meta):
                continue
            if allowed_doc_ids is not None and self._chunk_doc_id(chunk) not in allowed_doc_ids:
                continue
            out.append((chunk["chunk_id"], float(score)))
            if len(out) >= top_n:
                break
        return out

    @staticmethod
    def _rrf_fuse(
        ranked_lists: List[List[Tuple[str, float]]],
        k: int = 60,
    ) -> List[Tuple[str, float, List[str]]]:
        """RRF fuse; returns (chunk_id, rrf_score, sources)."""
        source_names = ["vector", "bm25"]
        scores: Dict[str, float] = {}
        sources: Dict[str, List[str]] = {}
        for list_i, ranked in enumerate(ranked_lists):
            name = source_names[list_i] if list_i < len(source_names) else f"s{list_i}"
            for rank, (chunk_id, _) in enumerate(ranked):
                scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)
                src = sources.setdefault(chunk_id, [])
                if name not in src:
                    src.append(name)
        fused = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [(cid, sc, sources.get(cid, [])) for cid, sc in fused]

    def search(
        self,
        kb_id: str,
        query: str,
        top_k: int = 5,
        mode: str = "hybrid",
        tag_filters: Optional[List[Dict[str, Any]]] = None,
        tag_defs: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        self._ensure_index(kb_id)
        self._ensure_bm25(kb_id)
        chunks = self._chunks[kb_id]
        if not chunks:
            return []

        mode = (mode or "hybrid").lower().strip()
        if mode not in ("hybrid", "vector", "bm25"):
            mode = "hybrid"

        allowed_doc_ids = self._docs_matching_tag_filters(kb_id, tag_filters, tag_defs)
        if allowed_doc_ids is not None and not allowed_doc_ids:
            return []

        n = len(chunks)
        fetch_n = min(max(top_k * 5, top_k), n) if n else top_k
        chunk_by_id = {c["chunk_id"]: c for c in chunks}

        def _pack(chunk_id: str, score: float, sources: List[str]) -> Optional[Dict[str, Any]]:
            chunk = chunk_by_id.get(chunk_id)
            if not chunk:
                return None
            meta = chunk.get("metadata") or {}
            if not self._is_active(meta):
                return None
            if allowed_doc_ids is not None and self._chunk_doc_id(chunk) not in allowed_doc_ids:
                return None
            tags = dict(meta.get("tags") or {})
            return {
                "chunk_id": chunk["chunk_id"],
                "content": chunk["content"],
                "score": float(score),
                "metadata": meta,
                "sources": sources,
                "tags": tags,
            }

        results: List[Dict[str, Any]] = []

        from services.monitor.oi_tracing import mark_span_ok, oi_span, set_span_attrs
        from services.monitor.openinference_attrs import attrs_for_retriever

        with oi_span(
            "retrieve.knowledge",
            attrs_for_retriever(query=query or "", documents=[]),
        ) as span:
            if mode == "vector":
                for cid, sc in self._search_vector(kb_id, query, top_k, allowed_doc_ids):
                    item = _pack(cid, sc, ["vector"])
                    if item:
                        results.append(item)
                set_span_attrs(span, attrs_for_retriever(query=query or "", documents=results))
                mark_span_ok(span)
                return results

            if mode == "bm25":
                for cid, sc in self._search_bm25(kb_id, query, top_k, allowed_doc_ids):
                    item = _pack(cid, sc, ["bm25"])
                    if item:
                        results.append(item)
                if results:
                    scores = [r["score"] for r in results]
                    min_s, max_s = min(scores), max(scores)
                    if max_s == min_s:
                        for r in results:
                            r["score"] = 1.0
                    else:
                        span_score = max_s - min_s
                        for r in results:
                            r["score"] = (r["score"] - min_s) / span_score
                set_span_attrs(span, attrs_for_retriever(query=query or "", documents=results))
                mark_span_ok(span)
                return results

            vec = self._search_vector(kb_id, query, fetch_n, allowed_doc_ids)
            bm = self._search_bm25(kb_id, query, fetch_n, allowed_doc_ids)
            fused = self._rrf_fuse([vec, bm], k=self.RRF_K)
            for cid, sc, srcs in fused:
                item = _pack(cid, sc, srcs)
                if item:
                    results.append(item)
                if len(results) >= top_k:
                    break
            set_span_attrs(span, attrs_for_retriever(query=query or "", documents=results))
            mark_span_ok(span)
            return results

    def _docs_matching_tag_filters(
        self,
        kb_id: str,
        tag_filters: Optional[List[Dict[str, Any]]],
        tag_defs: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Set[str]]:
        from services.knowledge.tag_extractor import (
            document_matches_tag_filters,
            normalize_tag_filters,
        )

        filters = normalize_tag_filters(tag_filters)
        if not filters:
            return None
        allowed: Set[str] = set()
        for chunk in self._chunks.get(kb_id) or []:
            meta = chunk.get("metadata") or {}
            if document_matches_tag_filters(meta.get("tags"), filters, tag_defs):
                allowed.add(self._chunk_doc_id(chunk))
        return allowed

    def delete_kb(self, kb_id: str):
        import shutil

        if kb_id in self._indexes:
            del self._indexes[kb_id]
        if kb_id in self._chunks:
            del self._chunks[kb_id]
        self._bm25_index.pop(kb_id, None)
        self._bm25_row_to_chunk_idx.pop(kb_id, None)
        index_path = self._get_index_path(kb_id)
        chunks_path = self._get_chunks_path(kb_id)
        if os.path.exists(index_path):
            os.remove(index_path)
        if os.path.exists(chunks_path):
            os.remove(chunks_path)
        kb_dir = os.path.join(KB_FILES_DIR, kb_id)
        if os.path.isdir(kb_dir):
            shutil.rmtree(kb_dir, ignore_errors=True)

    def list_files(self, kb_id: str) -> List[Dict[str, Any]]:
        self._ensure_index(kb_id)
        chunks = self._chunks[kb_id]

        files: Dict[str, Dict[str, Any]] = {}
        for chunk in chunks:
            meta = chunk.get("metadata") or {}
            filename = meta.get("filename", "手动粘贴")
            doc_id = meta.get("doc_id") or self._legacy_doc_id(filename)
            if doc_id not in files:
                files[doc_id] = {
                    "doc_id": doc_id,
                    "filename": filename,
                    "file_type": (meta.get("file_type") or "").lstrip("."),
                    "status": meta.get("status") or "ACTIVE",
                    "source": meta.get("source") or (
                        "paste" if str(filename).startswith(("手动粘贴", "粘贴文本")) else "upload"
                    ),
                    "has_file": bool(self._resolve_stored_path(meta.get("stored_path", ""))),
                    "chunk_count": 0,
                    "total_chars": 0,
                    "preview": chunk["content"][:200],
                    "tags": dict(meta.get("tags") or {}),
                }
            files[doc_id]["chunk_count"] += 1
            files[doc_id]["total_chars"] += len(chunk["content"])
            if meta.get("status"):
                files[doc_id]["status"] = meta.get("status")
            if meta.get("tags"):
                files[doc_id]["tags"] = dict(meta.get("tags") or {})

        return list(files.values())

    def set_document_status(self, kb_id: str, doc_id: str, status: str) -> Dict[str, Any]:
        if status not in ("ACTIVE", "INACTIVE"):
            raise ValueError("status 仅支持 ACTIVE 或 INACTIVE")
        matched = self._match_doc_chunks(kb_id, doc_id)
        if not matched:
            raise ValueError("文档不存在")
        for chunk in matched:
            meta = dict(chunk.get("metadata") or {})
            meta["status"] = status
            if not meta.get("doc_id"):
                meta["doc_id"] = doc_id
            chunk["metadata"] = meta
        self._save(kb_id)
        self._rebuild_bm25(kb_id)
        return {"doc_id": doc_id, "status": status, "chunk_count": len(matched)}

    def delete_document(self, kb_id: str, doc_id: str) -> Dict[str, Any]:
        import shutil

        matched = self._match_doc_chunks(kb_id, doc_id)
        if not matched:
            raise ValueError("文档不存在")

        stored_paths = set()
        for chunk in matched:
            meta = chunk.get("metadata") or {}
            if meta.get("stored_path"):
                stored_paths.add(meta["stored_path"])

        matched_ids = {id(c) for c in matched}
        self._chunks[kb_id] = [c for c in self._chunks[kb_id] if id(c) not in matched_ids]
        self._rebuild_index(kb_id)

        for rel in stored_paths:
            abs_path = self._resolve_stored_path(rel)
            if abs_path and os.path.isfile(abs_path):
                try:
                    os.remove(abs_path)
                except OSError:
                    pass
        doc_dir = self._doc_dir(kb_id, doc_id)
        if os.path.isdir(doc_dir):
            shutil.rmtree(doc_dir, ignore_errors=True)

        return {"doc_id": doc_id, "deleted_chunks": len(matched)}

    def get_document_content(self, kb_id: str, doc_id: str) -> Dict[str, Any]:
        matched = self._match_doc_chunks(kb_id, doc_id)
        if not matched:
            raise ValueError("文档不存在")

        meta0 = matched[0].get("metadata") or {}
        filename = meta0.get("filename", "document")
        file_type = (meta0.get("file_type") or "").lstrip(".")
        stored_path = meta0.get("stored_path", "")
        abs_path = self._resolve_stored_path(stored_path)

        if abs_path:
            return {
                "doc_id": doc_id,
                "filename": filename,
                "file_type": file_type,
                "mode": "file",
                "path": abs_path,
            }

        text_join = "\n\n".join(c.get("content", "") for c in matched)
        return {
            "doc_id": doc_id,
            "filename": filename,
            "file_type": file_type or "txt",
            "mode": "text",
            "content": text_join,
        }

    def get_doc_count(self, kb_id: str) -> int:
        """Number of document files (not chunk/vector count)."""
        return len(self.list_files(kb_id))

    def get_chunk_count(self, kb_id: str) -> int:
        self._ensure_index(kb_id)
        return self._indexes[kb_id].ntotal

    @staticmethod
    def _chunk_sort_key(chunk: Dict[str, Any]) -> Tuple[int, str]:
        chunk_id = str(chunk.get("chunk_id") or "")
        match = re.search(r"(\d+)$", chunk_id)
        if match:
            return (int(match.group(1)), chunk_id)
        return (10**9, chunk_id)

    def list_document_chunks(self, kb_id: str, doc_id: str) -> Dict[str, Any]:
        matched = self._match_doc_chunks(kb_id, doc_id)
        if not matched:
            raise ValueError("文档不存在")

        ordered = sorted(matched, key=self._chunk_sort_key)
        meta0 = ordered[0].get("metadata") or {}
        filename = meta0.get("filename", "手动粘贴")
        items = []
        for i, chunk in enumerate(ordered, start=1):
            meta = chunk.get("metadata") or {}
            content = chunk.get("content") or ""
            prefix = (meta.get("contextual_prefix") or "").strip() or None
            items.append({
                "chunk_id": chunk.get("chunk_id") or f"chunk-{i - 1}",
                "index": i,
                "content": content,
                "char_count": len(content),
                "contextual_prefix": prefix,
                "contextualized": bool(meta.get("contextualized")) or bool(prefix),
                "has_index_text": bool(chunk.get("index_text")),
                "status": meta.get("status") or "ACTIVE",
            })
        return {
            "doc_id": doc_id,
            "filename": filename,
            "total": len(items),
            "chunks": items,
        }

    def _document_text_for_doc(
        self, kb_id: str, doc_id: str, doc_chunks: List[Dict[str, Any]]
    ) -> str:
        meta0 = (doc_chunks[0].get("metadata") or {}) if doc_chunks else {}
        stored_path = meta0.get("stored_path", "")
        abs_path = self._resolve_stored_path(stored_path)
        if abs_path and os.path.isfile(abs_path):
            try:
                with open(abs_path, "rb") as f:
                    raw = f.read()
                filename = meta0.get("filename") or os.path.basename(abs_path)
                ext = os.path.splitext(filename)[1].lower()
                parser = PARSERS.get(ext)
                if parser:
                    text = parser(raw)
                    if text and text.strip():
                        return text
            except Exception as exc:
                logger.warning(
                    "[knowledge_service] failed to read stored file for doc %s: %s",
                    doc_id,
                    exc,
                )
        return "\n\n".join(c.get("content", "") for c in doc_chunks)

    async def reindex_contextual(
        self,
        kb_id: str,
        *,
        kb_description: str = "",
        kb_override: Optional[bool] = None,
        db,
    ) -> Dict[str, Any]:
        from services.knowledge.config import (
            is_contextual_retrieval_enabled_for_kb,
            load_contextual_retrieval_config,
        )
        from services.knowledge.contextualizer import build_index_texts, contextualize_chunks

        cfg = load_contextual_retrieval_config()
        if not is_contextual_retrieval_enabled_for_kb(kb_override, cfg):
            raise ValueError("上下文感知检索未启用")

        self._ensure_index(kb_id)
        chunks = self._chunks.get(kb_id) or []
        if not chunks:
            return {"processed_docs": 0, "processed_chunks": 0, "contextualized_count": 0}

        docs: Dict[str, List[Dict[str, Any]]] = {}
        for chunk in chunks:
            meta = chunk.get("metadata") or {}
            doc_id = meta.get("doc_id") or self._legacy_doc_id(meta.get("filename", "手动粘贴"))
            docs.setdefault(doc_id, []).append(chunk)

        processed_chunks = 0

        for doc_id, doc_chunks in docs.items():
            meta0 = doc_chunks[0].get("metadata") or {}
            filename = meta0.get("filename", "")
            document_text = self._document_text_for_doc(kb_id, doc_id, doc_chunks)
            chunk_texts = [c.get("content", "") for c in doc_chunks]
            prefixes = await contextualize_chunks(
                chunk_texts,
                document_text=document_text,
                filename=filename,
                kb_description=kb_description,
                model_service_id=cfg.model_service_id,
                db=db,
                config=cfg,
            )
            index_texts = build_index_texts(chunk_texts, prefixes)
            for chunk, prefix, idx_text in zip(doc_chunks, prefixes, index_texts):
                meta = dict(chunk.get("metadata") or {})
                if prefix:
                    meta["contextual_prefix"] = prefix
                    meta["contextualized"] = True
                else:
                    meta.pop("contextual_prefix", None)
                    meta["contextualized"] = False
                tags = self._clean_tags(meta.get("tags"))
                if tags:
                    meta["tags"] = tags
                    idx_text = self._with_tag_index_texts([chunk.get("content") or ""], [idx_text], tags)[0]
                if idx_text != (chunk.get("content") or ""):
                    chunk["index_text"] = idx_text
                else:
                    chunk.pop("index_text", None)
                chunk["metadata"] = meta
                processed_chunks += 1

        self._rebuild_index(kb_id)
        contextualized_count = sum(
            1
            for c in self._chunks.get(kb_id) or []
            if (c.get("metadata") or {}).get("contextualized")
        )
        return {
            "processed_docs": len(docs),
            "processed_chunks": processed_chunks,
            "contextualized_count": contextualized_count,
        }

    def update_document_tags(
        self, kb_id: str, doc_id: str, tags: Dict[str, Any]
    ) -> Dict[str, Any]:
        from services.knowledge.contextualizer import build_index_texts

        matched = self._match_doc_chunks(kb_id, doc_id)
        if not matched:
            raise ValueError("文档不存在")
        clean_tags = self._clean_tags(tags)
        for chunk in matched:
            meta = dict(chunk.get("metadata") or {})
            if clean_tags:
                meta["tags"] = clean_tags
            else:
                meta.pop("tags", None)
            prefix = (meta.get("contextual_prefix") or "").strip()
            idx_text = build_index_texts([chunk.get("content") or ""], [prefix])[0]
            tagged = self._with_tag_index_texts(
                [chunk.get("content") or ""], [idx_text], clean_tags
            )
            idx_text = tagged[0] if tagged else idx_text
            if idx_text != (chunk.get("content") or ""):
                chunk["index_text"] = idx_text
            else:
                chunk.pop("index_text", None)
            chunk["metadata"] = meta
        self._rebuild_index(kb_id)
        return {"doc_id": doc_id, "tags": clean_tags, "chunk_count": len(matched)}

    def _preview_dir(self, kb_id: str, preview_id: str) -> str:
        return os.path.join(PENDING_DIR, kb_id, preview_id)

    def save_import_preview(
        self,
        kb_id: str,
        *,
        filename: str,
        file_bytes: Optional[bytes],
        text: str,
        source: str,
        extracted_tags: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        import time
        import uuid

        self.cleanup_expired_previews()
        preview_id = uuid.uuid4().hex
        dest = self._preview_dir(kb_id, preview_id)
        os.makedirs(dest, exist_ok=True)
        stored_name = os.path.basename(filename) or "document.txt"
        if file_bytes is None:
            file_bytes = (text or "").encode("utf-8")
        bin_path = os.path.join(dest, stored_name)
        with open(bin_path, "wb") as f:
            f.write(file_bytes)
        meta = {
            "preview_id": preview_id,
            "kb_id": kb_id,
            "filename": filename,
            "source": source,
            "text": text,
            "extracted_tags": extracted_tags,
            "created_at": time.time(),
            "stored_name": stored_name,
        }
        with open(os.path.join(dest, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
        excerpt = (text or "")[:400]
        return {
            "preview_id": preview_id,
            "filename": filename,
            "text_length": len(text or ""),
            "excerpt": excerpt,
            "tags": extracted_tags,
        }

    def load_import_preview(self, kb_id: str, preview_id: str) -> Dict[str, Any]:
        import time

        dest = self._preview_dir(kb_id, preview_id)
        meta_path = os.path.join(dest, "meta.json")
        if not os.path.isfile(meta_path):
            raise ValueError("导入预览不存在或已过期")
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        created = float(meta.get("created_at") or 0)
        if time.time() - created > PREVIEW_TTL_SECONDS:
            self.delete_import_preview(kb_id, preview_id)
            raise ValueError("导入预览不存在或已过期")
        stored_name = meta.get("stored_name") or os.path.basename(meta.get("filename") or "file")
        bin_path = os.path.join(dest, stored_name)
        file_bytes = b""
        if os.path.isfile(bin_path):
            with open(bin_path, "rb") as f:
                file_bytes = f.read()
        meta["file_bytes"] = file_bytes
        return meta

    def delete_import_preview(self, kb_id: str, preview_id: str) -> None:
        import shutil

        dest = self._preview_dir(kb_id, preview_id)
        if os.path.isdir(dest):
            shutil.rmtree(dest, ignore_errors=True)

    def cleanup_expired_previews(self) -> None:
        import time
        import shutil

        if not os.path.isdir(PENDING_DIR):
            return
        now = time.time()
        for kb_id in os.listdir(PENDING_DIR):
            kb_dir = os.path.join(PENDING_DIR, kb_id)
            if not os.path.isdir(kb_dir):
                continue
            for preview_id in os.listdir(kb_dir):
                dest = os.path.join(kb_dir, preview_id)
                meta_path = os.path.join(dest, "meta.json")
                expired = True
                if os.path.isfile(meta_path):
                    try:
                        with open(meta_path, "r", encoding="utf-8") as f:
                            meta = json.load(f)
                        created = float(meta.get("created_at") or 0)
                        expired = now - created > PREVIEW_TTL_SECONDS
                    except Exception:
                        expired = True
                if expired:
                    shutil.rmtree(dest, ignore_errors=True)


knowledge_service = KnowledgeService()
