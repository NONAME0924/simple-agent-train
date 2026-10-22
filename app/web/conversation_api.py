"""專案、對話、L2 記憶、聊天串流與背景工作 API。"""
import datetime
import asyncio
import json
import os
import uuid
from urllib.parse import unquote
from typing import Literal, Optional
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from app.logging_setup import log
from app.storage.memory import memory_manager
from app.storage.jobs import job_manager, JOB_DIR
from app.storage.workspace import session_workspace
from app.storage.images import MAX_IMAGE_BYTES, MAX_IMAGES, save_image, image_path, image_info
from app.mcp.client import mcp_manager

router = APIRouter()


async def detach_mcp(session):
    try:
        await mcp_manager.detach(session)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = "default"
    model: Optional[str] = None
    mode: Literal["auto", "agent", "plan"] = "auto"
    reasoning_level: Literal["low", "medium", "high"] = "medium"
    images: list[str] = Field(default_factory=list, max_length=MAX_IMAGES)


class ControlRequest(BaseModel):
    action: Literal["pause", "resume"]


class CreateSessionRequest(BaseModel):
    session_id: Optional[str] = None
    title: Optional[str] = "新對話"
    project_id: Optional[str] = None


class ProjectRequest(BaseModel):
    name: str


class MoveSessionRequest(BaseModel):
    project_id: Optional[str] = None


class MemoryEdit(BaseModel):
    summary: str = Field(max_length=12000)
    pinned: str = Field(max_length=8000)
    version: int


@router.get("/api/projects")
async def get_projects():
    return {"projects": memory_manager.list_projects()}


@router.get("/api/projects/{project_id}/memory")
async def get_project_memory(project_id: str):
    project = memory_manager.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="找不到專案。")
    return {"memory": memory_manager.get_project_memory(project_id),
            "pinned": project["pinned_memory"], "version": project["memory_version"]}


@router.post("/api/projects")
async def create_project(req: ProjectRequest):
    try:
        return memory_manager.save_project(f"proj_{uuid.uuid4().hex}", req.name)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.patch("/api/projects/{project_id}")
async def rename_project(project_id: str, req: ProjectRequest):
    if memory_manager.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="找不到專案。")
    try:
        return memory_manager.save_project(project_id, req.name)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.delete("/api/projects/{project_id}")
async def delete_project(project_id: str, request: Request):
    if any(s["project_id"] == project_id and (s["id"] in request.app.state.agent.runs or job_manager.has_active(s["id"])) for s in memory_manager.list_sessions()):
        raise HTTPException(status_code=409, detail="專案中仍有執行中的任務，請完成後再刪除分類。")
    await detach_mcp({"project_id": project_id, "id": ""})
    if not memory_manager.delete_project(project_id):
        raise HTTPException(status_code=404, detail="找不到專案。")
    return {"status": "success"}


@router.get("/api/sessions")
async def get_sessions():
    """取得所有會話清單（依最後活躍時間降序排列）"""
    sessions = memory_manager.list_sessions()
    return {"sessions": sessions}


@router.post("/api/sessions")
async def create_session(req: CreateSessionRequest):
    """建立新會話"""
    project_id = req.project_id or None
    if project_id is not None and memory_manager.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="找不到專案。")
    sess_id = req.session_id or f"sess_{int(datetime.datetime.now().timestamp())}_{uuid.uuid4().hex[:6]}"
    session = memory_manager.create_or_get_session(sess_id, req.title, project_id)
    return session


@router.patch("/api/sessions/{session_id}/project")
async def move_session(session_id: str, req: MoveSessionRequest, request: Request):
    if session_id in request.app.state.agent.runs or job_manager.has_active(session_id):
        raise HTTPException(status_code=409, detail="此對話仍有執行中的任務，請完成後再移動。")
    project_id = req.project_id or None
    if project_id is not None and memory_manager.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="找不到專案。")
    old_session = memory_manager.get_session(session_id)
    if old_session and not old_session["project_id"] and project_id:
        await detach_mcp(old_session)
    if not memory_manager.move_session(session_id, project_id):
        raise HTTPException(status_code=404, detail="找不到對話。")
    return memory_manager.get_session(session_id)


@router.get("/api/sessions/{session_id}/messages")
async def get_session_messages(session_id: str):
    """取得特定會話的訊息紀錄（供右側聊天視窗還原）"""
    messages = memory_manager.get_session_messages(session_id)
    for message in messages:
        attachments = []
        for image_id in message["images"]:
            try:
                attachments.append(image_info(session_id, image_id))
            except (ValueError, OSError):
                attachments.append({"id": image_id, "name": "圖片附件（檔案已移除）"})
        message["images"] = attachments
    return {"messages": messages}


@router.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str, request: Request):
    """刪除指定會話及其所有歷史紀錄 (級聯刪除)"""
    if session_id in request.app.state.agent.runs or job_manager.has_active(session_id):
        raise HTTPException(status_code=409, detail="此對話仍有執行中的任務，請完成後再刪除。")
    session = memory_manager.get_session(session_id)
    if session and not session["project_id"]:
        await detach_mcp(session)
    success = memory_manager.delete_session(session_id)
    return {"status": "success" if success else "not_found"}


