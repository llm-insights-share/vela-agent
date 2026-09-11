import os

# Must be set before PyTorch/OpenMP (sentence-transformers) initializes.
# Otherwise asyncio subprocess fork deadlocks the API event loop.
os.environ.setdefault("KMP_INIT_AT_FORK", "FALSE")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi import HTTPException
from database import init_db, SessionLocal
from deps import get_current_user
from auth_config import ADMIN_PASSWORD, ADMIN_USERNAME, AVATAR_DIR
from models import User
from security import hash_password
from routes.agents import router as agents_router
from routes.model_services import router as model_services_router
from routes.skills import router as skills_router
from routes.knowledge_bases import router as knowledge_bases_router
from routes.sessions import router as sessions_router
from routes.tools import router as tools_router
from routes.config import router as config_router
from routes.compositions import router as compositions_router
from routes.hitl import router as hitl_router
from routes.approvals import router as approvals_router
from routes.workflows import router as workflows_router
from routes.workflow_cron import router as workflow_cron_router
from routes.dataquery_agents import router as dataquery_agents_router
from routes.dataquery_metadata import router as dataquery_metadata_router
from routes.dataquery_knowledge import router as dataquery_knowledge_router
from routes.memory import router as memory_router
from routes.screenpilot import router as screenpilot_router
from routes.query_rewrite import router as query_rewrite_router
from routes.auth import router as auth_router
from routes.users import router as users_router
from routes.llm_gateway import router as llm_gateway_router
from routes.code_exec import router as code_exec_router
from routes.schedules import router as schedules_router
from routes.inbox import router as inbox_router
from routes.mcp_servers import router as mcp_servers_router, oauth_callback_router
from routes.connectors import router as connectors_router
from routes.monitor import router as monitor_router
from routes.eval import router as eval_router
from routes.selfopt import router as selfopt_router

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

_auth_deps = [Depends(get_current_user)]

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(llm_gateway_router)  # Letta 回连：独立共享密钥，不挂 JWT
app.include_router(agents_router, dependencies=_auth_deps)
app.include_router(model_services_router, dependencies=_auth_deps)
app.include_router(skills_router, dependencies=_auth_deps)
app.include_router(knowledge_bases_router, dependencies=_auth_deps)
app.include_router(sessions_router, dependencies=_auth_deps)
app.include_router(tools_router, dependencies=_auth_deps)
app.include_router(config_router, dependencies=_auth_deps)
app.include_router(compositions_router, dependencies=_auth_deps)
app.include_router(hitl_router, dependencies=_auth_deps)
app.include_router(approvals_router, dependencies=_auth_deps)
app.include_router(workflows_router, dependencies=_auth_deps)
app.include_router(workflow_cron_router, dependencies=_auth_deps)
app.include_router(dataquery_agents_router, dependencies=_auth_deps)
app.include_router(dataquery_metadata_router, dependencies=_auth_deps)
app.include_router(dataquery_knowledge_router, dependencies=_auth_deps)
app.include_router(memory_router, dependencies=_auth_deps)
app.include_router(screenpilot_router, dependencies=_auth_deps)
app.include_router(query_rewrite_router, dependencies=_auth_deps)
app.include_router(code_exec_router, dependencies=_auth_deps)
app.include_router(schedules_router, dependencies=_auth_deps)
app.include_router(inbox_router, dependencies=_auth_deps)
app.include_router(mcp_servers_router, dependencies=_auth_deps)
app.include_router(connectors_router, dependencies=_auth_deps)
app.include_router(monitor_router, dependencies=_auth_deps)
app.include_router(eval_router, dependencies=_auth_deps)
app.include_router(selfopt_router, dependencies=_auth_deps)
app.include_router(oauth_callback_router)

AVATAR_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/avatars", StaticFiles(directory=str(AVATAR_DIR)), name="avatars")


def seed_admin() -> None:
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == ADMIN_USERNAME).first()
        if existing:
            return
        db.add(
            User(
                username=ADMIN_USERNAME,
                email=f"{ADMIN_USERNAME}@localhost",
                display_name="Administrator",
                hashed_password=hash_password(ADMIN_PASSWORD),
                roles="admin,member",
                is_active=True,
            )
        )
        db.commit()
    finally:
        db.close()

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
        from services.schedule.runner import recover_stale_schedule_runs
        recover_stale_schedule_runs(db)
    finally:
        db.close()


@app.on_event("startup")
async def on_startup():
    init_db()
    seed_admin()
    _recover_stale_running_sessions()
    try:
        from services.monitor.otel_setup import setup_tracer_provider

        setup_tracer_provider()
    except Exception as e:
        print(f"[startup] OpenTelemetry init skipped: {e}")
    from services.workflow_cron_scheduler import cron_scheduler
    from services.schedule.scheduler import schedule_scheduler

    cron_scheduler.start()
    schedule_scheduler.start()
    try:
        from services.selfopt.scheduler import selfopt_scheduler
        from services.selfopt.config import is_schedule_enabled

        if is_schedule_enabled():
            selfopt_scheduler.start()
    except Exception as e:
        print(f"[startup] SelfOpt scheduler skipped: {e}")
    from models import ModelProvider, ProviderStatus, gen_uuid
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

    if os.environ.get("VELA_SEED_DEMO", "").strip() in ("1", "true", "TRUE", "yes", "YES"):
        try:
            from scripts.seed_demo import seed_all

            summary = seed_all()
            print(f"[startup] demo seed ok: agents={list((summary.get('agents') or {}).keys())}")
        except Exception as e:
            print(f"[startup] demo seed skipped/failed: {e}")


@app.on_event("shutdown")
async def on_shutdown():
    try:
        from services.monitor.otel_setup import shutdown_tracer_provider

        shutdown_tracer_provider()
    except Exception:
        pass
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
        from services.schedule.scheduler import schedule_scheduler

        cron_scheduler.stop()
        schedule_scheduler.stop()
    except Exception as e:
        print(f"[shutdown] schedulers: {e}")
    try:
        from services.selfopt.scheduler import selfopt_scheduler

        selfopt_scheduler.stop()
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