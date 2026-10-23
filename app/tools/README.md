# 內建工具

[English](README.en.md)

函式簽名同時產生 Schema 與參數驗證。

讀寫檔案統一使用 `path`、`content`、`old_string`、`new_string`。註冊時可明確指定 `aliases` 相容舊名稱；不同值的別名衝突會拒絕，未知欄位與型別仍嚴格驗證。局部替換先精確匹配，再容許換行與行尾空白差異；多處匹配不自動選擇，找不到時提供重讀指引及可能相關的行號。

| 檔案／目錄 | 用途 |
| --- | --- |
| `__init__.py` | 統一註冊內建工具與適用模式。 |
| `finish_task.py` | 交付最終回答，明確結束一次執行。 |
| `file_edit.py` | 唯一區塊匹配、有限空白容錯與失敗定位提示；不直接寫檔。 |
| `google_search.py` | Google News RSS 與一般網頁搜尋。 |
| `history_memory.py` | 限制在目前專案／對話的歷史搜尋。 |
| `planning.py` | 保存 spec.md、plan.md、tasks.md 三份 SDD。 |
| `preferences.py` | 引用使用者原文，單項新增或取代共用偏好。 |
| `read_web_page.py` | 擷取網頁／Markdown 文字與連結。 |
| `registry.py` | 工具定義、Pydantic Schema、明確別名相容、嚴格驗證與 ToolResult。 |
| `skill_install.py` | 從公開來源安裝技能並保留來源及雜湊紀錄。 |
| `skill_run.py` | 執行 Skill 原始 Python 腳本，沿用工作區、背景工作及 Log。 |
| `workspace_tools.py` | 檔案讀寫、程式搜尋、Python AST 地圖及 Python 執行工具。 |
