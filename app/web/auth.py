"""登入狀態驗證與資源存取規則；由 server 的 middleware 統一呼叫。"""
import re
from urllib.parse import urlsplit
from fastapi.responses import JSONResponse
from app.storage.memory import memory_manager
from app.storage.users import user_manager

COOKIE = "agent_session"
PUBLIC_API = {"/api/auth/login", "/api/auth/register"}
SAFE = {"GET", "HEAD", "OPTIONS"}


def deny(status, detail):
    return JSONResponse({"detail": detail}, status_code=status)


def session_role(user, session):
    """對話的存取身分：owner / project_owner / member / admin（唯讀）/ None。"""
    if session.get("owner_id") == user["id"]:
        return "owner"
    if session.get("project_id"):
        role = memory_manager.project_role(session["project_id"], user["id"])
        if role:
            return "project_owner" if role == "owner" else "member"
    return "admin" if user["role"] == "admin" else None


def project_role(user, project_id):
    role = memory_manager.project_role(project_id, user["id"])
    return role or ("admin" if user["role"] == "admin" else None)


def can_write_session(user, session):
    return session_role(user, session) in {"owner", "project_owner", "member"}


def can_delete_session(user, session):
    return session_role(user, session) in {"owner", "project_owner", "admin"}


def _same_origin(request):
    origin = request.headers.get("origin")
    return not origin or urlsplit(origin).netloc == request.headers.get("host", "")


def authorize(request):
    """回傳 (user, error_response)。非 /api 路徑（首頁與靜態檔）公開。"""
    path, method = request.url.path, request.method
    if not path.startswith("/api/"):
        return None, None
    if method not in SAFE and not _same_origin(request):
        return None, deny(403, "不允許跨網站請求。")
    if path in PUBLIC_API:
        return None, None
    user = user_manager.user_for_token(request.cookies.get(COOKIE))
    if user is None:
        return None, deny(401, "請先登入。")
    if path.startswith("/api/admin/") and user["role"] != "admin":
        return None, deny(403, "需要管理員權限。")

    match = re.match(r"/api/sessions/([^/]+)(/.*)?$", path)
    session_id = request.query_params.get("session_id") or (match.group(1) if match else None)
    if session_id:
        session = memory_manager.get_session(session_id)
        if session:
            role = session_role(user, session)
            if role is None:
                return None, deny(404, "找不到對話。")
            if role == "admin" and method not in SAFE and not (method == "DELETE" and match and not match.group(2)):
                return None, deny(403, "管理員只能檢視或刪除他人的對話。")

    match = re.match(r"/api/projects/([^/]+)(/.*)?$", path)
    if match:
        project_id, sub = match.group(1), match.group(2) or ""
        role = project_role(user, project_id)
        if memory_manager.get_project(project_id) and role is None:
            return None, deny(404, "找不到專案。")
        if role:
            is_leave = method == "DELETE" and sub == f"/members/{user['id']}"
            owner_only = (not sub and method != "GET") or (sub.startswith("/members") and method != "GET")
            if owner_only and not is_leave and role not in {"owner", "admin"}:
                return None, deny(403, "只有專案擁有者可以執行這項操作。")
            if sub.startswith("/memory") and method not in SAFE and role not in {"owner", "member"}:
                return None, deny(403, "管理員只能檢視他人的專案。")
    request.state.user = user
    return user, None
