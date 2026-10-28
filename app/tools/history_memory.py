from app.storage.memory import memory_manager
from contextvars import ContextVar


memory_session = ContextVar("memory_session", default=None)


def search_history_memory(keywords: str) -> str:
    """搜尋目前專案內的歷史對話、先前設定與舊決策；未分類時僅搜尋目前對話。
    使用者問起過去的事、或所需資訊不在近期對話中時使用。

    Args:
        keywords: 檢索關鍵字。
    """
    session_id = memory_session.get()
    if session_id is None:
        return "缺少目前對話，無法確認記憶搜尋範圍。"
    return memory_manager.search_memory(keywords=keywords, session_id=session_id)
