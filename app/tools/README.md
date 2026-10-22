# 內建工具

[English](README.en.md)

函式簽名同時產生 Schema 與參數驗證。

| 檔案／目錄 | 用途 |
| --- | --- |
| `__init__.py` | 統一註冊內建工具與適用模式。 |
| `finish_task.py` | 交付最終回答，明確結束一次執行。 |
| `google_search.py` | Google News RSS 與一般網頁搜尋。 |
| `history_memory.py` | 限制在目前專案／對話的歷史搜尋。 |
| `planning.py` | 保存 spec.md、plan.md、tasks.md 三份 SDD。 |
| `preferences.py` | 引用使用者原文，單項新增或取代共用偏好。 |
| `read_web_page.py` | 擷取網頁／Markdown 文字與連結。 |
| `registry.py` | 工具定義、Pydantic Schema、嚴格驗證與 ToolResult。 |
| `skill_install.py` | 從公開來源安裝技能並保留來源及雜湊紀錄。 |
| `workspace_tools.py` | 檔案讀寫、程式搜尋、Python AST 地圖及 Python 執行工具。 |
