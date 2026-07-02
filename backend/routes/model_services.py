from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from database import get_db
from models import ModelProvider, ModelService, ProviderStatus, ModelServiceStatus, gen_uuid, now_utc
from schemas import (
    ModelProviderCreate, ModelProviderUpdate, ModelProviderResponse,
    ModelServiceCreate, ModelServiceUpdate, ModelServiceResponse,
    SyncModelsRequest, PaginatedResponse
)
from services.model_provider import model_provider_service

router = APIRouter(prefix="/api/v1", tags=["model-services"])


@router.get("/providers", response_model=PaginatedResponse)
def list_providers(
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(ModelProvider)
    if status:
        query = query.filter(ModelProvider.status == status)
    total = query.count()
    providers = query.order_by(ModelProvider.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()
    return PaginatedResponse(
        total=total, page=page, page_size=page_size,
        items=[ModelProviderResponse.model_validate(p) for p in providers]
    )


@router.post("/providers", response_model=ModelProviderResponse, status_code=201)
def create_provider(data: ModelProviderCreate, db: Session = Depends(get_db)):
    existing = db.query(ModelProvider).filter(
        ModelProvider.provider_code == data.provider_code
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="供应商代码已存在")
    provider = ModelProvider(
        provider_id=gen_uuid(),
        provider_code=data.provider_code,
        display_name=data.display_name,
        base_url=data.base_url,
        api_key=data.api_key,
        extra_headers=data.extra_headers,
        timeout_seconds=data.timeout_seconds,
        max_retries=data.max_retries,
    )
    db.add(provider)
    db.commit()
    db.refresh(provider)
    return ModelProviderResponse.model_validate(provider)


@router.get("/providers/{provider_id}", response_model=ModelProviderResponse)
def get_provider(provider_id: str, db: Session = Depends(get_db)):
    provider = db.query(ModelProvider).filter(
        ModelProvider.provider_id == provider_id
    ).first()
    if not provider:
        raise HTTPException(status_code=404, detail="供应商不存在")
    return ModelProviderResponse.model_validate(provider)


@router.put("/providers/{provider_id}", response_model=ModelProviderResponse)
def update_provider(provider_id: str, data: ModelProviderUpdate, db: Session = Depends(get_db)):
    provider = db.query(ModelProvider).filter(
        ModelProvider.provider_id == provider_id
    ).first()
    if not provider:
        raise HTTPException(status_code=404, detail="供应商不存在")
    update_fields = data.model_dump(exclude_unset=True)
    for key, value in update_fields.items():
        if hasattr(provider, key):
            setattr(provider, key, value)
    db.commit()
    db.refresh(provider)
    return ModelProviderResponse.model_validate(provider)


@router.delete("/providers/{provider_id}")
def delete_provider(provider_id: str, db: Session = Depends(get_db)):
    provider = db.query(ModelProvider).filter(
        ModelProvider.provider_id == provider_id
    ).first()
    if not provider:
        raise HTTPException(status_code=404, detail="供应商不存在")
    services = db.query(ModelService).filter(
        ModelService.provider_id == provider_id
    ).count()
    if services > 0:
        raise HTTPException(status_code=400, detail="该供应商下仍有模型服务，请先删除模型服务")
    db.delete(provider)
    db.commit()
    return {"message": "供应商已删除"}


@router.post("/providers/{provider_id}/sync-models")
async def sync_models(provider_id: str, db: Session = Depends(get_db)):
    provider = db.query(ModelProvider).filter(
        ModelProvider.provider_id == provider_id
    ).first()
    if not provider:
        raise HTTPException(status_code=404, detail="供应商不存在")

    models = await model_provider_service.list_models(provider)
    if not models:
        provider.status = ProviderStatus.ERROR
        db.commit()
        raise HTTPException(status_code=502, detail="无法获取模型列表，请检查 base_url 和 api_key 配置")

    provider.status = ProviderStatus.ACTIVE

    for m in models:
        existing = db.query(ModelService).filter(
            ModelService.provider_id == provider_id,
            ModelService.model_name == m["model_name"],
        ).first()
        if existing:
            existing.display_name = m["display_name"]
            existing.max_tokens = m.get("max_tokens", 4096)
            existing.capabilities = m.get("capabilities", ["text"])
            existing.status = ModelServiceStatus.ACTIVE
        else:
            svc = ModelService(
                model_service_id=gen_uuid(),
                provider_id=provider_id,
                model_name=m["model_name"],
                display_name=m["display_name"],
                max_tokens=m.get("max_tokens", 4096),
                capabilities=m.get("capabilities", ["text"]),
            )
            db.add(svc)

    db.commit()
    return {"message": f"同步完成，共 {len(models)} 个模型", "count": len(models)}


@router.get("/model-services", response_model=PaginatedResponse)
def list_model_services(
    provider_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(ModelService)
    if provider_id:
        query = query.filter(ModelService.provider_id == provider_id)
    if status:
        query = query.filter(ModelService.status == status)
    total = query.count()
    services = query.order_by(ModelService.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    items = []
    for s in services:
        provider = db.query(ModelProvider).filter(
            ModelProvider.provider_id == s.provider_id
        ).first()
        d = ModelServiceResponse.model_validate(s).model_dump()
        d["provider_code"] = provider.provider_code if provider else ""
        items.append(d)

    return PaginatedResponse(total=total, page=page, page_size=page_size, items=items)


@router.post("/model-services", response_model=ModelServiceResponse, status_code=201)
def create_model_service(data: ModelServiceCreate, db: Session = Depends(get_db)):
    provider = db.query(ModelProvider).filter(
        ModelProvider.provider_id == data.provider_id
    ).first()
    if not provider:
        raise HTTPException(status_code=400, detail="供应商不存在")

    existing = db.query(ModelService).filter(
        ModelService.provider_id == data.provider_id,
        ModelService.model_name == data.model_name,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="该模型服务已存在")

    svc = ModelService(
        model_service_id=gen_uuid(),
        provider_id=data.provider_id,
        model_name=data.model_name,
        display_name=data.display_name,
        max_tokens=data.max_tokens,
        capabilities=data.capabilities,
    )
    db.add(svc)
    db.commit()
    db.refresh(svc)
    return ModelServiceResponse.model_validate(svc)


@router.put("/model-services/{model_service_id}", response_model=ModelServiceResponse)
def update_model_service(model_service_id: str, data: ModelServiceUpdate, db: Session = Depends(get_db)):
    svc = db.query(ModelService).filter(
        ModelService.model_service_id == model_service_id
    ).first()
    if not svc:
        raise HTTPException(status_code=404, detail="模型服务不存在")
    update_fields = data.model_dump(exclude_unset=True)
    for key, value in update_fields.items():
        if hasattr(svc, key):
            setattr(svc, key, value)
    db.commit()
    db.refresh(svc)
    return ModelServiceResponse.model_validate(svc)


@router.delete("/model-services/{model_service_id}")
def delete_model_service(model_service_id: str, db: Session = Depends(get_db)):
    svc = db.query(ModelService).filter(
        ModelService.model_service_id == model_service_id
    ).first()
    if not svc:
        raise HTTPException(status_code=404, detail="模型服务不存在")

    from models import Agent
    agent_count = db.query(Agent).filter(
        Agent.model_service_id == model_service_id,
        Agent.status != "DELETED"
    ).count()
    if agent_count > 0:
        raise HTTPException(status_code=400, detail=f"有 {agent_count} 个 Agent 正在使用该模型服务，无法删除")

    db.delete(svc)
    db.commit()
    return {"message": "模型服务已删除"}