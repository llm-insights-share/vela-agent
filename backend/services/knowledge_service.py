import os
import re
import io
import json
import numpy as np
from typing import List, Dict, Any, Optional
import faiss

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


def _parse_pdf(file_bytes: bytes) -> str:
    from PyPDF2 import PdfReader
    reader = PdfReader(io.BytesIO(file_bytes))
    parts = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            parts.append(text.strip())
    return "\n\n".join(parts)


def _parse_docx(file_bytes: bytes) -> str:
    from docx import Document
    doc = Document(io.BytesIO(file_bytes))
    parts = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def _parse_txt(file_bytes: bytes) -> str:
    return file_bytes.decode("utf-8", errors="replace")


def _parse_markdown(file_bytes: bytes) -> str:
    text = file_bytes.decode("utf-8", errors="replace")
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[*_~>|]", "", text)
    return text


PARSERS = {
    ".pdf": _parse_pdf,
    ".docx": _parse_docx,
    ".doc": _parse_docx,
    ".txt": _parse_txt,
    ".md": _parse_markdown,
    ".markdown": _parse_markdown,
}


def chunk_by_paragraph(text: str, target_size: int = 500, min_size: int = 100) -> List[str]:
    raw_paragraphs = re.split(r"\n\s*\n", text)
    paragraphs = [p.strip() for p in raw_paragraphs if p.strip()]
    if not paragraphs:
        return []

    chunks = []
    current = ""

    for para in paragraphs:
        if len(para) >= target_size:
            if current:
                chunks.append(current.strip())
                current = ""
            start = 0
            while start < len(para):
                end = start + target_size
                chunks.append(para[start:end].strip())
                start = end
        elif current and len(current) + len(para) + 2 > target_size:
            chunks.append(current.strip())
            current = para
        else:
            if current:
                current += "\n\n" + para
            else:
                current = para

    if current:
        chunks.append(current.strip())

    result = []
    for chunk in chunks:
        if len(chunk) >= min_size:
            result.append(chunk)

    return result


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
    def __init__(self):
        self._embedding_model = None
        self._indexes: Dict[str, faiss.IndexFlatIP] = {}
        self._chunks: Dict[str, List[Dict[str, Any]]] = {}
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
                        texts = [c["content"] for c in chunks]
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
    ) -> Dict[str, Any]:
        self._ensure_index(kb_id)

        ext = os.path.splitext(filename)[1].lower()
        parser = PARSERS.get(ext)
        if parser is None:
            supported = ", ".join(PARSERS.keys())
            raise ValueError(f"不支持的文件格式 .{ext}，支持: {supported}")

        text = parser(file_bytes)
        if not text or not text.strip():
            raise ValueError("文件内容为空或无法解析")

        chunks = chunk_by_paragraph(text)

        meta = metadata or {}
        meta["filename"] = filename
        meta["file_type"] = ext

        added = self._add_chunks(kb_id, chunks, meta)
        return {"filename": filename, "text_length": len(text), "chunk_count": added}

    def add_documents(self, kb_id: str, documents: List[Dict[str, Any]]) -> int:
        self._ensure_index(kb_id)

        all_chunks = []
        all_meta = []

        for doc in documents:
            content = doc.get("content", "")
            meta = doc.get("metadata", {})
            chunks = chunk_by_paragraph(content)
            all_chunks.extend(chunks)
            all_meta.extend([meta] * len(chunks))

        if not all_chunks:
            return 0

        return self._add_chunks(kb_id, all_chunks, all_meta)

    def _add_chunks(
        self,
        kb_id: str,
        chunks: List[str],
        metadata: Any,
    ) -> int:
        index = self._indexes[kb_id]
        existing = self._chunks[kb_id]
        start_idx = len(existing)

        for i, chunk in enumerate(chunks):
            meta = metadata[i] if isinstance(metadata, list) else metadata
            existing.append({
                "chunk_id": f"chunk-{start_idx + i}",
                "content": chunk,
                "metadata": meta if isinstance(meta, dict) else {},
            })

        embeddings = self.embedding_model.encode(chunks, normalize_embeddings=True)
        embeddings = np.array(embeddings).astype("float32")
        index.add(embeddings)
        self._save(kb_id)

        return len(chunks)

    def search(self, kb_id: str, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        self._ensure_index(kb_id)
        index = self._indexes[kb_id]
        chunks = self._chunks[kb_id]

        if index.ntotal == 0:
            return []

        query_embedding = self.embedding_model.encode([query], normalize_embeddings=True)
        query_embedding = np.array(query_embedding).astype("float32")

        scores, indices = index.search(query_embedding, min(top_k, index.ntotal))

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx >= 0 and idx < len(chunks):
                chunk = chunks[idx]
                results.append({
                    "chunk_id": chunk["chunk_id"],
                    "content": chunk["content"],
                    "score": float(score),
                    "metadata": chunk.get("metadata", {}),
                })

        return results

    def delete_kb(self, kb_id: str):
        if kb_id in self._indexes:
            del self._indexes[kb_id]
        if kb_id in self._chunks:
            del self._chunks[kb_id]
        index_path = self._get_index_path(kb_id)
        chunks_path = self._get_chunks_path(kb_id)
        if os.path.exists(index_path):
            os.remove(index_path)
        if os.path.exists(chunks_path):
            os.remove(chunks_path)

    def list_files(self, kb_id: str) -> List[Dict[str, Any]]:
        self._ensure_index(kb_id)
        chunks = self._chunks[kb_id]

        files: Dict[str, Dict[str, Any]] = {}
        for chunk in chunks:
            meta = chunk.get("metadata", {})
            filename = meta.get("filename", "手动粘贴")
            if filename not in files:
                files[filename] = {
                    "filename": filename,
                    "file_type": meta.get("file_type", ""),
                    "chunk_count": 0,
                    "total_chars": 0,
                    "preview": chunk["content"][:200],
                }
            files[filename]["chunk_count"] += 1
            files[filename]["total_chars"] += len(chunk["content"])

        return list(files.values())

    def get_doc_count(self, kb_id: str) -> int:
        self._ensure_index(kb_id)
        return self._indexes[kb_id].ntotal


knowledge_service = KnowledgeService()