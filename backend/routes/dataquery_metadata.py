from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from models import DataCodeMapping, DataDictionaryItem
from schemas import (
    DataCodeMappingCreate,
    DataCodeMappingResponse,
    DataCodeMappingUpdate,
    DataQueryDictionaryCreate,
    DataQueryDictionaryResponse,
    DataQueryDictionaryUpdate,
    PaginatedResponse,
)

router = APIRouter(prefix="/api/v1/dataquery-agents/{dq_agent_id}/metadata", tags=["dataquery-metadata"])


@router.get("/dictionary", response_model=PaginatedResponse)
def list_dictionary(
    dq_agent_id: str,
    datasource_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(DataDictionaryItem).filter(DataDictionaryItem.dq_agent_id == dq_agent_id)
    if datasource_id:
        query = query.filter(DataDictionaryItem.datasource_id == datasource_id)
    total = query.count()
    items = query.order_by(DataDictionaryItem.updated_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return PaginatedResponse(total=total, page=page, page_size=page_size, items=[
        DataQueryDictionaryResponse.model_validate(x).model_dump() for x in items
    ])


@router.post("/dictionary", response_model=DataQueryDictionaryResponse, status_code=201)
def create_dictionary(dq_agent_id: str, payload: DataQueryDictionaryCreate, db: Session = Depends(get_db)):
    item = DataDictionaryItem(dq_agent_id=dq_agent_id, **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return DataQueryDictionaryResponse.model_validate(item)


@router.put("/dictionary/{item_id}", response_model=DataQueryDictionaryResponse)
def update_dictionary(dq_agent_id: str, item_id: int, payload: DataQueryDictionaryUpdate, db: Session = Depends(get_db)):
    item = db.query(DataDictionaryItem).filter(
        DataDictionaryItem.id == item_id,
        DataDictionaryItem.dq_agent_id == dq_agent_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="字典项不存在")
    updates = payload.model_dump(exclude_unset=True)
    for k, v in updates.items():
        setattr(item, k, v)
    db.commit()
    db.refresh(item)
    return DataQueryDictionaryResponse.model_validate(item)


@router.delete("/dictionary/{item_id}")
def delete_dictionary(dq_agent_id: str, item_id: int, db: Session = Depends(get_db)):
    item = db.query(DataDictionaryItem).filter(
        DataDictionaryItem.id == item_id,
        DataDictionaryItem.dq_agent_id == dq_agent_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="字典项不存在")
    db.delete(item)
    db.commit()
    return {"success": True}


@router.get("/code-mappings", response_model=PaginatedResponse)
def list_code_mappings(
    dq_agent_id: str,
    datasource_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(DataCodeMapping).filter(DataCodeMapping.dq_agent_id == dq_agent_id)
    if datasource_id:
        query = query.filter(DataCodeMapping.datasource_id == datasource_id)
    total = query.count()
    items = query.order_by(DataCodeMapping.updated_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return PaginatedResponse(total=total, page=page, page_size=page_size, items=[
        DataCodeMappingResponse.model_validate(x).model_dump() for x in items
    ])


@router.post("/code-mappings", response_model=DataCodeMappingResponse, status_code=201)
def create_code_mapping(dq_agent_id: str, payload: DataCodeMappingCreate, db: Session = Depends(get_db)):
    item = DataCodeMapping(dq_agent_id=dq_agent_id, **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return DataCodeMappingResponse.model_validate(item)


@router.put("/code-mappings/{mapping_id}", response_model=DataCodeMappingResponse)
def update_code_mapping(dq_agent_id: str, mapping_id: int, payload: DataCodeMappingUpdate, db: Session = Depends(get_db)):
    item = db.query(DataCodeMapping).filter(
        DataCodeMapping.id == mapping_id,
        DataCodeMapping.dq_agent_id == dq_agent_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="映射项不存在")
    updates = payload.model_dump(exclude_unset=True)
    for k, v in updates.items():
        setattr(item, k, v)
    db.commit()
    db.refresh(item)
    return DataCodeMappingResponse.model_validate(item)


@router.delete("/code-mappings/{mapping_id}")
def delete_code_mapping(dq_agent_id: str, mapping_id: int, db: Session = Depends(get_db)):
    item = db.query(DataCodeMapping).filter(
        DataCodeMapping.id == mapping_id,
        DataCodeMapping.dq_agent_id == dq_agent_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="映射项不存在")
    db.delete(item)
    db.commit()
    return {"success": True}
