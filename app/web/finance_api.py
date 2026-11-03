"""實驗室公帳：成員請款（附照片）、會計審核與經費增減。"""
import asyncio
from urllib.parse import unquote
from typing import Literal, Optional
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from app.logging_setup import log
import datetime
from app.storage.finance import DATE_RE, FinanceError, MAX_IMAGES, finance_manager, label_for, real_name_map
from app.storage import finance_export
from app.storage.notifications import notify
from app.storage.images import MAX_IMAGE_BYTES, image_info, image_path, save_image

router = APIRouter()


class NewRequest(BaseModel):
    amount: int
    description: str = Field(max_length=600)
    images: list[str] = Field(default_factory=list, max_length=MAX_IMAGES)


class Reject(BaseModel):
    reason: str = Field(max_length=400)


class Approve(BaseModel):
    force: bool = False


class AmountChange(BaseModel):
    amount: int
    note: str = Field(max_length=400)


class Correction(AmountChange):
    force: bool = False


class Revoke(BaseModel):
    note: str = Field(max_length=400)


class Adjust(BaseModel):
    kind: Literal["add", "subtract"]
    amount: int
    note: str = Field(max_length=400)


def _scope(user_id):
    return f"finance:{user_id}"


def _run(action):
    try:
        return action()
    except FinanceError as error:
        raise HTTPException(status_code=error.status, detail={"message": str(error), **error.extra} if error.extra else str(error))


def treasurer(request: Request):
    user = request.state.user
    if not user.get("is_treasurer"):
        raise HTTPException(status_code=403, detail="只有會計可以審核請款與調整經費。")
    return user


def viewer(request: Request):
    user = request.state.user
    if not (user.get("is_treasurer") or user["role"] == "admin"):
        raise HTTPException(status_code=403, detail="只有會計與管理員可以查看經費。")
    return user


def _visible(user, item):
    return item["user_id"] == user["id"] or user.get("is_treasurer") or user["role"] == "admin"


@router.get("/api/finance/me")
def finance_me(request: Request):
    user = request.state.user
    can_view = bool(user.get("is_treasurer") or user["role"] == "admin")
    return {"is_treasurer": bool(user.get("is_treasurer")), "can_view": can_view,
            "pending": finance_manager.pending_count() if can_view else 0}


@router.post("/api/finance/images")
async def upload_receipt(request: Request):
    user = request.state.user
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="單張圖片最多 10 MiB。")
    try:
        return await asyncio.to_thread(save_image, _scope(user["id"]), bytes(data), unquote(request.headers.get("X-File-Name", "receipt.png")))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except Exception:
        log("image.failed", level=40, exc_info=True, scope="finance")
        raise HTTPException(status_code=422, detail="圖片處理失敗，完整錯誤已記入 log。")


@router.post("/api/finance/requests")
def create_request(data: NewRequest, request: Request):
    user = request.state.user
    if len(set(data.images)) != len(data.images):
        raise HTTPException(status_code=400, detail="同一張照片不能重複附上。")
    infos = []
    for image_id in data.images:
        try:
            infos.append({key: image_info(_scope(user["id"]), image_id)[key] for key in ("id", "name")})
        except (ValueError, OSError):
            raise HTTPException(status_code=422, detail="照片不存在，請重新上傳。")
    item = _run(lambda: finance_manager.create_request(user, data.amount, data.description, infos))
    notify("role:treasurer", user, "新的請款待審", f"{label_for(real_name_map([user['id']]), user['id'], user['username'])} 申請 ${item['amount']:,}：{item['description'][:60]}",
           f"finance:review:{item['id']}")
    return item


def _tell_requester(item, actor, title, body=""):
    """請款狀態變了就通知申請人本人；財務通知只發給當事人。"""
    notify(item["user_id"], actor, title, f"#{item['id']} {item['description'][:40]}（${item['amount']:,}）" + (f"：{body}" if body else ""),
           f"finance:mine:{item['id']}")


@router.get("/api/finance/requests/mine")
def my_requests(request: Request):
    return {"requests": finance_manager.list_requests(user_id=request.state.user["id"])}


@router.get("/api/finance/requests")
def all_requests(request: Request, status: Optional[Literal["pending", "approved", "rejected", "withdrawn"]] = None,
                 limit: int = Query(default=200, ge=1, le=500)):
    viewer(request)
    items = finance_manager.list_requests(status=status, limit=limit)
    names = real_name_map([item["user_id"] for item in items])
    for item in items:  # 會計與管理員看到「實名（帳號）」，成員自己的清單不變
        item["requester"] = label_for(names, item["user_id"], item["user_name"])
    return {"requests": items}


