"""午餐輪盤：清單所有人可看、可新增；修改與刪除限新增者或管理員。抽籤在瀏覽器做（只是好玩，不需要伺服器裁決）。"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from app.storage.lunch import LunchError, lunch_manager

router = APIRouter()


class RestaurantIn(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    category: Optional[str] = Field(default=None, max_length=100)
    price: Optional[str] = Field(default=None, max_length=100)
    note: Optional[str] = Field(default=None, max_length=500)


def _run(action):
    try:
        return action()
    except LunchError as error:
        raise HTTPException(status_code=error.status, detail=str(error))


def _fields(data: RestaurantIn):
    return {k: v for k, v in data.model_dump().items() if k in data.model_fields_set}


@router.get("/api/lunch")
def list_restaurants(category: str = "", price: str = ""):
    return lunch_manager.list(category[:20], price[:20])


@router.post("/api/lunch")
def add_restaurant(data: RestaurantIn, request: Request):
    return _run(lambda: lunch_manager.create(_fields(data), request.state.user))


@router.post("/api/lunch/{restaurant_id}")
def edit_restaurant(restaurant_id: int, data: RestaurantIn, request: Request):
    return _run(lambda: lunch_manager.update(restaurant_id, _fields(data), request.state.user))


@router.delete("/api/lunch/{restaurant_id}")
def delete_restaurant(restaurant_id: int, request: Request):
    _run(lambda: lunch_manager.delete(restaurant_id, request.state.user))
    return {"status": "ok"}
