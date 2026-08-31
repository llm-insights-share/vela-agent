"""Keyword / BM25 search over tool catalog."""
from __future__ import annotations

import math
import re
from typing import List, Optional, Set

from services.tool_search.catalog import ToolCatalog, ToolCatalogEntry

_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


def _tokenize(text: str) -> List[str]:
    return _TOKEN_RE.findall((text or "").lower())


def _keyword_score(query_tokens: List[str], doc: str) -> float:
    if not query_tokens:
        return 0.0
    doc_l = (doc or "").lower()
    score = 0.0
    for tok in query_tokens:
        if tok in doc_l:
            score += 1.0 + doc_l.count(tok) * 0.1
    return score


class _SimpleBM25:
    def __init__(self, docs: List[str], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.docs = docs
        self.doc_tokens = [_tokenize(d) for d in docs]
        self.doc_len = [len(t) for t in self.doc_tokens]
        self.avgdl = sum(self.doc_len) / len(self.doc_len) if self.doc_len else 0.0
        self.df: dict[str, int] = {}
        for tokens in self.doc_tokens:
            for t in set(tokens):
                self.df[t] = self.df.get(t, 0) + 1
        self.n = len(docs)

    def score(self, query: str, idx: int) -> float:
        q_tokens = _tokenize(query)
        if not q_tokens or idx >= len(self.doc_tokens):
            return 0.0
        doc_toks = self.doc_tokens[idx]
        if not doc_toks:
            return 0.0
        dl = self.doc_len[idx]
        tf_map: dict[str, int] = {}
        for t in doc_toks:
            tf_map[t] = tf_map.get(t, 0) + 1
        total = 0.0
        for qt in q_tokens:
            tf = tf_map.get(qt, 0)
            if tf == 0:
                continue
            df = self.df.get(qt, 0)
            idf = math.log(1 + (self.n - df + 0.5) / (df + 0.5))
            denom = tf + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1))
            total += idf * (tf * (self.k1 + 1)) / (denom or 1)
        return total


def search_tools(
    catalog: ToolCatalog,
    query: str,
    *,
    max_results: int = 5,
    backend: str = "bm25",
    tool_types: Optional[List[str]] = None,
    searchable_names: Optional[Set[str]] = None,
) -> List[ToolCatalogEntry]:
    q = (query or "").strip()
    if not q:
        return []

    entries = catalog.entries
    if searchable_names is not None:
        entries = [e for e in entries if e.name in searchable_names]
    if tool_types:
        allowed = {str(t).lower() for t in tool_types}
        entries = [e for e in entries if (e.tool_type or "").lower() in allowed]
    if not entries:
        return []

    docs = [e.document_text() for e in entries]
    if backend == "keyword":
        q_tokens = _tokenize(q)
        scored = [( _keyword_score(q_tokens, d), i) for i, d in enumerate(docs)]
    else:
        bm25 = _SimpleBM25(docs)
        scored = [(bm25.score(q, i), i) for i in range(len(docs))]

    scored.sort(key=lambda x: x[0], reverse=True)
    out: List[ToolCatalogEntry] = []
    for score, idx in scored:
        if score <= 0:
            continue
        out.append(entries[idx])
        if len(out) >= max_results:
            break
    return out
