from app.storage.memory import memory_manager
from contextvars import ContextVar


memory_session = ContextVar("memory_session", default=None)


def search_history_memory(keywords: str) -> str:
    """搜尋目前專案內的歷史對話、先前設定與舊決策；未分類時僅搜尋目前對話。

    當遇到以下情況時應積極調用此工具：
    1. 使用者詢問過去的事情（例如：「你還記得我上次說過...」、「之前我們討論的...」、「查一下我以前紀錄的...」）。
    2. 使用者的問題涉及歷史決策或過往話題，且該資訊不在當前最近的對話視窗內時。
    3. 使用者明確要求「查記憶」、「翻紀錄」、「之前的事」時。

    Args:
        keywords: 檢索關鍵字，例如「資料庫選型」或「專案架構」
    """
    session_id = memory_session.get()
    if session_id is None:
        return "缺少目前對話，無法確認記憶搜尋範圍。"
    return memory_manager.search_memory(keywords=keywords, session_id=session_id)
