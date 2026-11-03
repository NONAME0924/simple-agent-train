"""站內通知：讀取自己的通知、標為已讀；管理員發公告。"""
from typing import Literal
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from app.storage.notifications import notification_manager, notify

router = APIRouter()


class Announcement(BaseModel):
    to: Literal["all", "role:admin", "role:treasurer", "role:equipment"] = "all"
    title: str = Field(max_length=200)
    body: str = Field(default="", max_length=2000)


@router.get("/api/notifications")
def my_notifications(request: Request, limit: int = Query(default=50, ge=1, le=200)):
    return notification_manager.list(request.state.user["id"], limit)


@router.get("/api/notifications/unread")
def unread_count(request: Request):
    return {"unread": notification_manager.unread(request.state.user["id"])}


@router.post("/api/notifications/read-all")
def read_all(request: Request):
    notification_manager.mark_read(request.state.user["id"])
    return {"status": "ok"}


@router.post("/api/notifications/{notification_id}/read")
def read_one(notification_id: int, request: Request):
    notification_manager.mark_read(request.state.user["id"], notification_id)
    return {"status": "ok"}


@router.post("/api/admin/announce")
def announce(data: Announcement, request: Request):
    """/api/admin/ 開頭的路徑已在 authorize() 限定管理員。"""
    if not data.title.strip():
        raise HTTPException(status_code=400, detail="公告需要標題。")
    count = notify(data.to, request.state.user, data.title, data.body, "", include_sender=True)
    return {"sent": count}
