from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from typing import Optional
from database import get_db
from models import McpServer, Tool, ToolType, ToolStatus, gen_uuid, now_utc
from schemas import ToolCreate, ToolUpdate, ToolResponse, ToolTestRequest, McpDiscoverRequest, PaginatedResponse
from services.tool_service import tool_execution_service
from services.builtin_tools import get_builtin_tools_for_runtime

router = APIRouter(prefix="/api/v1/tools", tags=["tools"])


def _tool_response(tool: Tool) -> ToolResponse:
    payload = ToolResponse.model_validate(tool)
    server = getattr(tool, "mcp_server", None)
    if server is not None:
        payload.mcp_server_name = server.display_name or server.name or ""
    elif tool.mcp_server_id and isinstance(tool.config, dict):
        payload.mcp_server_name = ""
    return payload


@router.get("/builtin")
def list_builtin_tools():
    items = []
    for t in get_builtin_tools_for_runtime():
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
    mcp_server_id: Optional[str] = Query(None, description="按 MCP Server 列出工具（含已同步工具）"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = (
        db.query(Tool)
        .options(joinedload(Tool.mcp_server))
    )
    if mcp_server_id:
        # Explicit server scope: used by Agent connector policy UI.
        query = query.filter(Tool.mcp_server_id == mcp_server_id)
    else:
        # Tools management: hide all tools synced/owned by MCP servers (connectors + platform).
        query = query.filter(Tool.mcp_server_id.is_(None))
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
        items=[_tool_response(t) for t in tools]
    )


@router.post("", response_model=ToolResponse, status_code=201)
def create_tool(data: ToolCreate, db: Session = Depends(get_db)):
    existing = db.query(Tool).filter(Tool.name == data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="工具名称已存在")

    config = dict(data.config or {})
    server_id = data.mcp_server_id or config.get("mcp_server_id")
    if server_id:
        server = db.query(McpServer).filter(McpServer.server_id == server_id).first()
        if not server:
            raise HTTPException(status_code=400, detail="关联的 MCP Server 不存在")
        config["mcp_server_id"] = server_id
        config.setdefault("transport", server.transport)
    tool = Tool(
        tool_id=gen_uuid(),
        name=data.name,
        display_name=data.display_name or data.name,
        description=data.description,
        tool_type=ToolType(data.tool_type),
        config=config,
        parameters_schema=data.parameters_schema,
        mcp_server_id=server_id,
    )
    db.add(tool)
    db.commit()
    db.refresh(tool)
    return _tool_response(tool)


@router.get("/{tool_id}", response_model=ToolResponse)
def get_tool(tool_id: str, db: Session = Depends(get_db)):
    tool = db.query(Tool).filter(Tool.tool_id == tool_id).first()
    if not tool:
        raise HTTPException(status_code=404, detail="工具不存在")
    return _tool_response(tool)


@router.put("/{tool_id}", response_model=ToolResponse)
def update_tool(tool_id: str, data: ToolUpdate, db: Session = Depends(get_db)):
    tool = db.query(Tool).filter(Tool.tool_id == tool_id).first()
    if not tool:
        raise HTTPException(status_code=404, detail="工具不存在")

    update_fields = data.model_dump(exclude_unset=True)
    if "name" in update_fields:
        new_name = (update_fields.get("name") or "").strip()
        if new_name and new_name != tool.name:
            clash = db.query(Tool).filter(Tool.name == new_name, Tool.tool_id != tool.tool_id).first()
            if clash:
                raise HTTPException(status_code=400, detail="工具名称已存在")
        update_fields["name"] = new_name or tool.name
    if "config" in update_fields and isinstance(update_fields["config"], dict):
        cfg = dict(update_fields["config"])
        if cfg.get("mcp_server_id") and not update_fields.get("mcp_server_id"):
            update_fields["mcp_server_id"] = cfg.get("mcp_server_id")
        update_fields["config"] = cfg
    for key, value in update_fields.items():
        if hasattr(tool, key):
            setattr(tool, key, value)
    tool.updated_at = now_utc()
    db.commit()
    db.refresh(tool)
    return _tool_response(tool)


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
        transport=data.transport,
        url=data.url,
        headers=data.headers,
        auth_type=data.auth_type,
        auth_token=data.auth_token,
        mcp_server_id=data.mcp_server_id,
    )
    return result