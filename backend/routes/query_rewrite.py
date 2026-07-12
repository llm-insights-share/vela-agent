"""Query rewrite preview / debug API."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Agent, AgentKnowledgeBinding, AgentStatus, ModelProvider, ModelService
from schemas import QueryRewritePreviewRequest, QueryRewritePreviewResponse

router = APIRouter(prefix="/api/v1/query-rewrite", tags=["query-rewrite"])


@router.post("/preview", response_model=QueryRewritePreviewResponse)
async def preview_query_rewrite(
    data: QueryRewritePreviewRequest,
    db: Session = Depends(get_db),
):
    agent = db.query(Agent).filter(Agent.agent_id == data.agent_id).first()
    if not agent or agent.status == AgentStatus.DELETED:
        raise HTTPException(status_code=404, detail="Agent 不存在")

    model_svc = db.query(ModelService).filter(
        ModelService.model_service_id == agent.model_service_id
    ).first()
    provider = None
    if model_svc:
        provider = db.query(ModelProvider).filter(
            ModelProvider.provider_id == model_svc.provider_id
        ).first()

    kb_ids = [
        b.kb_id
        for b in db.query(AgentKnowledgeBinding).filter(
            AgentKnowledgeBinding.agent_id == agent.agent_id
        ).all()
    ]

    from services.query_rewrite import QueryRewriteEngine

    engine = QueryRewriteEngine(db=db, provider=provider, model_svc=model_svc)
    result = await engine.rewrite(
        data.query,
        messages=data.history or [],
        agent_id=agent.agent_id,
        user_id="",
        memory_enabled=bool(getattr(agent, "memory_enabled", False)),
        kb_ids=kb_ids,
    )
    return QueryRewritePreviewResponse(rewrite=result.to_dict())