@router.post("/api/sessions/{session_id}/control")
async def control_run(session_id: str, req: ControlRequest, request: Request):
    control = request.app.state.agent.runs.get(session_id)
    if control is None:
        raise HTTPException(status_code=409, detail="目前沒有執行中的任務。")
    if req.action == "pause":
        control.ready.clear()
        log("run.pause_requested", session_id=session_id, run_id=control.run_id)
        return {"state": "paused" if control.waiting else "pausing"}
    control.ready.set()
    log("run.resume_requested", session_id=session_id, run_id=control.run_id)
    return {"state": "running"}


@router.get("/api/sessions/{session_id}/jobs")
def list_jobs(session_id: str):
    return {"jobs": job_manager.list(session_id)}


@router.get("/api/sessions/{session_id}/jobs/{job_id}")
def job_details(session_id: str, job_id: str):
    try:
        record = job_manager.get(session_id, job_id)
        session = memory_manager.get_session(session_id)
        matches = session is not None and os.path.normcase(record["cwd"]) == os.path.normcase(session_workspace(session))
        return {**record, "workspace_matches": matches, "stdout": job_manager.output(job_id, "stdout", 16000),
                "stderr": job_manager.output(job_id, "stderr", 16000)}
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))


@router.post("/api/sessions/{session_id}/jobs/{job_id}/stop")
def stop_background_job(session_id: str, job_id: str):
    try:
        return job_manager.stop(session_id, job_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))


@router.get("/api/sessions/{session_id}/jobs/{job_id}/output/{kind}")
def download_job_output(session_id: str, job_id: str, kind: Literal["stdout", "stderr"]):
    try:
        job_manager.get(session_id, job_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))
    return FileResponse(JOB_DIR / job_id / f"{kind}.txt", filename=f"{job_id}-{kind}.txt", media_type="text/plain; charset=utf-8")


# ==========================================
# 聊天串流 API (SSE)
# ==========================================

@router.post("/api/sessions/{session_id}/images")
async def upload_image(session_id: str, request: Request):
    if memory_manager.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="找不到目前對話。")
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="單張圖片最多 10 MiB。")
    try:
        return await asyncio.to_thread(save_image, session_id, bytes(data),
            unquote(request.headers.get("X-File-Name", "image.png")))
    except ValueError as error:
        log("image.rejected", level=30, exc_info=True, session_id=session_id, error=str(error))
        raise HTTPException(status_code=422, detail=str(error))
    except Exception:
        log("image.failed", level=40, exc_info=True, session_id=session_id)
        raise HTTPException(status_code=422, detail="圖片處理失敗，完整錯誤已記入 log。")


@router.get("/api/sessions/{session_id}/images/{image_id}")
def view_image(session_id: str, image_id: str):
    if memory_manager.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="找不到目前對話。")
    try:
        return FileResponse(image_path(session_id, image_id), media_type="image/png")
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))


@router.post("/api/chat")
async def chat_stream(req: ChatRequest, request: Request):
    """
    SSE (Server-Sent Events) 串流聊天端點。
    支援多步驟執行、工具即時回饋、思考鏈與結案交付。
    """
    if not req.message.strip() and not req.images:
        raise HTTPException(status_code=400, detail="訊息不可為空")
    message = req.message.strip() or "請分析這些圖片。"

    # 確保 session 存在於資料庫
    sess_id = req.session_id or f"sess_{int(datetime.datetime.now().timestamp())}_{uuid.uuid4().hex[:6]}"
    memory_manager.create_or_get_session(sess_id, title=message[:25])
    request.state.log_context = {"session_id": sess_id, "project_id": memory_manager.get_session(sess_id)["project_id"]}
    try:
        for image_id in req.images:
            image_path(sess_id, image_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    try:
        control = request.app.state.agent.start_run(sess_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))

    async def event_generator():
        stream = request.app.state.agent.stream_chat(
            session_id=sess_id,
            user_message=message,
            model=req.model,
            mode=req.mode,
            reasoning_level=req.reasoning_level,
            control=control,
            images=req.images
        )
        try:
            async for event in stream:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            await stream.aclose()
            if request.app.state.agent.runs.get(sess_id) is control:
                request.app.state.agent.runs.pop(sess_id, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


def require_project(project_id):
    project = memory_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="找不到專案。")
    return project


@router.patch("/api/projects/{project_id}/memory")
def edit_memory(project_id: str, data: MemoryEdit):
    require_project(project_id)
    try:
        memory_manager.edit_project_memory(project_id, data.summary, data.pinned, data.version)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))
    return {"status": "saved"}


@router.get("/api/projects/{project_id}/memory/sources")
def memory_sources(project_id: str, before: int = Query(default=None, ge=1)):
    require_project(project_id)
    saved = memory_manager.get_project_memory(project_id)
    rows = memory_manager.project_memory_sources(project_id, saved["source_cursor"], before) if saved else []
    return {"sources": rows, "next_before": rows[-1]["id"] if len(rows) == 30 else None}


