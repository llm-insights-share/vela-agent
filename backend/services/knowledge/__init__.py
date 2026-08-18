"""Knowledge base contextual retrieval helpers."""

from services.knowledge.config import (
    ContextualRetrievalConfig,
    is_contextual_retrieval_enabled_for_kb,
    load_contextual_retrieval_config,
    save_contextual_retrieval_config,
)
from services.knowledge.contextualizer import build_index_texts, contextualize_chunks
from services.knowledge.tag_extractor import (
    apply_tags_to_index_text,
    document_matches_tag_filters,
    extract_tags,
    format_tags_index_line,
    normalize_tag_defs,
    normalize_tag_filters,
    suggest_tag_filters,
    suggest_tag_filters_heuristic,
)

__all__ = [
    "ContextualRetrievalConfig",
    "apply_tags_to_index_text",
    "build_index_texts",
    "contextualize_chunks",
    "document_matches_tag_filters",
    "extract_tags",
    "format_tags_index_line",
    "is_contextual_retrieval_enabled_for_kb",
    "load_contextual_retrieval_config",
    "normalize_tag_defs",
    "normalize_tag_filters",
    "save_contextual_retrieval_config",
    "suggest_tag_filters",
    "suggest_tag_filters_heuristic",
]
