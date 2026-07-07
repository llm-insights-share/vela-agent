from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from models import (
    DataQueryAgent,
    DataQueryDatasourceBinding,
    DataQueryExecutionLog,
    DataQueryQualityStats,
    gen_uuid,
    now_utc,
)
from schemas import (
    DataQueryAgentCreate,
    DataQueryAgentResponse,
    DataQueryAgentUpdate,
    DataQueryDatasourceBindingResponse,
    DataQueryDatasourceUpdateRequest,
    DataQueryTestQueryRequest,
    PaginatedResponse,
)
from services.dataquery_service import dataquery_service

router = APIRouter(prefix="/api/v1/dataquery-agents", tags=["dataquery-agents"])


@router.get("", response_model=PaginatedResponse)
def list_dataquery_agents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(DataQueryAgent)
    if status:
        query = query.filter(DataQueryAgent.status == status)
    total = query.count()
    items = query.order_by(DataQueryAgent.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return PaginatedResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[DataQueryAgentResponse.model_validate(x) for x in items],
    )


@router.post("", response_model=DataQueryAgentResponse, status_code=201)
def create_dataquery_agent(payload: DataQueryAgentCreate, db: Session = Depends(get_db)):
    exists = db.query(DataQueryAgent).filter(DataQueryAgent.name == payload.name).first()
    if exists:
        raise HTTPException(status_code=400, detail="DataQueryAgent 名称已存在")
    item = DataQueryAgent(
        dq_agent_id=gen_uuid(),
        **payload.model_dump(),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return DataQueryAgentResponse.model_validate(item)


@router.get("/{dq_agent_id}", response_model=DataQueryAgentResponse)
def get_dataquery_agent(dq_agent_id: str, db: Session = Depends(get_db)):
    item = db.query(DataQueryAgent).filter(DataQueryAgent.dq_agent_id == dq_agent_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="DataQueryAgent 不存在")
    return DataQueryAgentResponse.model_validate(item)


@router.put("/{dq_agent_id}", response_model=DataQueryAgentResponse)
def update_dataquery_agent(dq_agent_id: str, payload: DataQueryAgentUpdate, db: Session = Depends(get_db)):
    item = db.query(DataQueryAgent).filter(DataQueryAgent.dq_agent_id == dq_agent_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="DataQueryAgent 不存在")
    updates = payload.model_dump(exclude_unset=True)
    for k, v in updates.items():
        if hasattr(item, k):
            setattr(item, k, v)
    item.updated_at = now_utc()
    db.commit()
    db.refresh(item)
    return DataQueryAgentResponse.model_validate(item)


@router.delete("/{dq_agent_id}")
def delete_dataquery_agent(dq_agent_id: str, db: Session = Depends(get_db)):
    item = db.query(DataQueryAgent).filter(DataQueryAgent.dq_agent_id == dq_agent_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="DataQueryAgent 不存在")
    db.delete(item)
    db.commit()
    return {"success": True, "message": "已删除"}


@router.get("/{dq_agent_id}/datasources", response_model=list[DataQueryDatasourceBindingResponse])
def get_datasource_bindings(dq_agent_id: str, db: Session = Depends(get_db)):
    items = db.query(DataQueryDatasourceBinding).filter(
        DataQueryDatasourceBinding.dq_agent_id == dq_agent_id
    ).order_by(DataQueryDatasourceBinding.id.asc()).all()
    return [DataQueryDatasourceBindingResponse.model_validate(x) for x in items]


@router.put("/{dq_agent_id}/datasources", response_model=list[DataQueryDatasourceBindingResponse])
def update_datasource_bindings(
    dq_agent_id: str,
    payload: DataQueryDatasourceUpdateRequest,
    db: Session = Depends(get_db),
):
    exists = db.query(DataQueryAgent).filter(DataQueryAgent.dq_agent_id == dq_agent_id).first()
    if not exists:
        raise HTTPException(status_code=404, detail="DataQueryAgent 不存在")

    db.query(DataQueryDatasourceBinding).filter(
        DataQueryDatasourceBinding.dq_agent_id == dq_agent_id
    ).delete()

    for b in payload.bindings:
        db.add(DataQueryDatasourceBinding(
            dq_agent_id=dq_agent_id,
            **b.model_dump(),
        ))
    db.commit()

    items = db.query(DataQueryDatasourceBinding).filter(
        DataQueryDatasourceBinding.dq_agent_id == dq_agent_id
    ).order_by(DataQueryDatasourceBinding.id.asc()).all()
    return [DataQueryDatasourceBindingResponse.model_validate(x) for x in items]


@router.post("/{dq_agent_id}/test-query")
async def test_query(
    dq_agent_id: str,
    payload: DataQueryTestQueryRequest,
    db: Session = Depends(get_db),
):
    try:
        result = await dataquery_service.query(
            db=db,
            dq_agent_id=dq_agent_id,
            question=payload.question,
            datasource_id=payload.datasource_id,
            top_k=payload.top_k,
            strict_mode=payload.strict_mode,
            return_sql_only=payload.return_sql_only,
            session_id=payload.session_id,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{dq_agent_id}/logs", response_model=PaginatedResponse)
def list_query_logs(
    dq_agent_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(DataQueryExecutionLog).filter(
        DataQueryExecutionLog.dq_agent_id == dq_agent_id
    )
    total = query.count()
    items = query.order_by(DataQueryExecutionLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return PaginatedResponse(total=total, page=page, page_size=page_size, items=[{
        "log_id": x.log_id,
        "question": x.question,
        "normalized_question": x.normalized_question,
        "generated_sql": x.generated_sql,
        "execution_status": x.execution_status.value if x.execution_status else "FAILED",
        "rows": x.rows,
        "duration_ms": x.duration_ms,
        "tokens_used": x.tokens_used,
        "feedback_score": x.feedback_score,
        "created_at": x.created_at,
    } for x in items])


@router.get("/{dq_agent_id}/quality-stats", response_model=PaginatedResponse)
def list_quality_stats(
    dq_agent_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(DataQueryQualityStats).filter(
        DataQueryQualityStats.dq_agent_id == dq_agent_id
    )
    total = query.count()
    items = query.order_by(DataQueryQualityStats.stat_date.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return PaginatedResponse(total=total, page=page, page_size=page_size, items=[{
        "id": x.id,
        "dq_agent_id": x.dq_agent_id,
        "stat_date": x.stat_date,
        "total_queries": x.total_queries,
        "success_queries": x.success_queries,
        "failed_queries": x.failed_queries,
        "avg_duration_ms": x.avg_duration_ms,
        "avg_feedback_score": x.avg_feedback_score,
        "updated_at": x.updated_at,
    } for x in items])
