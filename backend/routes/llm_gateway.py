"""OpenAI-compatible LLM gateway for Letta.

Exposes /llm-gateway/v1/{models,chat/completions,embeddings} so a self-hosted
Letta server can reuse vela's ModelService providers and the same sentence-
transformers embedding model as the knowledge base.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Union

import httpx
import yaml
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models import ModelProvider, ModelService, ModelServiceStatus

router = APIRouter(prefix="/llm-gateway/v1", tags=["llm-gateway"])

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "vela.yaml")
EMBEDDING_MODEL_ID = "vela-embedding"


def _load_letta_cfg() -> dict:
    if not os.path.isfile(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    return (cfg.get("memory") or {}).get("letta") or {}


def _expected_token() -> str:
    cfg = _load_letta_cfg()
    return (
        os.getenv("VELA_LLM_GATEWAY_TOKEN")
        or cfg.get("gateway_token")
        or "vela-local-gateway"
    )


def require_gateway_token(authorization: Optional[str] = Header(None)):
    expected = _expected_token()
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or token.strip() != expected:
        raise HTTPException(status_code=401, detail="Invalid gateway token")
    return token.strip()


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[Dict[str, Any]] = Field(default_factory=list)
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    tools: Optional[List[Dict[str, Any]]] = None
    tool_choice: Optional[Any] = None
    stream: bool = False
    # Allow extra OpenAI fields Letta may send
    model_config = {"extra": "allow"}


class EmbeddingRequest(BaseModel):
    model: str = EMBEDDING_MODEL_ID
    input: Union[str, List[str]]
    encoding_format: Optional[str] = "float"
    model_config = {"extra": "allow"}


def _resolve_model_service(db: Session, model_name: str) -> tuple[ModelService, ModelProvider]:
    svc = (
        db.query(ModelService)
        .filter(
            ModelService.model_name == model_name,
            ModelService.status == ModelServiceStatus.ACTIVE,
        )
        .first()
    )
    if not svc:
        # Fallback: match by model_service_id or display_name
        svc = (
            db.query(ModelService)
            .filter(ModelService.model_service_id == model_name)
            .first()
        )
    if not svc:
        raise HTTPException(status_code=404, detail=f"Model not found: {model_name}")
    provider = (
        db.query(ModelProvider)
        .filter(ModelProvider.provider_id == svc.provider_id)
        .first()
    )
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider missing for model: {model_name}")
    return svc, provider


@router.get("/models")
def list_models(
    db: Session = Depends(get_db),
    _token: str = Depends(require_gateway_token),
):
    services = (
        db.query(ModelService)
        .filter(ModelService.status == ModelServiceStatus.ACTIVE)
        .all()
    )
    data = [
        {
            "id": s.model_name,
            "object": "model",
            "created": 0,
            "owned_by": "vela",
        }
        for s in services
    ]
    data.append(
        {
            "id": EMBEDDING_MODEL_ID,
            "object": "model",
            "created": 0,
            "owned_by": "vela",
        }
    )
    return {"object": "list", "data": data}


def _ensure_reasoning_content(messages: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], int]:
    """Letta does not replay thinking traces; DeepSeek thinking mode 400s without them."""
    patched = 0
    out: List[Dict[str, Any]] = []
    for m in messages or []:
        if not isinstance(m, dict):
            out.append(m)
            continue
        msg = dict(m)
        if msg.get("role") == "assistant":
            rc = msg.get("reasoning_content") or msg.get("thinking")
            if not (isinstance(rc, str) and rc.strip()):
                msg["reasoning_content"] = " "
                patched += 1
            elif not msg.get("reasoning_content"):
                msg["reasoning_content"] = rc
        out.append(msg)
    return out, patched


@router.post("/chat/completions")
async def chat_completions(
    request: Request,
    db: Session = Depends(get_db),
    _token: str = Depends(require_gateway_token),
):
    body = await request.json()
    model_name = body.get("model") or ""
    if not model_name:
        raise HTTPException(status_code=400, detail="model is required")

    svc, provider = _resolve_model_service(db, model_name)
    # Forward the model name the upstream provider expects
    forward_body = dict(body)
    forward_body["model"] = svc.model_name
    msgs, patched_n = _ensure_reasoning_content(forward_body.get("messages") or [])
    forward_body["messages"] = msgs
    # #region agent log
    try:
        import json as _j, time as _t
        with open("/Users/zhangjr/apps/LlmDemo/vibe-project/vela-agent/.cursor/debug-5cb12e.log", "a") as _f:
            _f.write(_j.dumps({"sessionId":"5cb12e","runId":"post-fix","hypothesisId":"H2","location":"llm_gateway.py:chat_completions","message":"sanitized reasoning_content","data":{"model":forward_body.get("model"),"n_messages":len(msgs),"patched":patched_n},"timestamp":int(_t.time()*1000)},ensure_ascii=False)+"\n")
    except Exception:
        pass
    # #endregion

    headers = {
        "Authorization": f"Bearer {provider.api_key}",
        "Content-Type": "application/json",
    }
    if provider.extra_headers:
        headers.update(provider.extra_headers)

    url = provider.base_url.rstrip("/") + "/chat/completions"
    stream = bool(forward_body.get("stream"))
    read_timeout = float(provider.timeout_seconds or 120)
    timeout = httpx.Timeout(connect=10.0, read=read_timeout, write=30.0, pool=10.0)

    if stream:
        async def _proxy_stream():
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST", url, headers=headers, json=forward_body
                ) as resp:
                    if resp.status_code >= 400:
                        detail = await resp.aread()
                        raise HTTPException(
                            status_code=resp.status_code,
                            detail=detail.decode("utf-8", errors="replace")[:1000],
                        )
                    async for chunk in resp.aiter_bytes():
                        yield chunk

        return StreamingResponse(_proxy_stream(), media_type="text/event-stream")

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.post(url, headers=headers, json=forward_body)
            if resp.status_code >= 400:
                # #region agent log
                try:
                    import json as _j, time as _t
                    msgs = forward_body.get("messages") or []
                    roles = [m.get("role") for m in msgs if isinstance(m, dict)]
                    has_rc = any(isinstance(m, dict) and m.get("reasoning_content") for m in msgs)
                    with open("/Users/zhangjr/apps/LlmDemo/vibe-project/vela-agent/.cursor/debug-5cb12e.log", "a") as _f:
                        _f.write(_j.dumps({"sessionId":"5cb12e","runId":"pre-fix","hypothesisId":"H2","location":"llm_gateway.py:chat_completions","message":"upstream 400","data":{"status":resp.status_code,"model":forward_body.get("model"),"n_messages":len(msgs),"roles":roles[-6:],"has_reasoning_content":has_rc,"err":(resp.text or "")[:220]},"timestamp":int(_t.time()*1000)},ensure_ascii=False)+"\n")
                except Exception:
                    pass
                # #endregion
                return JSONResponse(
                    status_code=resp.status_code,
                    content={"error": {"message": resp.text[:1000], "type": "upstream_error"}},
                )
            return resp.json()
        except httpx.ReadTimeout:
            raise HTTPException(status_code=504, detail=f"Upstream model timeout ({read_timeout}s)")
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Upstream error: {e}")


@router.post("/embeddings")
def create_embeddings(
    body: EmbeddingRequest,
    _token: str = Depends(require_gateway_token),
):
    from services.knowledge_service import knowledge_service

    texts = body.input if isinstance(body.input, list) else [body.input]
    if not texts:
        raise HTTPException(status_code=400, detail="input is required")

    try:
        vectors = knowledge_service.embedding_model.encode(
            texts, normalize_embeddings=True
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding failed: {e}")

    data = []
    for i, vec in enumerate(vectors):
        data.append(
            {
                "object": "embedding",
                "index": i,
                "embedding": vec.tolist() if hasattr(vec, "tolist") else list(vec),
            }
        )

    # Rough token estimate
    total_tokens = sum(max(1, len(t) // 2) for t in texts)
    return {
        "object": "list",
        "data": data,
        "model": EMBEDDING_MODEL_ID,
        "usage": {"prompt_tokens": total_tokens, "total_tokens": total_tokens},
    }