@router.get("/api/finance/requests/{request_id}/images/{image_id}")
def receipt_image(request_id: int, image_id: str, request: Request):
    item = finance_manager.get_request(request_id)
    if not item or not _visible(request.state.user, item) or image_id not in {i["id"] for i in item["images"]}:
        raise HTTPException(status_code=404, detail="找不到這張照片。")
    try:
        return FileResponse(image_path(_scope(item["user_id"]), image_id), media_type="image/png",
                            headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=3600"})
    except ValueError:
        raise HTTPException(status_code=404, detail="照片檔案已移除。")


@router.post("/api/finance/requests/{request_id}/withdraw")
def withdraw(request_id: int, request: Request):
    return _run(lambda: finance_manager.withdraw(request_id, request.state.user))


@router.post("/api/finance/requests/{request_id}/approve")
def approve(request_id: int, request: Request, data: Approve = Approve()):
    actor = treasurer(request)
    item = _run(lambda: finance_manager.approve(request_id, actor, data.force))
    _tell_requester(item, actor, "請款已通過")
    return {"request": item, "fund": finance_manager.summary()}


@router.post("/api/finance/requests/{request_id}/amount")
def change_amount(request_id: int, data: AmountChange, request: Request):
    actor = treasurer(request)
    item = _run(lambda: finance_manager.adjust_request_amount(request_id, data.amount, data.note, actor))
    _tell_requester(item, actor, "請款金額已調整", data.note)
    return item


@router.post("/api/finance/requests/{request_id}/correct")
def correct_approved(request_id: int, data: Correction, request: Request):
    actor = treasurer(request)
    item = _run(lambda: finance_manager.correct_approved(request_id, data.amount, data.note, actor, data.force))
    _tell_requester(item, actor, "已通過的請款金額被更正", data.note)
    return {"request": item, "fund": finance_manager.summary()}


@router.post("/api/finance/requests/{request_id}/revoke")
def revoke_approval(request_id: int, data: Revoke, request: Request):
    actor = treasurer(request)
    item = _run(lambda: finance_manager.revoke_approval(request_id, actor, data.note))
    _tell_requester(item, actor, "請款的通過已撤銷，回到審核中", data.note)
    return {"request": item, "fund": finance_manager.summary()}


@router.post("/api/finance/requests/{request_id}/reject")
def reject(request_id: int, data: Reject, request: Request):
    actor = treasurer(request)
    item = _run(lambda: finance_manager.reject(request_id, actor, data.reason))
    _tell_requester(item, actor, "請款被退回", data.reason)
    return item


@router.get("/api/finance/fund")
def fund(request: Request, before: Optional[int] = Query(default=None, ge=1)):
    viewer(request)
    return {**finance_manager.summary(), "ledger": finance_manager.ledger(before=before)}


@router.post("/api/finance/fund/adjust")
def adjust(data: Adjust, request: Request):
    actor = treasurer(request)
    return _run(lambda: finance_manager.adjust(data.kind, data.amount, data.note, actor))


def _day(value, label):
    value = (value or "").strip()
    if not value:
        return None
    try:
        if not DATE_RE.fullmatch(value):
            raise ValueError
        datetime.date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{label}須為真實存在的 YYYY-MM-DD 日期。")
    return value


@router.get("/api/finance/export")
def export(request: Request, format: Literal["csv", "xlsx"] = "xlsx", table: Literal["ledger", "requests", "corrections"] = "ledger",
           since: Optional[str] = None, until: Optional[str] = None):
    """會計與管理員匯出目前收支：Excel 含總覽＋流水帳＋請款明細＋更正與撤銷；CSV 一次一張表（table=ledger|requests|corrections）。"""
    user = viewer(request)
    since, until = _day(since, "起日"), _day(until, "迄日")
    if since and until and since > until:
        raise HTTPException(status_code=400, detail="起日不能晚於迄日。")
    data = finance_manager.export_data(since, until)
    stamp = datetime.date.today().strftime("%Y%m%d")
    if format == "xlsx":
        body, media, name = finance_export.build_xlsx(data), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"finance-{stamp}.xlsx"
    else:
        body, media, name = finance_export.build_csv(data, table), "text/csv; charset=utf-8", f"finance-{table}-{stamp}.csv"
    log("finance.exported", user_id=user["id"], format=format, table=table, since=since, until=until)
    return Response(body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"',
                                                     "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
