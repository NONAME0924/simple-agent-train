"""目前執行任務所屬的使用者；工具與提示語據此套用個人偏好與管理權限。"""
from contextvars import ContextVar

current_user = ContextVar("current_user", default=None)


def is_admin():
    """沒有登入使用者（本機命令列）視為管理員；網頁任務依帳號角色。"""
    user = current_user.get()
    return user is None or user.get("role") == "admin"


def require_admin(action):
    if not is_admin():
        raise PermissionError(f"只有管理員可以{action}；請聯絡管理員處理。")
