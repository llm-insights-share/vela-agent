from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from database import get_db
from models import Tool, ToolType, ToolStatus, gen_uuid, now_utc
from schemas import ToolCreate, ToolUpdate, ToolResponse, ToolTestRequest, McpDiscoverRequest, PaginatedResponse
from services.tool_service import tool_execution_service
from services.builtin_tools import BUILTIN_TOOLS

router = APIRouter(prefix="/api/v1/tools", tags=["tools"])


@router.get("/builtin")
def list_builtin_tools():
    items = []
    for t in BUILTIN_TOOLS:
        items.append({
            "tool_id": f"builtin_{t.name}",
            "name": t.name,
            "display_name": t.name,
            "description": t.description,
            "tool_type": "builtin",
            "config": {},
            "parameters_schema": t.parameters,
            "status": "ACTIVE",
        })
    return {"items": items, "total": len(items)}


@router.get("", response_model=PaginatedResponse)
def list_tools(
    tool_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(Tool)
    if tool_type:
        query = query.filter(Tool.tool_type == tool_type)
    if status:
        query = query.filter(Tool.status == status)
    total = query.count()
    tools = query.order_by(Tool.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()
    return PaginatedResponse(
        total=total, page=page, page_size=page_size,
        items=[ToolResponse.model_validate(t) for t in tools]
    )


@router.post("", response_model=ToolResponse, status_code=201)
def create_tool(data: ToolCreate, db: Session = Depends(get_db)):
    existing = db.query(Tool).filter(Tool.name == data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="工具名称已存在")

    tool = Tool(
        tool_id=gen_uuid(),
        name=data.name,
        display_name=data.display_name or data.name,
        description=data.description,
        tool_type=ToolType(data.tool_type),
        config=data.config,
        parameters_schema=data.parameters_schema,
    )
    db.add(tool)
    db.commit()
    db.refresh(tool)
    return ToolResponse.model_validate(tool)


@router.get("/{tool_id}", response_model=ToolResponse)
def get_tool(tool_id: str, db: Session = Depends(get_db)):
    tool = db.query(Tool).filter(Tool.tool_id == tool_id).first()
    if not tool:
        raise HTTPException(status_code=404, detail="工具不存在")
    return ToolResponse.model_validate(tool)


@router.put("/{tool_id}", response_model=ToolResponse)
def update_tool(tool_id: str, data: ToolUpdate, db: Session = Depends(get_db)):
    tool = db.query(Tool).filter(Tool.tool_id == tool_id).first()
    if not tool:
        raise HTTPException(status_code=404, detail="工具不存在")

    update_fields = data.model_dump(exclude_unset=True)
    for key, value in update_fields.items():
        if hasattr(tool, key):
            setattr(tool, key, value)
    tool.updated_at = now_utc()
    db.commit()
    db.refresh(tool)
    return ToolResponse.model_validate(tool)


@router.delete("/{tool_id}")
def delete_tool(tool_id: str, db: Session = Depends(get_db)):
    tool = db.query(Tool).filter(Tool.tool_id == tool_id).first()
    if not tool:
        raise HTTPException(status_code=404, detail="工具不存在")
    db.delete(tool)
    db.commit()
    return {"message": "工具已删除"}


@router.post("/{tool_id}/test")
async def test_tool(tool_id: str, data: ToolTestRequest, db: Session = Depends(get_db)):
    tool = db.query(Tool).filter(Tool.tool_id == tool_id).first()
    if not tool:
        raise HTTPException(status_code=404, detail="工具不存在")

    result = await tool_execution_service.execute_tool(tool, data.parameters)
    return result


@router.post("/mcp/discover")
async def discover_mcp_tools(data: McpDiscoverRequest):
    result = await tool_execution_service.discover_mcp_tools(
        command=data.command,
        args=data.args,
        env=data.env,
        timeout_seconds=data.timeout_seconds,
    )
    return result