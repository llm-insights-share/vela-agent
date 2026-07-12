"""Tier-2 LLM rewriters: HyDE, multi-hop, memory-anchored."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from services.query_rewrite.types import DialogueContext

HYDE_SYSTEM = """你是检索前置处理器。请针对用户问题生成一段"假设性回答/文档片段"
(不超过150字),尽量覆盖答案可能涉及的实体与术语,但不要声明其为真实答案。

输出要求:仅输出假设文档正文,不要附加解释。"""

MULTI_HOP_SYSTEM = """请将用户问题拆解为若干有依赖顺序的子问题,每个子问题应可被单独
检索或调用工具解答。若子问题之间存在依赖,请显式标注依赖关系。

输出JSON:
{"steps": [
  {"id": 1, "query": "...", "depends_on": []},
  {"id": 2, "query": "...", "depends_on": [1]}
]}

仅输出 JSON，不要附加解释。"""

MEMORY_ANCHOR_SYSTEM = """用户引用了历史内容但表达模糊,请结合当前对话上下文与可用锚点,
将其改写为适合在长期记忆库中检索的具体查询语句。若无法确定具体指向,
请仅输出 NEED_CLARIFICATION,不要编造内容。"""


def _extract_message_content(completion: Dict[str, Any]) -> str:
    choices = completion.get("choices") or []
    if not choices:
        return ""
    msg = choices[0].get("message") or {}
    return (msg.get("content") or "").strip()


def _usage_tokens(completion: Dict[str, Any]) -> int:
    usage = completion.get("usage") or {}
    return int(usage.get("total_tokens") or 0)


def _parse_json_blob(text: str) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


async def _call_llm(
    provider,
    model_svc,
    messages: List[Dict[str, str]],
    *,
    max_tokens: int = 512,
    temperature: float = 0.3,
    timeout_seconds: Optional[float] = 30.0,
) -> Tuple[str, int]:
    from services.model_provider import ModelProviderService

    completion = await ModelProviderService.chat_completion(
        provider=provider,
        model_name=model_svc.model_name,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout_seconds=timeout_seconds,
    )
    return _extract_message_content(completion), _usage_tokens(completion)


async def rewrite_hyde(
    query: str,
    ctx: DialogueContext,
    provider,
    model_svc,
    *,
    timeout_seconds: Optional[float] = 30.0,
) -> Tuple[str, float, int]:
    user = (
        f"用户问题:{query}\n"
        f"对话上下文摘要:{ctx.context_summary or '(无)'}"
    )
    text, tokens = await _call_llm(
        provider,
        model_svc,
        [
            {"role": "system", "content": HYDE_SYSTEM},
            {"role": "user", "content": user},
        ],
        max_tokens=256,
        temperature=0.4,
        timeout_seconds=timeout_seconds,
    )
    if not text:
        return query, 0.0, tokens
    # Downstream retrieval benefits from hypo doc; also keep original intent
    rewritten = f"{query}\n{text}"
    return rewritten, 0.75, tokens


async def rewrite_multi_hop(
    query: str,
    ctx: DialogueContext,
    provider,
    model_svc,
    *,
    timeout_seconds: Optional[float] = 30.0,
) -> Tuple[str, float, int, Optional[List[Dict[str, Any]]]]:
    text, tokens = await _call_llm(
        provider,
        model_svc,
        [
            {"role": "system", "content": MULTI_HOP_SYSTEM},
            {"role": "user", "content": f"用户问题:{query}"},
        ],
        max_tokens=512,
        temperature=0.2,
        timeout_seconds=timeout_seconds,
    )
    data = _parse_json_blob(text)
    steps = (data or {}).get("steps") if isinstance(data, dict) else None
    if not isinstance(steps, list) or not steps:
        return query, 0.0, tokens, None
    normalized = []
    queries = []
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        q = (step.get("query") or "").strip()
        if not q:
            continue
        sid = step.get("id", i + 1)
        deps = step.get("depends_on") or []
        if not isinstance(deps, list):
            deps = []
        normalized.append({"id": sid, "query": q, "depends_on": deps})
        queries.append(q)
    if not queries:
        return query, 0.0, tokens, None
    # Primary downstream query: join independent first-hop queries
    rewritten = "；".join(queries)
    return rewritten, 0.8, tokens, normalized


async def rewrite_memory_anchor(
    query: str,
    ctx: DialogueContext,
    provider,
    model_svc,
    db,
    *,
    timeout_seconds: Optional[float] = 30.0,
) -> Tuple[str, float, int, bool, Optional[str]]:
    """
    Returns (rewritten, confidence, tokens, need_clarification, clarification).
    """
    # Existence probe before LLM invents anchors
    memory_hits: List[str] = []
    if ctx.memory_enabled and db is not None and ctx.agent_id:
        try:
            from services.memory.gateway import MemoryGateway, MemoryQuery

            gw = MemoryGateway(db)
            # Keyword probe with a few tokens from query
            keyword = None
            for token in ("方案", "文档", "报告", "计划", "讨论"):
                if token in query:
                    keyword = token
                    break
            rows = gw.read(
                MemoryQuery(
                    agent_id=ctx.agent_id,
                    user_id=ctx.user_id or "",
                    keyword=keyword,
                    top_k=5,
                )
            )
            if not rows and ctx.user_id:
                rows = gw.read(
                    MemoryQuery(agent_id=ctx.agent_id, user_id="", top_k=5)
                )
            memory_hits = [(r.content or "")[:120] for r in rows if r.content]
        except Exception:
            memory_hits = []

    if ctx.memory_enabled and not memory_hits and not (ctx.context_summary or "").strip():
        return (
            query,
            0.0,
            0,
            True,
            "您提到了历史内容，但我暂时找不到对应记忆。请补充主题、时间或文档名称。",
        )

    anchors = (
        f"时间提示={ctx.time_hint or '未知'};"
        f"主题标签={','.join(ctx.topic_tags) or '未知'};"
        f"用户ID={ctx.user_id or '未知'};"
        f"记忆片段={'; '.join(memory_hits[:3]) or '无'}"
    )
    user = (
        f"模糊引用:{query}\n"
        f"可用锚点:{anchors}\n"
        f"对话上下文:\n{ctx.context_summary or '(无)'}"
    )
    text, tokens = await _call_llm(
        provider,
        model_svc,
        [
            {"role": "system", "content": MEMORY_ANCHOR_SYSTEM},
            {"role": "user", "content": user},
        ],
        max_tokens=256,
        temperature=0.2,
        timeout_seconds=timeout_seconds,
    )
    if not text or "NEED_CLARIFICATION" in text.upper():
        return (
            query,
            0.0,
            tokens,
            True,
            "您提到了历史内容，请补充更具体的主题、时间或名称，以便我准确检索。",
        )
    return text, 0.8, tokens, False, None
