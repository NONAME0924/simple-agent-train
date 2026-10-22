"""按需連線與讀取狀態；不輪詢、不自動修改場景。"""
from importlib.metadata import distribution
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from app.logging_setup import log_context
from app.mcp.client import mcp_manager
from app.storage.memory import memory_manager

router = APIRouter()


def _session(session_id):
    session = memory_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="找不到目前對話。")
    return session


@router.get("/api/sessions/{session_id}/mcp")
async def mcp_status(session_id: str):
    try:
        return {"servers": mcp_manager.status(_session(session_id))}
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


@router.post("/api/sessions/{session_id}/mcp/{server}/connect")
async def connect(session_id: str, server: str):
    session = _session(session_id)
    try:
        connection = await mcp_manager.connect(session, server)
        # 明確按連線時才查詢場景，MCP 程序已連線與 Blender 可用分別呈現。
        if server == "blender" and connection.config.instance not in mcp_manager.owners:
            result = await connection.call("get_scene_info", {}, {**log_context.get(), "session_id": session_id})
            connection.application = result.ok
            connection.application_error = "" if result.ok else (
                str(result) + "\n請確認 Blender 插件已啟用並按下 Start MCP Server，且位址與連接埠相同。"
                "若 Agent 在遠端，127.0.0.1 指遠端主機，不是瀏覽器所在電腦。")
        return {"servers": mcp_manager.status(session)}
    except (ValueError, RuntimeError) as error:
        raise HTTPException(status_code=409, detail=str(error))


@router.post("/api/sessions/{session_id}/mcp/{server}/disconnect")
async def disconnect(session_id: str, server: str):
    session = _session(session_id)
    try:
        await mcp_manager.disconnect(session, server)
        return {"servers": mcp_manager.status(session)}
    except (ValueError, RuntimeError) as error:
        raise HTTPException(status_code=409, detail=str(error))


@router.get("/api/mcp/blender/addon")
def blender_addon():
    path = distribution("mcp-for-blender").locate_file("blender_mcp/bundled/addon.py")
    return FileResponse(path, filename="blender_mcp_addon.py", media_type="text/x-python")
