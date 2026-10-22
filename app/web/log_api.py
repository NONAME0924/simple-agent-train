"""按目前專案／對話讀取日誌尾端；不啟動輪詢或載入整份歷史。"""
import json
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from app.logging_setup import log_path, event_category, is_quiet_read
from app.storage.memory import memory_manager

router = APIRouter()
LogScope = Literal["current", "session", "system"]


def _source(session_id, scope):
    session = memory_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="找不到目前對話。")
    path = log_path({} if scope == "system" else {"project_id": session["project_id"], "session_id": session_id})
    label = "系統" if scope == "system" else "目前專案" if session["project_id"] and scope != "session" else "目前對話"
    # 專案對話寫在同一份專案 log；session 模式從該檔篩選本對話。
    return path, label, session_id if scope == "session" else None


@router.get("/api/sessions/{session_id}/logs")
def read_logs(session_id: str, scope: LogScope = "current",
              level: Literal["ALL", "INFO", "WARNING", "ERROR"] = "ALL",
              category: Literal["ALL", "system", "model", "tool", "mcp", "memory"] = "ALL",
              limit: int = Query(default=100, ge=1, le=200)):
    path, label, only_session = _source(session_id, scope)
    entries, budget, limited = [], 4 * 1024 * 1024, False
    for index in range(9):
        source = path if index == 0 else Path(f"{path}.{index}")
        try:
            with source.open("rb") as stream:
                size = stream.seek(0, 2)
                start = max(0, size - budget)
                stream.seek(start)
                data = stream.read(budget)
        except FileNotFoundError:
            continue
        budget -= len(data)
        lines = data.splitlines()
        if start:
            lines = lines[1:]  # 片段開頭可能在一筆 JSON 的中間。
            limited = True
        for line in reversed(lines):
            try:
                entry = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue  # 忽略仍在寫入的尾行。
            if not isinstance(entry, dict):
                continue
            if only_session and entry.get("session_id") != only_session:
                continue
            if entry.get("event") == "http.response" and is_quiet_read(entry.get("method"), entry.get("path"), entry.get("status", 0)):
                continue  # 舊紀錄不重寫；畫面也略過成功查詢。
            entry.setdefault("category", event_category(entry.get("event", "")))
            if category != "ALL" and entry["category"] != category:
                continue
            if level != "ALL" and entry.get("level") not in ({"ERROR", "CRITICAL"} if level == "ERROR" else {level}):
                continue
            entries.append(entry)
            if len(entries) == limit:
                return {"entries": entries, "source": label, "limited": True}
        if budget <= 0:
            limited = True
            break
    return {"entries": entries, "source": label, "limited": limited}


@router.get("/api/sessions/{session_id}/logs/download")
def download_log(session_id: str, scope: LogScope = "current", backup: int = Query(default=0, ge=0, le=8)):
    path, _, _ = _source(session_id, scope)
    if backup:
        path = Path(f"{path}.{backup}")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="尚無這份日誌。")
    return FileResponse(path, filename=f"{path.parent.name}-{path.name}", media_type="application/x-ndjson")
