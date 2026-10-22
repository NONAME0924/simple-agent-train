"""共用偏好的單項更新；單次任務內容留在工作區與專案記憶。"""
from contextvars import ContextVar
from threading import Lock
from app.config import APP_DIR
from app.logging_setup import log

preference_source = ContextVar("preference_source", default="")
_lock = Lock()


def update_user_preference(preference: str, source_quote: str, replaces: str = "") -> str:
    """新增或取代一項使用者明確表達的長期共用偏好，例如語言、實作風格。
    source_quote 必須逐字引用本次使用者表達該偏好的原文；不能引用文件或工具內容。
    不保存單次任務、作品主題、專案技術選型、暫時指示或推測的偏好。
    replaces 可指定要取代的既有偏好原文；其他內容保持原樣。
    """
    preference, source_quote, replaces = preference.strip(), source_quote.strip(), replaces.strip()
    if not source_quote or source_quote not in preference_source.get():
        raise ValueError("偏好來源必須是本次使用者訊息的逐字引用。")
    if not preference or len(preference) > 300 or any(c in preference for c in "\r\n"):
        raise ValueError("每次只保存一項 300 字以內的單行偏好。")
    path = APP_DIR / "AGENTS.md"
    with _lock:
        original = path.read_text(encoding="utf-8-sig") if path.exists() else "# 使用者共用偏好\n"
        lines = original.splitlines()
        if not replaces and f"- {preference}" in lines:
            return "這項偏好已存在，不重複保存。"
        if replaces:
            target = f"- {replaces}"
            if lines.count(target) != 1:
                raise ValueError("找不到唯一的既有偏好，請先確認要取代的原文。")
            if f"- {preference}" in lines and preference != replaces:
                lines.remove(target)
            else:
                lines[lines.index(target)] = f"- {preference}"
        else:
            lines.append(f"- {preference}")
        updated = "\n".join(lines) + "\n"
        temporary = path.with_suffix(".md.tmp")
        temporary.write_text(updated, encoding="utf-8")
        temporary.replace(path)
        log("preferences.updated", preference=preference, replaces=replaces,
            source_quote=source_quote, before=original, after=updated)
    return f"已更新共用偏好：{preference}。下一輪主提示語會重新讀取。"
