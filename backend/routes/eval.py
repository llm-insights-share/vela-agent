from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from deps import CurrentUser
from models import (
    AnnotationQueue,
    AnnotationQueueItem,
    EvalCase,
    EvalDataset,
    EvalJob,
    EvalJobResult,
    EvalJudgeEvaluator,
    EvalRuleEvaluator,
    gen_uuid,
)
from schemas import PaginatedResponse
from services.eval.evaluator import (
    add_run_to_dataset,
    batch_import_feedback,
    compare_jobs,
    delete_dataset_cascade,
    run_eval_job,
    serialize_rule_evaluator,
)
from services.eval.judge import serialize_judge_evaluator

router = APIRouter(prefix="/api/v1/eval", tags=["eval"])


def _serialize_dataset(db: Session, d: EvalDataset) -> dict:
    return {
        "dataset_id": d.dataset_id,
        "name": d.name,
        "description": d.description,
        "agent_id": d.agent_id,
        "tags": d.tags or [],
        "case_count": db.query(EvalCase).filter(EvalCase.dataset_id == d.dataset_id).count(),
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


def _get_dataset_or_404(db: Session, dataset_id: str) -> EvalDataset:
    ds = db.query(EvalDataset).filter(EvalDataset.dataset_id == dataset_id).first()
    if not ds:
        raise HTTPException(status_code=404, detail="数据集不存在")
    return ds


@router.get("/datasets")
def list_datasets(
    user: CurrentUser,
    agent_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    q = db.query(EvalDataset).order_by(EvalDataset.created_at.desc())
    if agent_id:
        q = q.filter(EvalDataset.agent_id == agent_id)
    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    items = [_serialize_dataset(db, d) for d in rows]
    return PaginatedResponse(total=total, page=page, page_size=page_size, items=items)


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: str, user: CurrentUser, db: Session = Depends(get_db)):
    return _serialize_dataset(db, _get_dataset_or_404(db, dataset_id))


@router.post("/datasets", status_code=201)
def create_dataset(data: dict, user: CurrentUser, db: Session = Depends(get_db)):
    name = (data.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name 必填")
    if db.query(EvalDataset).filter(EvalDataset.name == name).first():
        raise HTTPException(status_code=400, detail="数据集名称已存在")
    ds = EvalDataset(
        dataset_id=gen_uuid(),
        name=name,
        description=data.get("description") or "",
        agent_id=data.get("agent_id") or "",
        tags=data.get("tags") or [],
    )
    db.add(ds)
    db.commit()
    return {"dataset_id": ds.dataset_id, "name": ds.name}


@router.patch("/datasets/{dataset_id}")
def update_dataset(dataset_id: str, data: dict, user: CurrentUser, db: Session = Depends(get_db)):
    ds = _get_dataset_or_404(db, dataset_id)
    if "name" in data:
        name = (data.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="name 不能为空")
        existing = db.query(EvalDataset).filter(EvalDataset.name == name, EvalDataset.dataset_id != dataset_id).first()
        if existing:
            raise HTTPException(status_code=400, detail="数据集名称已存在")
        ds.name = name
    if "description" in data:
        ds.description = data.get("description") or ""
    if "agent_id" in data:
        ds.agent_id = data.get("agent_id") or ""
    if "tags" in data:
        ds.tags = data.get("tags") or []
    db.add(ds)
    db.commit()
    return _serialize_dataset(db, ds)


@router.delete("/datasets/{dataset_id}")
def remove_dataset(dataset_id: str, user: CurrentUser, db: Session = Depends(get_db)):
    try:
        deleted = delete_dataset_cascade(db, dataset_id)
    except ValueError as e:
        msg = str(e)
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg) from e
        raise HTTPException(status_code=409, detail=msg) from e
    return {"ok": True, **deleted}


@router.get("/datasets/{dataset_id}/cases")
def list_cases(dataset_id: str, user: CurrentUser, db: Session = Depends(get_db)):
    _get_dataset_or_404(db, dataset_id)
    rows = db.query(EvalCase).filter(EvalCase.dataset_id == dataset_id).all()
    return {
        "items": [
            {
                "case_id": c.case_id,
                "input_text": c.input_text,
                "expected_tools": c.expected_tools or [],
                "expected_keywords": c.expected_keywords or [],
                "expected_output": c.expected_output or "",
                "rubric": c.rubric,
                "source_run_id": c.source_run_id,
            }
            for c in rows
        ]
    }


@router.post("/datasets/{dataset_id}/cases", status_code=201)
def create_case(dataset_id: str, data: dict, user: CurrentUser, db: Session = Depends(get_db)):
    _get_dataset_or_404(db, dataset_id)
    case = EvalCase(
        case_id=gen_uuid(),
        dataset_id=dataset_id,
        input_text=data.get("input_text") or "",
        expected_output=data.get("expected_output") or "",
        expected_tools=data.get("expected_tools") or [],
        expected_keywords=data.get("expected_keywords") or [],
        rubric=data.get("rubric") or "",
        source_run_id=data.get("source_run_id") or "",
    )
    db.add(case)
    db.commit()
    return {"case_id": case.case_id}


@router.patch("/datasets/{dataset_id}/cases/{case_id}")
def update_case(
    dataset_id: str,
    case_id: str,
    data: dict,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    _get_dataset_or_404(db, dataset_id)
    case = db.query(EvalCase).filter(EvalCase.case_id == case_id, EvalCase.dataset_id == dataset_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="用例不存在")
    if "input_text" in data:
        case.input_text = data.get("input_text") or ""
    if "expected_output" in data:
        case.expected_output = data.get("expected_output") or ""
    if "expected_tools" in data:
        case.expected_tools = data.get("expected_tools") or []
    if "expected_keywords" in data:
        case.expected_keywords = data.get("expected_keywords") or []
    if "rubric" in data:
        case.rubric = data.get("rubric") or ""
    if "source_run_id" in data:
        case.source_run_id = data.get("source_run_id") or ""
    db.add(case)
    db.commit()
    return {"case_id": case.case_id}


@router.delete("/datasets/{dataset_id}/cases/{case_id}")
def remove_case(dataset_id: str, case_id: str, user: CurrentUser, db: Session = Depends(get_db)):
    _get_dataset_or_404(db, dataset_id)
    case = db.query(EvalCase).filter(EvalCase.case_id == case_id, EvalCase.dataset_id == dataset_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="用例不存在")
    db.delete(case)
    db.commit()
    return {"ok": True}


@router.post("/datasets/{dataset_id}/import-run/{run_id}")
def import_run(dataset_id: str, run_id: str, user: CurrentUser, db: Session = Depends(get_db)):
    try:
        case = add_run_to_dataset(db, dataset_id=dataset_id, run_id=run_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"case_id": case.case_id}


@router.get("/jobs")
def list_jobs(
    user: CurrentUser,
    dataset_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    q = db.query(EvalJob).order_by(EvalJob.created_at.desc())
    if dataset_id:
        q = q.filter(EvalJob.dataset_id == dataset_id)
    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    items = [
        {
            "job_id": j.job_id,
            "dataset_id": j.dataset_id,
            "agent_id": j.agent_id,
            "status": j.status,
            "pass_threshold": j.pass_threshold,
            "run_mode": j.run_mode or "replay",
            "evaluator_id": j.evaluator_id or "",
            "summary": j.summary or {},
            "started_at": j.started_at.isoformat() if j.started_at else None,
            "finished_at": j.finished_at.isoformat() if j.finished_at else None,
            "created_at": j.created_at.isoformat() if j.created_at else None,
        }
        for j in rows
    ]
    return PaginatedResponse(total=total, page=page, page_size=page_size, items=items)


@router.post("/jobs", status_code=201)
def create_job(data: dict, user: CurrentUser, db: Session = Depends(get_db)):
    dataset_id = data.get("dataset_id")
    if not dataset_id:
        raise HTTPException(status_code=400, detail="dataset_id 必填")
    if not db.query(EvalDataset).filter(EvalDataset.dataset_id == dataset_id).first():
        raise HTTPException(status_code=404, detail="数据集不存在")
    job = EvalJob(
        job_id=gen_uuid(),
        dataset_id=dataset_id,
        agent_id=data.get("agent_id") or "",
        pass_threshold=float(data.get("pass_threshold") or 0.8),
        run_mode=data.get("run_mode") or "replay",
        evaluator_id=data.get("evaluator_id") or "",
    )
    db.add(job)
    db.commit()
    return {"job_id": job.job_id}


@router.post("/jobs/{job_id}/run")
def execute_job(job_id: str, user: CurrentUser, db: Session = Depends(get_db)):
    try:
        return run_eval_job(db, job_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/jobs/{job_id}")
def get_job(job_id: str, user: CurrentUser, db: Session = Depends(get_db)):
    job = db.query(EvalJob).filter(EvalJob.job_id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job 不存在")
    results = db.query(EvalJobResult).filter(EvalJobResult.job_id == job_id).all()
    return {
        "job_id": job.job_id,
        "dataset_id": job.dataset_id,
        "agent_id": job.agent_id,
        "status": job.status,
        "pass_threshold": job.pass_threshold,
        "run_mode": job.run_mode or "replay",
        "evaluator_id": job.evaluator_id or "",
        "summary": job.summary or {},
        "results": [
            {
                "result_id": r.result_id,
                "case_id": r.case_id,
                "passed": r.passed,
                "scores": r.scores or {},
                "details": r.details or {},
            }
            for r in results
        ],
    }


@router.get("/jobs/compare")
def compare_eval_jobs(
    user: CurrentUser,
    job_a: str = Query(...),
    job_b: str = Query(...),
    db: Session = Depends(get_db),
):
    try:
        return compare_jobs(db, job_a, job_b)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/datasets/{dataset_id}/import-feedback")
def import_feedback_runs(
    dataset_id: str,
    data: dict,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    _get_dataset_or_404(db, dataset_id)
    try:
        return batch_import_feedback(
            db,
            dataset_id=dataset_id,
            agent_id=data.get("agent_id") or "",
            days=int(data.get("days") or 7),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/evaluators")
def list_evaluators(
    user: CurrentUser,
    agent_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(EvalRuleEvaluator).order_by(EvalRuleEvaluator.created_at.desc())
    if agent_id:
        q = q.filter(EvalRuleEvaluator.agent_id == agent_id)
    return {"items": [serialize_rule_evaluator(ev) for ev in q.all()]}


@router.post("/evaluators", status_code=201)
def create_evaluator(data: dict, user: CurrentUser, db: Session = Depends(get_db)):
    name = (data.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name 必填")
    ev = EvalRuleEvaluator(
        evaluator_id=gen_uuid(),
        name=name,
        agent_id=data.get("agent_id") or "",
        enabled=bool(data.get("enabled", True)),
        rules_json=data.get("rules_json") or {},
    )
    db.add(ev)
    db.commit()
    return serialize_rule_evaluator(ev)


@router.patch("/evaluators/{evaluator_id}")
def update_evaluator(evaluator_id: str, data: dict, user: CurrentUser, db: Session = Depends(get_db)):
    ev = db.query(EvalRuleEvaluator).filter(EvalRuleEvaluator.evaluator_id == evaluator_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Evaluator 不存在")
    if "name" in data:
        ev.name = (data.get("name") or "").strip() or ev.name
    if "agent_id" in data:
        ev.agent_id = data.get("agent_id") or ""
    if "enabled" in data:
        ev.enabled = bool(data.get("enabled"))
    if "rules_json" in data:
        ev.rules_json = data.get("rules_json") or {}
    db.commit()
    return serialize_rule_evaluator(ev)


@router.delete("/evaluators/{evaluator_id}")
def delete_evaluator(evaluator_id: str, user: CurrentUser, db: Session = Depends(get_db)):
    ev = db.query(EvalRuleEvaluator).filter(EvalRuleEvaluator.evaluator_id == evaluator_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Evaluator 不存在")
    db.delete(ev)
    db.commit()
    return {"ok": True}


@router.get("/judge-evaluators")
def list_judge_evaluators(user: CurrentUser, db: Session = Depends(get_db)):
    rows = db.query(EvalJudgeEvaluator).order_by(EvalJudgeEvaluator.created_at.desc()).all()
    return {"items": [serialize_judge_evaluator(r) for r in rows]}


@router.post("/judge-evaluators", status_code=201)
def create_judge_evaluator(data: dict, user: CurrentUser, db: Session = Depends(get_db)):
    name = (data.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name 必填")
    ev = EvalJudgeEvaluator(
        evaluator_id=gen_uuid(),
        name=name,
        agent_id=data.get("agent_id") or "",
        enabled=bool(data.get("enabled", True)),
        sample_rate=float(data.get("sample_rate") or 0.1),
        prompt_template=data.get("prompt_template") or "",
        model_service_id=data.get("model_service_id") or "",
    )
    db.add(ev)
    db.commit()
    return serialize_judge_evaluator(ev)


@router.patch("/judge-evaluators/{evaluator_id}")
def update_judge_evaluator(evaluator_id: str, data: dict, user: CurrentUser, db: Session = Depends(get_db)):
    ev = db.query(EvalJudgeEvaluator).filter(EvalJudgeEvaluator.evaluator_id == evaluator_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Judge evaluator 不存在")
    for key in ("name", "agent_id", "prompt_template", "model_service_id"):
        if key in data:
            setattr(ev, key, data.get(key) or "")
    if "enabled" in data:
        ev.enabled = bool(data.get("enabled"))
    if "sample_rate" in data:
        ev.sample_rate = float(data.get("sample_rate") or 0.1)
    db.commit()
    return serialize_judge_evaluator(ev)


@router.get("/annotation-queues")
def list_annotation_queues(user: CurrentUser, db: Session = Depends(get_db)):
    rows = db.query(AnnotationQueue).order_by(AnnotationQueue.created_at.desc()).all()
    items = []
    for q in rows:
        pending = (
            db.query(AnnotationQueueItem)
            .filter(AnnotationQueueItem.queue_id == q.queue_id, AnnotationQueueItem.status == "pending")
            .count()
        )
        items.append(
            {
                "queue_id": q.queue_id,
                "name": q.name,
                "agent_id": q.agent_id,
                "description": q.description,
                "pending_count": pending,
            }
        )
    return {"items": items}


@router.post("/annotation-queues", status_code=201)
def create_annotation_queue(data: dict, user: CurrentUser, db: Session = Depends(get_db)):
    name = (data.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name 必填")
    q = AnnotationQueue(
        queue_id=gen_uuid(),
        name=name,
        agent_id=data.get("agent_id") or "",
        description=data.get("description") or "",
    )
    db.add(q)
    db.commit()
    return {"queue_id": q.queue_id}


@router.get("/annotation-queues/{queue_id}/items")
def list_annotation_items(queue_id: str, user: CurrentUser, db: Session = Depends(get_db)):
    rows = (
        db.query(AnnotationQueueItem)
        .filter(AnnotationQueueItem.queue_id == queue_id)
        .order_by(AnnotationQueueItem.created_at.desc())
        .all()
    )
    return {
        "items": [
            {
                "item_id": i.item_id,
                "run_id": i.run_id,
                "case_id": i.case_id,
                "status": i.status,
                "expected_output": i.expected_output,
                "notes": i.notes,
            }
            for i in rows
        ]
    }


@router.post("/annotation-queues/{queue_id}/items", status_code=201)
def add_annotation_item(queue_id: str, data: dict, user: CurrentUser, db: Session = Depends(get_db)):
    if not db.query(AnnotationQueue).filter(AnnotationQueue.queue_id == queue_id).first():
        raise HTTPException(status_code=404, detail="队列不存在")
    item = AnnotationQueueItem(
        item_id=gen_uuid(),
        queue_id=queue_id,
        run_id=data.get("run_id") or "",
        case_id=data.get("case_id") or "",
        status="pending",
        expected_output=data.get("expected_output") or "",
        notes=data.get("notes") or "",
    )
    db.add(item)
    db.commit()
    return {"item_id": item.item_id}


@router.patch("/annotation-queues/{queue_id}/items/{item_id}")
def update_annotation_item(
    queue_id: str,
    item_id: str,
    data: dict,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    item = (
        db.query(AnnotationQueueItem)
        .filter(AnnotationQueueItem.queue_id == queue_id, AnnotationQueueItem.item_id == item_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Item 不存在")
    if "status" in data:
        item.status = data.get("status") or item.status
    if "expected_output" in data:
        item.expected_output = data.get("expected_output") or ""
    if "notes" in data:
        item.notes = data.get("notes") or ""
    db.commit()
    return {"ok": True}
