"""登入、註冊、個人密碼，以及管理員的帳號管理。"""
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from app.config import AUTH_COOKIE_SECURE, AUTH_SESSION_DAYS
from app.storage.memory import memory_manager
from app.storage.users import AuthError, public, register_throttle, user_manager
from app.web.auth import COOKIE

router = APIRouter()


class Credentials(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)


class Registration(Credentials):
    real_name: str = Field(max_length=64)


class PasswordChange(BaseModel):
    old_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


class NewPassword(BaseModel):
    password: str = Field(max_length=256)


class RoleChange(BaseModel):
    role: str


class AdminCreate(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)
    role: str = "user"
    real_name: str = Field(max_length=64)


def _source(request: Request):
    return request.client.host if request.client else ""


def _run(action):
    try:
        return action()
    except AuthError as error:
        raise HTTPException(status_code=error.status, detail=str(error))


@router.post("/api/auth/login")
def login(data: Credentials, request: Request, response: Response):
    user = _run(lambda: user_manager.authenticate(data.username, data.password, _source(request)))
    response.set_cookie(COOKIE, user_manager.new_token(user["id"]), max_age=AUTH_SESSION_DAYS * 86400,
                        httponly=True, samesite="lax", secure=AUTH_COOKIE_SECURE, path="/")
    return {"user": public(user)}


@router.post("/api/auth/register")
def register(data: Registration, request: Request):
    key = _source(request)
    if register_throttle.blocked(key):
        raise HTTPException(status_code=429, detail="註冊太頻繁，請稍後再試。")
    register_throttle.add(key)
    _run(lambda: user_manager.create_user(data.username, data.password, "user", "pending", data.real_name, True))
    return {"status": "pending", "message": "已送出申請，等管理員核准後即可登入。"}


@router.post("/api/auth/logout")
def logout(request: Request, response: Response):
    user_manager.revoke_token(request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path="/")
    return {"status": "ok"}


@router.get("/api/auth/me")
def me(request: Request):
    return {"user": public(request.state.user)}


@router.post("/api/auth/password")
def change_password(data: PasswordChange, request: Request):
    user = request.state.user
    row = user_manager.get(user["id"])
    from app.storage.users import verify_password
    if not verify_password(data.old_password, row["password_hash"]):
        raise HTTPException(status_code=403, detail="目前的密碼不正確。")
    _run(lambda: user_manager.set_password(user["id"], data.new_password, keep_token=request.cookies.get(COOKIE)))
    return {"status": "ok"}


# ---------------- 管理員 ----------------
@router.get("/api/admin/users")
def admin_users():
    return {"users": user_manager.list_users()}


@router.post("/api/admin/users")
def admin_create_user(data: AdminCreate):
    return public(_run(lambda: user_manager.create_user(data.username, data.password, data.role, "active", data.real_name, True)))


@router.post("/api/admin/users/{user_id}/status/{status}")
def admin_set_status(user_id: str, status: str, request: Request):
    return public(_run(lambda: user_manager.set_status(user_id, status, request.state.user["id"])))


@router.post("/api/admin/users/{user_id}/role")
def admin_set_role(user_id: str, data: RoleChange, request: Request):
    return public(_run(lambda: user_manager.set_role(user_id, data.role, request.state.user["id"])))


class TreasurerChange(BaseModel):
    value: bool


@router.post("/api/admin/users/{user_id}/treasurer")
def admin_set_treasurer(user_id: str, data: TreasurerChange, request: Request):
    return public(_run(lambda: user_manager.set_treasurer(user_id, data.value, request.state.user["id"])))


@router.post("/api/admin/users/{user_id}/password")
def admin_reset_password(user_id: str, data: NewPassword):
    _run(lambda: user_manager.set_password(user_id, data.password))
    return {"status": "ok"}


@router.delete("/api/admin/users/{user_id}")
def admin_delete_user(user_id: str, request: Request):
    _run(lambda: user_manager.delete_user(user_id, request.state.user["id"]))
    return {"status": "ok"}


@router.get("/api/admin/sessions")
def admin_sessions():
    return {"sessions": memory_manager.list_sessions(include_all=True)}


@router.get("/api/admin/projects")
def admin_projects():
    return {"projects": memory_manager.list_projects(include_all=True)}
