from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi import HTTPException
import os
from database import init_db
from routes.agents import router as agents_router
from routes.model_services import router as model_services_router
from routes.skills import router as skills_router
from routes.knowledge_bases import router as knowledge_bases_router
from routes.sessions import router as sessions_router
from routes.tools import router as tools_router
from routes.config import router as config_router
from routes.compositions import router as compositions_router
from routes.hitl import router as hitl_router
from routes.workflows import router as workflows_router
from routes.workflow_cron import router as workflow_cron_router
from routes.dataquery_agents import router as dataquery_agents_router
from routes.dataquery_metadata import router as dataquery_metadata_router
from routes.dataquery_knowledge import router as dataquery_knowledge_router
from routes.memory import router as memory_router
from routes.screenpilot import router as screenpilot_router
from routes.query_rewrite import router as query_rewrite_router

app = FastAPI(
    title="Vela Agent Playground API",
    description="Agent Playground — Agent 管理与编排平台",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agents_router)
app.include_router(model_services_router)
app.include_router(skills_router)
app.include_router(knowledge_bases_router)
app.include_router(sessions_router)
app.include_router(tools_router)
app.include_router(config_router)
app.include_router(compositions_router)
app.include_router(hitl_router)
app.include_router(workflows_router)
app.include_router(workflow_cron_router)
app.include_router(dataquery_agents_router)
app.include_router(dataquery_metadata_router)
app.include_router(dataquery_knowledge_router)
app.include_router(memory_router)
app.include_router(screenpilot_router)
app.include_router(query_rewrite_router)

# #region agent log
try:
    import json as _json, time as _time
    with open("/Users/zhangjr/apps/LlmDemo/vibe-project/vela-agent/.cursor/debug-66b153.log", "a") as _f:
        _f.write(_json.dumps({
            "sessionId": "66b153", "runId": "startup", "hypothesisId": "H1",
            "location": "main.py:import",
            "message": "main app imported successfully",
            "data": {"title": app.title, "version": app.version},
            "timestamp": int(_time.time() * 1000),
        }, ensure_ascii=False) + "\n")
except Exception:
    pass
# #endregion


def _recover_stale_running_sessions():
    """服务重启后，在途后台任务已丢失，将 RUNNING 会话标记为 ERROR。"""
    from sqlalchemy.orm.attributes import flag_modified
    from database import SessionLocal
    from models import Session as SessionModel, SessionStatus

    db = SessionLocal()
    try:
        running_sessions = db.query(SessionModel).filter(
            SessionModel.status == SessionStatus.RUNNING
        ).all()
        for session in running_sessions:
            messages = list(session.messages or [])
            messages.append({
                "role": "assistant",
                "content": "❌ 服务重启导致任务中断，请重新发送消息。",
            })
            session.messages = messages
            flag_modified(session, "messages")
            session.status = SessionStatus.ERROR
            pending = dict(session.pending_context or {})
            pending.pop("background_job", None)
            session.pending_context = pending
        if running_sessions:
            db.commit()
    finally:
        db.close()


@app.on_event("startup")
async def on_startup():
    init_db()
    _recover_stale_running_sessions()
    from services.workflow_cron_scheduler import cron_scheduler
    cron_scheduler.start()
    from models import ModelProvider, ModelService, ProviderStatus, gen_uuid
    from database import SessionLocal
    db = SessionLocal()
    try:
        existing = db.query(ModelProvider).count()
        if existing == 0:
            providers = [
                ModelProvider(
                    provider_id=gen_uuid(),
                    provider_code="deepseek",
                    display_name="DeepSeek",
                    base_url="https://api.deepseek.com/v1",
                    api_key="",
                    extra_headers={},
                    status=ProviderStatus.ACTIVE,
                ),
                ModelProvider(
                    provider_id=gen_uuid(),
                    provider_code="bailian",
                    display_name="阿里云百炼",
                    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                    api_key="",
                    extra_headers={},
                    status=ProviderStatus.ACTIVE,
                ),
            ]
            db.add_all(providers)
            db.commit()
    finally:
        db.close()


@app.on_event("shutdown")
async def on_shutdown():
    try:
        from services.screenpilot.session_manager import shutdown_browser_pool

        await shutdown_browser_pool()
    except Exception as e:
        print(f"[shutdown] ScreenPilot browser pool: {e}")
    try:
        from services.screenpilot.mcp_pool import screenpilot_mcp_pool

        await screenpilot_mcp_pool.shutdown()
    except Exception as e:
        print(f"[shutdown] ScreenPilot MCP pool: {e}")
    try:
        from services.workflow_cron_scheduler import cron_scheduler

        cron_scheduler.stop()
    except Exception:
        pass


@app.get("/api/v1/health")
def health_check():
    return {"status": "ok", "service": "Vela Agent Playground"}


MIME_TYPES = {
    ".html": "text/html",
    ".htm": "text/html",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".json": "application/json",
    ".xml": "application/xml",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".drawio": "application/xml",
    ".dio": "application/xml",
}


@app.get("/api/v1/files/{session_id}/{filename}")
def download_file(session_id: str, filename: str):
    file_path = os.path.join(
        os.path.dirname(__file__), "data", "outputs", session_id, filename
    )
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="文件不存在")

    ext = os.path.splitext(filename)[1].lower()
    media_type = MIME_TYPES.get(ext, "application/octet-stream")

    return FileResponse(
        file_path,
        filename=filename,
        media_type=media_type,
    )