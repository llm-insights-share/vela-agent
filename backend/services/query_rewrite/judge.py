"""Lightweight rewrite judge: rule signals + optional coherence + conditional probe."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from services.query_rewrite.types import DialogueContext, RewriteDecision

# ---- Tunable thresholds (doc §3.2) ----
W_RULE = 0.55
W_COH = 0.30
W_PROBE = 0.15
TIER0_THRESHOLD = 0.25
TIER1_THRESHOLD = 0.55
RETRIEVAL_CONF_THRESHOLD = 0.55
MIN_TOKENS = 4

PRONOUN_LEXICON = (
    "它", "他", "她", "它们", "他们", "她们",
    "这个", "那个", "这些", "那些", "这俩", "那俩", "那两个", "这两个",
    "前者", "后者", "上述", "以上", "该", "其",
    "it", "this", "that", "these", "those", "they", "them",
)

ELLIPTICAL_PATTERNS = [
    re.compile(r"^(多少钱|多贵|价格|报价|在哪|哪里|怎么样|如何|为何|为什么|啥意思)[\?？!！。.\s]*$"),
    re.compile(r"^(换个|再来|继续|然后呢|还有呢|呢)[\?？!！。.\s]*$"),
    re.compile(r"^(对比一下|比较一下|详细说说|展开讲讲)[\?？!！。.\s]*$"),
]

ENTITY_RE = re.compile(
    r"(?:"
    r"[A-Za-z][A-Za-z0-9_\-]{2,}|"
    r"[A-Za-z0-9]*[\u4e00-\u9fff]{2,12}(?:ETF|基金|公司|股票|方案|报告|项目|产品|系统|平台)"
    r")"
)
NOISE_ENTITY_RE = re.compile(r"[的了吗呢吧着过较可关]")


def extract_entities(text: str) -> List[str]:
    if not text:
        return []
    found: List[str] = []
    for m in QUOTED_RE.finditer(text):
        found.append(m.group(1).strip())
    for m in ENTITY_RE.finditer(text):
        ent = m.group(0).strip()
        if len(ent) < 2:
            continue
        if ent in ("这个", "那个", "什么", "如何", "怎么", "可以", "关注"):
            continue
        # Drop sentence-like fragments
        if NOISE_ENTITY_RE.search(ent) and not ent.endswith(("ETF", "基金", "公司")):
            continue
        # Trim leading colloquial verbs glued to proper nouns
        for prefix in ("可关注", "关注", "看看", "了解"):
            if ent.startswith(prefix) and len(ent) > len(prefix) + 1:
                ent = ent[len(prefix):]
                break
        if ent not in found:
            found.append(ent)
    found.sort(key=lambda x: len(x), reverse=True)
    return found[:20]
QUOTED_RE = re.compile(r"[「『\"“]([^」』\"”]{1,40})[」』\"”]")

FOLLOWUP_HINTS = ("上次", "之前", "那份", "那个方案", "上回", "刚才说的", "前面提到")
MULTI_HOP_HINTS = ("对比", "分别", "以及", "并且", "同时", "比较", "两者", "两家", "vs", "VS")
COLLOQUIAL_HINTS = ("咋样", "咋办", "啥", "咋", "么样", "搞一下", "整一下")


def tokenize_rough(text: str) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []
    # Split CJK chars loosely + latin words
    parts = re.findall(r"[A-Za-z0-9_\-]+|[\u4e00-\u9fff]", text)
    return parts


def has_reference(query: str) -> bool:
    q = query or ""
    for p in PRONOUN_LEXICON:
        if p in q:
            return True
    return False


def is_elliptical(query: str) -> bool:
    q = (query or "").strip()
    if not q:
        return True
    for pat in ELLIPTICAL_PATTERNS:
        if pat.match(q):
            return True
    tokens = tokenize_rough(q)
    # Short question without clear subject
    if len(tokens) <= 3 and q.endswith(("?", "？", "吗", "呢", "嘛")):
        return True
    return False


def has_named_entity(query: str) -> bool:
    return len(extract_entities(query)) > 0


def shares_entity_with_last_turn(query: str, ctx: DialogueContext) -> bool:
    q_ents = set(extract_entities(query))
    if not q_ents or not ctx.entity_slots:
        return False
    slots = set(ctx.entity_slots)
    return bool(q_ents & slots)


def _cosine(a, b) -> float:
    import numpy as np
    a = np.asarray(a, dtype="float32").reshape(-1)
    b = np.asarray(b, dtype="float32").reshape(-1)
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom <= 1e-9:
        return 0.0
    return float(np.dot(a, b) / denom)


def semantic_coherence_gap(query: str, ctx: DialogueContext) -> float:
    """0~1, larger means more rewrite needed. Uses cached-style single encode of last turn."""
    if ctx.turn_index <= 0:
        return 0.0
    ref = (ctx.last_user_text or "") + "\n" + (ctx.last_assistant_text or "")
    ref = ref.strip()
    if not ref or not (query or "").strip():
        return 0.0
    try:
        from services.knowledge_service import _create_embedding_model
        model = _create_embedding_model()
        vecs = model.encode([query, ref[:800]], normalize_embeddings=True)
        sim = _cosine(vecs[0], vecs[1])
        # High similarity with pronouns still needs rewrite; gap focuses on topical drift
        gap = max(0.0, min(1.0, 1.0 - sim))
        return gap
    except Exception:
        return 0.0


def quick_ann_probe(query: str, kb_ids: List[str]) -> float:
    """Return top-1 similarity in [0,1]; 1.0 if probe skipped/unavailable."""
    if not kb_ids:
        return 1.0
    try:
        from services.knowledge_service import knowledge_service as ks
        best = 0.0
        for kb_id in kb_ids[:3]:
            hits = ks.search(kb_id, query, top_k=1)
            if hits:
                score = float(hits[0].get("score", 0) or 0)
                # FAISS inner-product / cosine often already in [-1,1] or [0,1]
                best = max(best, score)
        return best
    except Exception:
        return 1.0


def compute_rule_score(query: str, ctx: DialogueContext) -> Tuple[float, Dict[str, Any]]:
    signals: Dict[str, Any] = {}
    score = 0.0
    ref = has_reference(query)
    ellip = is_elliptical(query)
    short_no_ent = len(tokenize_rough(query)) < MIN_TOKENS and not has_named_entity(query)
    share = ctx.turn_index > 0 and shares_entity_with_last_turn(query, ctx)

    if ref:
        score += 0.4
        signals["has_reference"] = True
    if ellip:
        score += 0.3
        signals["is_elliptical"] = True
    if short_no_ent:
        score += 0.2
        signals["short_no_entity"] = True
    if share:
        score += 0.1
        signals["shares_entity"] = True

    signals["followup_memory"] = any(h in (query or "") for h in FOLLOWUP_HINTS)
    signals["multi_hop"] = any(h in (query or "") for h in MULTI_HOP_HINTS)
    signals["colloquial"] = any(h in (query or "") for h in COLLOQUIAL_HINTS)
    signals["token_count"] = len(tokenize_rough(query))
    return min(1.0, score), signals


def lightweight_judge(query: str, ctx: DialogueContext) -> RewriteDecision:
    rule_score, signals = compute_rule_score(query, ctx)

    coherence_gap = 0.0
    # Only spend embedding cost when rules suggest ambiguity
    if rule_score >= 0.2 or signals.get("has_reference") or signals.get("is_elliptical"):
        coherence_gap = semantic_coherence_gap(query, ctx)

    probe_penalty = 0.0
    if 0.2 <= rule_score < 0.6 and ctx.kb_ids:
        top1 = quick_ann_probe(query, ctx.kb_ids)
        signals["probe_top1"] = top1
        probe_penalty = max(0.0, RETRIEVAL_CONF_THRESHOLD - top1)

    score = W_RULE * rule_score + W_COH * coherence_gap + W_PROBE * probe_penalty

    if score < TIER0_THRESHOLD:
        tier, action = 0, "pass_through"
    elif score < TIER1_THRESHOLD:
        tier, action = 1, "rule_based_rewrite"
    else:
        tier, action = 2, "llm_rewrite"

    return RewriteDecision(
        tier=tier,
        action=action,
        score=score,
        rule_score=rule_score,
        coherence_gap=coherence_gap,
        probe_penalty=probe_penalty,
        signals=signals,
    )


def build_dialogue_context(
    messages: Optional[List[Dict[str, Any]]],
    *,
    agent_id: str = "",
    user_id: str = "",
    memory_enabled: bool = False,
    kb_ids: Optional[List[str]] = None,
) -> DialogueContext:
    history = list(messages or [])
    # Count user turns
    user_turns = [m for m in history if m.get("role") == "user"]
    turn_index = len(user_turns)

    last_user = ""
    last_assistant = ""
    for m in reversed(history):
        role = m.get("role")
        content = (m.get("content") or "") if isinstance(m.get("content"), str) else ""
        if role == "assistant" and not last_assistant:
            last_assistant = content
        elif role == "user" and not last_user:
            last_user = content
        if last_user and last_assistant:
            break

    entity_slots: List[str] = []
    for text in (last_assistant, last_user):
        for ent in extract_entities(text):
            if ent not in entity_slots:
                entity_slots.append(ent)

    summary_parts = []
    for m in history[-6:]:
        role = m.get("role", "")
        content = m.get("content") or ""
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            summary_parts.append(f"{role}: {content[:200]}")
    context_summary = "\n".join(summary_parts)

    return DialogueContext(
        turn_index=turn_index,
        recent_messages=history[-10:],
        entity_slots=entity_slots[:15],
        last_user_text=last_user[:1000],
        last_assistant_text=last_assistant[:1000],
        context_summary=context_summary[:2000],
        agent_id=agent_id,
        user_id=user_id or "",
        memory_enabled=bool(memory_enabled),
        kb_ids=list(kb_ids or []),
    )
