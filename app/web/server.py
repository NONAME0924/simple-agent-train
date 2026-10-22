import uuid
import time
import asyncio
import re
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import httpx
from app.logging_setup import setup_logging, log, log_context, is_quiet_read

setup_logging()

from app.config import OLLAMA_BASE_URL, DEFAULT_MODEL, SERVER_HOST, SERVER_PORT, STATIC_DIR
from app.core.agent import ChatAgent
from app.storage.memory import memory_manager
from app.storage.jobs import job_manager
from app.storage.workspace import workspace_scope, session_workspace
from app.web.conversation_api import router as conversation_router
from app.web.workspace_api import router as workspace_router
from app.web.log_api import router as log_router
from app.web.skill_api import router as skill_router
from app.web.mcp_api import router as mcp_router
from app.mcp.client import mcp_manager


@asynccontextmanager
async def lifespan(app):
    setup_logging()  # Uvicorn 設定完成後也保留存取紀錄的輪詢過濾。
    log("server.start")
    try:
        yield
    finally:
        await mcp_manager.close()
        await asyncio.to_thread(job_manager.shutdown)
        log("server.stop")


app = FastAPI(title="AI Agent with Multi-Session Sidebar", version="1.2.0", lifespan=lifespan)


@app.middleware("http")
async def request_log(request, call_next):
    token = log_context.set({"request_id": uuid.uuid4().hex})
    started = time.perf_counter()
    workspace_token = None
    try:
        match = re.match(r"/api/sessions/([^/]+)", request.url.path)
        session_id = request.query_params.get("session_id") or (match.group(1) if match else None)
        session = memory_manager.get_session(session_id) if session_id else None
        project = re.match(r"/api/projects/([^/]+)", request.url.path)
        if session:
            log_context.set({**log_context.get(), "session_id": session_id, "project_id": session["project_id"]})
        elif project:
            log_context.set({**log_context.get(), "project_id": project.group(1)})
        if request.url.path.startswith("/api/workspace/"):
            if not session:
                return JSONResponse({"detail": "請指定目前對話的 session_id。"}, status_code=400)
            workspace_token = workspace_scope.set(session_workspace(session))
        response = await call_next(request)
        if not is_quiet_read(request.method, request.url.path, response.status_code):
            log("http.response", method=request.method, path=request.url.path,
                query=dict(request.query_params), status=response.status_code, duration=time.perf_counter() - started,
                level=40 if response.status_code >= 500 else 30 if response.status_code >= 400 else 20,
                **getattr(request.state, "log_context", {}))
        return response
    except Exception:
        log("http.failed", level=40, exc_info=True, method=request.method, path=request.url.path)
        raise
    finally:
        if workspace_token is not None:
            workspace_scope.reset(workspace_token)
        log_context.reset(token)

# 允許跨域請求 (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 實例化 Agent
app.state.agent = ChatAgent(base_url=OLLAMA_BASE_URL, default_model=DEFAULT_MODEL)
app.include_router(conversation_router)
app.include_router(workspace_router)
app.include_router(log_router)
app.include_router(skill_router)
app.include_router(mcp_router)


@app.get("/api/health")
async def health_check():
    """檢查服務健康狀態與 Ollama 連線"""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("name") for m in data.get("models", [])]
                return {
                    "status": "healthy",
                    "ollama_url": OLLAMA_BASE_URL,
                    "default_model": DEFAULT_MODEL,
                    "available_models": models
                }
    except Exception as e:
        log("health.failed", level=40, exc_info=True)
        return {
            "status": "degraded",
            "ollama_url": OLLAMA_BASE_URL,
            "error": str(e)
        }
    return {"status": "unknown"}


# 掛載靜態網頁檔案
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def root():
    return FileResponse(STATIC_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.web.server:app", host=SERVER_HOST, port=SERVER_PORT, reload=True)
