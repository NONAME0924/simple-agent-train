"""實驗室設備：所有登入者可看、可匯出；新增、修改、改狀態只有「設備管理」。"""
import csv
import datetime
import io
from typing import Literal, Optional
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from app.storage.equipment import FIELDS, STATUSES, EquipmentError, equipment_manager
from app.storage.finance_export import _safe
from app.storage.notifications import notify

router = APIRouter()


class EquipmentIn(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    model: Optional[str] = Field(default=None, max_length=200)
    asset_no: Optional[str] = Field(default=None, max_length=200)
    serial_no: Optional[str] = Field(default=None, max_length=200)
    location: Optional[str] = Field(default=None, max_length=200)
    custodian: Optional[str] = Field(default=None, max_length=200)
    purchased_on: Optional[str] = Field(default=None, max_length=20)
    price: Optional[int] = None
    note: Optional[str] = Field(default=None, max_length=2000)
    reason: str = Field(default="", max_length=400)


class StatusIn(BaseModel):
    status: Literal["normal", "repair", "retired"]
    reason: str = Field(default="", max_length=400)


def manager(request: Request):
    user = request.state.user
    if not user.get("is_equipment_manager"):
        raise HTTPException(status_code=403, detail="只有設備管理可以新增或修改設備。")
    return user


def _run(action):
    try:
        return action()
    except EquipmentError as error:
        raise HTTPException(status_code=error.status, detail=str(error))


def _fields(data: EquipmentIn):
    return {k: v for k, v in data.model_dump(exclude={"reason"}).items() if k in data.model_fields_set}


@router.get("/api/equipment")
def list_equipment(request: Request, q: str = "", status: Optional[Literal["normal", "repair", "retired"]] = None, location: str = ""):
    user = request.state.user
    return {"equipment": _run(lambda: equipment_manager.list(q, status or "", location)), "locations": equipment_manager.locations(),
            "can_manage": bool(user.get("is_equipment_manager"))}


@router.get("/api/equipment/export")
def export_equipment(request: Request, format: Literal["csv", "xlsx"] = "xlsx"):
    items = equipment_manager.list()
    head = ["編號"] + [label for label, _ in FIELDS.values()] + ["狀態", "登記時間", "最後更新"]
    rows = [[e["id"], *[e[k] if e[k] is not None else "" for k in FIELDS], STATUSES[e["status"]], e["created_at"], e["updated_at"]] for e in items]
    stamp = datetime.date.today().strftime("%Y%m%d")
    if format == "csv":
        out = io.StringIO(newline="")
        writer = csv.writer(out)
        writer.writerow(head)
        writer.writerows([[_safe(c) for c in row] for row in rows])
        body, media, name = ("﻿" + out.getvalue()).encode("utf-8"), "text/csv; charset=utf-8", f"equipment-{stamp}.csv"
    else:
        from openpyxl import Workbook
        from openpyxl.styles import Font
        wb = Workbook()
        ws = wb.active
        ws.title = "設備清單"
        ws.append(head)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for row in rows:
            ws.append(row)
        for line in ws.iter_rows(min_row=2):
            for cell in line:
                if isinstance(cell.value, str):
                    cell.data_type = "s"  # 以 = 開頭也只是文字
        for index, width in enumerate([6, 24, 18, 14, 18, 16, 10, 12, 12, 40, 8, 20, 20], 1):
            ws.column_dimensions[chr(64 + index)].width = width
        ws.freeze_panes = "A2"
        buffer = io.BytesIO()
        wb.save(buffer)
        body, media, name = buffer.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"equipment-{stamp}.xlsx"
    return Response(body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"',
                                                     "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/api/equipment/{equipment_id}")
def get_equipment(equipment_id: int):
    item = equipment_manager.get(equipment_id)
    if not item:
        raise HTTPException(status_code=404, detail="找不到這台設備。")
    return item


@router.post("/api/equipment")
def create_equipment(data: EquipmentIn, request: Request):
    actor = manager(request)
    item = _run(lambda: equipment_manager.create(_fields(data), actor))
    notify("role:equipment", actor, "新增設備", f"{item['name']}{'（' + item['location'] + '）' if item['location'] else ''}", f"equipment:{item['id']}")
    return item


@router.post("/api/equipment/{equipment_id}")
def update_equipment(equipment_id: int, data: EquipmentIn, request: Request):
    actor = manager(request)
    return _run(lambda: equipment_manager.update(equipment_id, _fields(data), actor, data.reason))


@router.post("/api/equipment/{equipment_id}/status")
def set_status(equipment_id: int, data: StatusIn, request: Request):
    actor = manager(request)
    item = _run(lambda: equipment_manager.set_status(equipment_id, data.status, actor, data.reason))
    notify("role:equipment", actor, f"設備{STATUSES[data.status]}：{item['name']}", data.reason, f"equipment:{equipment_id}")
    return item
