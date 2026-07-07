from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from models import DataQueryExample, DataTermMapping, DataQueryFeedback, DataQueryExecutionLog
from schemas import (
    DataQueryExampleCreate,
    DataQueryExampleResponse,
    DataQueryExampleUpdate,
    DataQueryFeedbackCreate,
    DataQueryFeedbackResponse,
    DataTermMappingCreate,
    DataTermMappingResponse,
    DataTermMappingUpdate,
    PaginatedResponse,
)
from services.dataquery_service import dataquery_service

router = APIRouter(prefix="/api/v1/dataquery-agents/{dq_agent_id}/knowledge", tags=["dataquery-knowledge"])


@router.get("/examples", response_model=PaginatedResponse)
def list_examples(
    dq_agent_id: str,
    datasource_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(DataQueryExample).filter(DataQueryExample.dq_agent_id == dq_agent_id)
    if datasource_id:
        query = query.filter(DataQueryExample.datasource_id == datasource_id)
    total = query.count()
    items = query.order_by(DataQueryExample.updated_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return PaginatedResponse(total=total, page=page, page_size=page_size, items=[
        DataQueryExampleResponse.model_validate(x).model_dump() for x in items
    ])


@router.post("/examples", response_model=DataQueryExampleResponse, status_code=201)
def create_example(dq_agent_id: str, payload: DataQueryExampleCreate, db: Session = Depends(get_db)):
    item = DataQueryExample(dq_agent_id=dq_agent_id, **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return DataQueryExampleResponse.model_validate(item)


@router.put("/examples/{example_id}", response_model=DataQueryExampleResponse)
def update_example(dq_agent_id: str, example_id: str, payload: DataQueryExampleUpdate, db: Session = Depends(get_db)):
    item = db.query(DataQueryExample).filter(
        DataQueryExample.example_id == example_id,
        DataQueryExample.dq_agent_id == dq_agent_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="样例不存在")
    updates = payload.model_dump(exclude_unset=True)
    for k, v in updates.items():
        setattr(item, k, v)
    db.commit()
    db.refresh(item)
    return DataQueryExampleResponse.model_validate(item)


@router.delete("/examples/{example_id}")
def delete_example(dq_agent_id: str, example_id: str, db: Session = Depends(get_db)):
    item = db.query(DataQueryExample).filter(
        DataQueryExample.example_id == example_id,
        DataQueryExample.dq_agent_id == dq_agent_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="样例不存在")
    db.delete(item)
    db.commit()
    return {"success": True}


@router.get("/terms", response_model=PaginatedResponse)
def list_terms(
    dq_agent_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(DataTermMapping).filter(DataTermMapping.dq_agent_id == dq_agent_id)
    total = query.count()
    items = query.order_by(DataTermMapping.priority.asc()).offset((page - 1) * page_size).limit(page_size).all()
    return PaginatedResponse(total=total, page=page, page_size=page_size, items=[
        DataTermMappingResponse.model_validate(x).model_dump() for x in items
    ])


@router.post("/terms", response_model=DataTermMappingResponse, status_code=201)
def create_term(dq_agent_id: str, payload: DataTermMappingCreate, db: Session = Depends(get_db)):
    item = DataTermMapping(dq_agent_id=dq_agent_id, **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return DataTermMappingResponse.model_validate(item)


@router.put("/terms/{term_id}", response_model=DataTermMappingResponse)
def update_term(dq_agent_id: str, term_id: int, payload: DataTermMappingUpdate, db: Session = Depends(get_db)):
    item = db.query(DataTermMapping).filter(
        DataTermMapping.id == term_id,
        DataTermMapping.dq_agent_id == dq_agent_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="术语映射不存在")
    updates = payload.model_dump(exclude_unset=True)
    for k, v in updates.items():
        setattr(item, k, v)
    db.commit()
    db.refresh(item)
    return DataTermMappingResponse.model_validate(item)


@router.delete("/terms/{term_id}")
def delete_term(dq_agent_id: str, term_id: int, db: Session = Depends(get_db)):
    item = db.query(DataTermMapping).filter(
        DataTermMapping.id == term_id,
        DataTermMapping.dq_agent_id == dq_agent_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="术语映射不存在")
    db.delete(item)
    db.commit()
    return {"success": True}


@router.post("/feedback", response_model=DataQueryFeedbackResponse, status_code=201)
def create_feedback(dq_agent_id: str, payload: DataQueryFeedbackCreate, db: Session = Depends(get_db)):
    log = db.query(DataQueryExecutionLog).filter(
        DataQueryExecutionLog.log_id == payload.log_id,
        DataQueryExecutionLog.dq_agent_id == dq_agent_id,
    ).first()
    if not log:
        raise HTTPException(status_code=404, detail="执行日志不存在")
    fb = dataquery_service.add_feedback(db, payload.log_id, payload.rating, payload.comment)
    return DataQueryFeedbackResponse.model_validate(fb)


@router.get("/feedback", response_model=PaginatedResponse)
def list_feedback(
    dq_agent_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(DataQueryFeedback).filter(DataQueryFeedback.dq_agent_id == dq_agent_id)
    total = query.count()
    items = query.order_by(DataQueryFeedback.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return PaginatedResponse(total=total, page=page, page_size=page_size, items=[
        DataQueryFeedbackResponse.model_validate(x).model_dump() for x in items
    ])
