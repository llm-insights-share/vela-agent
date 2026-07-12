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


@app.on_event("startup")
async def on_startup():
    init_db()
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