"""Generate contextual prefixes for knowledge-base chunks via LLM."""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from models import ModelProvider, ModelService, ModelServiceStatus, ProviderStatus
from services.knowledge.config import ContextualRetrievalConfig

logger = logging.getLogger(__name__)

CONTEXTUALIZE_PROMPT = """<document>
{document_excerpt}
</document>

Here is the chunk we want to situate within the whole document:
<chunk>
{chunk}
</chunk>

Please give a short succinct context (2-3 sentences, in the same language as the chunk) to situate this chunk within the overall document for the purposes of improving search retrieval of the chunk. Answer only with the succinct context and nothing else."""

IMAGE_PREFIX = "[图片]"


def build_index_texts(chunks: List[str], prefixes: List[str]) -> List[str]:
    """Combine contextual prefixes with original chunks for indexing."""
    index_texts: List[str] = []
    for chunk, prefix in zip(chunks, prefixes):
        prefix = (prefix or "").strip()
        if prefix:
            index_texts.append(f"{prefix}\n\n{chunk}")
        else:
            index_texts.append(chunk)
    return index_texts


def _should_skip_chunk(chunk: str, config: ContextualRetrievalConfig) -> bool:
    text = (chunk or "").strip()
    if len(text) < config.min_chunk_length:
        return True
    if text.startswith(IMAGE_PREFIX):
        return True
    return False


def _document_excerpt(document_text: str, config: ContextualRetrievalConfig) -> str:
    text = (document_text or "").strip()
    if len(text) <= config.document_excerpt_max_chars:
        return text
    return text[: config.document_excerpt_max_chars]


def resolve_model_service(
    db: Session,
    model_service_id: str,
) -> Optional[Tuple[ModelProvider, ModelService]]:
    svc: Optional[ModelService] = None
    if model_service_id:
        svc = (
            db.query(ModelService)
            .filter(ModelService.model_service_id == model_service_id)
            .first()
        )
    if svc is None:
        svc = (
            db.query(ModelService)
            .filter(ModelService.status == ModelServiceStatus.ACTIVE)
            .first()
        )
    if svc is None:
        return None

    provider = (
        db.query(ModelProvider)
        .filter(ModelProvider.provider_id == svc.provider_id)
        .first()
    )
    if provider is None or provider.status != ProviderStatus.ACTIVE:
        return None
    if not (provider.api_key or "").strip():
        logger.warning("[contextualizer] provider %s has empty api_key", provider.provider_code)
        return None
    return provider, svc


def _extract_prefix(completion: dict) -> str:
    choices = completion.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return (message.get("content") or "").strip()


async def _generate_prefix_for_chunk(
    *,
    chunk: str,
    document_excerpt: str,
    filename: str,
    kb_description: str,
    provider: ModelProvider,
    model_svc: ModelService,
    config: ContextualRetrievalConfig,
) -> str:
    from services.model_provider import ModelProviderService

    doc_block = document_excerpt
    if filename:
        doc_block = f"Filename: {filename}\n\n{doc_block}"
    if kb_description:
        doc_block = f"Knowledge base description: {kb_description}\n\n{doc_block}"

    prompt = CONTEXTUALIZE_PROMPT.format(
        document_excerpt=doc_block,
        chunk=chunk,
    )
    messages = [{"role": "user", "content": prompt}]
    completion = await ModelProviderService.chat_completion(
        provider=provider,
        model_name=model_svc.model_name,
        messages=messages,
        max_tokens=config.prefix_max_tokens,
        temperature=config.temperature,
        timeout_seconds=config.chunk_timeout_seconds,
        source="contextual_retrieval",
    )
    return _extract_prefix(completion)


async def contextualize_chunks(
    chunks: List[str],
    *,
    document_text: str,
    filename: str = "",
    kb_description: str = "",
    model_service_id: str,
    db: Session,
    config: ContextualRetrievalConfig,
) -> List[str]:
    """Return contextual prefixes aligned with chunks; failures degrade to empty prefix."""
    if not chunks:
        return []

    resolved = resolve_model_service(db, model_service_id)
    if resolved is None:
        logger.warning("[contextualizer] no usable model service; skipping contextualization")
        return [""] * len(chunks)

    provider, model_svc = resolved
    excerpt = _document_excerpt(document_text, config)
    semaphore = asyncio.Semaphore(config.max_concurrency)
    prefixes: List[str] = [""] * len(chunks)

    async def _one(index: int, chunk: str) -> None:
        if _should_skip_chunk(chunk, config):
            prefixes[index] = ""
            return
        async with semaphore:
            try:
                prefix = await asyncio.wait_for(
                    _generate_prefix_for_chunk(
                        chunk=chunk,
                        document_excerpt=excerpt,
                        filename=filename,
                        kb_description=kb_description,
                        provider=provider,
                        model_svc=model_svc,
                        config=config,
                    ),
                    timeout=config.chunk_timeout_seconds,
                )
                prefixes[index] = (prefix or "").strip()
            except asyncio.TimeoutError:
                logger.warning("[contextualizer] timeout for chunk index=%s", index)
                prefixes[index] = ""
            except Exception as exc:
                logger.warning("[contextualizer] failed for chunk index=%s: %s", index, exc)
                prefixes[index] = ""

    await asyncio.gather(*(_one(i, chunk) for i, chunk in enumerate(chunks)))
    return prefixes
