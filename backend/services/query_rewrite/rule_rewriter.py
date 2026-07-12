"""Tier-1 rule-based rewriters: coreference (CR) and expand/normalize (EX)."""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from services.query_rewrite.judge import (
    COLLOQUIAL_HINTS,
    has_reference,
    is_elliptical,
)
from services.query_rewrite.types import DialogueContext

# Lightweight domain / colloquial expansions (EX)
TERM_EXPAND_MAP = [
    ("猪周期", "生猪养殖周期"),
    ("咋样了", "最新趋势如何"),
    ("咋样", "怎么样"),
    ("咋办", "怎么办"),
    ("啥意思", "是什么意思"),
    ("啥", "什么"),
    ("搞一下", "处理一下"),
    ("整一下", "处理一下"),
    ("A股", "A股市场"),
    ("美股", "美国股市"),
]

PRONOUN_REPLACE_ORDER = (
    "那两个", "这两个", "它们", "他们", "她们", "这个", "那个", "这些", "那些",
    "前者", "后者", "上述", "以上", "它", "他", "她", "该", "其",
    "these", "those", "they", "them", "this", "that", "it",
)


def _pick_entity(ctx: DialogueContext) -> Optional[str]:
    if ctx.entity_slots:
        # Longest slot is usually the full proper noun
        return sorted(ctx.entity_slots, key=len, reverse=True)[0]
    # Fallback: first quoted / long token from last assistant
    text = ctx.last_assistant_text or ctx.last_user_text or ""
    m = re.search(r"[「『\"“]([^」』\"”]{1,40})[」』\"”]", text)
    if m:
        return m.group(1).strip()
    return None


def rewrite_coreference(query: str, ctx: DialogueContext) -> Tuple[str, float]:
    """Replace pronouns / elliptical subjects with recent entity slots."""
    entity = _pick_entity(ctx)
    if not entity:
        return query, 0.0

    rewritten = query
    replaced = False

    if has_reference(query):
        for p in PRONOUN_REPLACE_ORDER:
            if p in rewritten:
                # Prefer whole-word-ish for latin; substring for CJK
                if p.isascii():
                    pattern = re.compile(rf"\b{re.escape(p)}\b", re.IGNORECASE)
                    new_text, n = pattern.subn(entity, rewritten, count=1)
                else:
                    new_text, n = rewritten.replace(p, entity, 1), (1 if p in rewritten else 0)
                if n:
                    rewritten = new_text
                    replaced = True
                    break

    if is_elliptical(query) and entity not in rewritten:
        # Prefix entity for bare questions like "多少钱"
        rewritten = f"{entity}{rewritten}" if not rewritten.startswith(entity) else rewritten
        replaced = True

    if not replaced or rewritten == query:
        return query, 0.0
    return rewritten, 0.85


def rewrite_expand(query: str, ctx: DialogueContext) -> Tuple[str, float]:
    """Synonym / colloquial normalization via dictionary."""
    rewritten = query
    applied = 0
    for src, dst in TERM_EXPAND_MAP:
        if src in rewritten:
            rewritten = rewritten.replace(src, dst)
            applied += 1
    # Mild punctuation cleanup
    rewritten = re.sub(r"[？?]{2,}", "？", rewritten).strip()
    if applied == 0 and not any(h in query for h in COLLOQUIAL_HINTS):
        return query, 0.0
    if rewritten == query:
        return query, 0.0
    return rewritten, 0.8 if applied else 0.5


def rule_rewrite(query: str, ctx: DialogueContext, method: str) -> Tuple[str, float, str]:
    """
    Execute T1 rewrite.
    Returns (rewritten, confidence, method_used).
    """
    if method == "CR":
        text, conf = rewrite_coreference(query, ctx)
        if conf > 0:
            return text, conf, "CR"
        text2, conf2 = rewrite_expand(query, ctx)
        return (text2, conf2, "EX") if conf2 > 0 else (query, 0.0, "CR")

    if method == "EX":
        text, conf = rewrite_expand(query, ctx)
        if conf > 0:
            return text, conf, "EX"
        text2, conf2 = rewrite_coreference(query, ctx)
        return (text2, conf2, "CR") if conf2 > 0 else (query, 0.0, "EX")

    # Auto within T1: try CR then EX
    text, conf = rewrite_coreference(query, ctx)
    if conf > 0:
        return text, conf, "CR"
    text, conf = rewrite_expand(query, ctx)
    if conf > 0:
        return text, conf, "EX"
    return query, 0.0, method or "CR"
