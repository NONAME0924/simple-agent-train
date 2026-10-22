# 儲存與執行資料

[English](README.en.md)

管理本機資料，不在此資料夾保存使用者作品。

| 檔案／目錄 | 用途 |
| --- | --- |
| `__init__.py` | Python 套件入口；部分套件也在此匯出共用函式。 |
| `context_manager.py` | Token 估算、80% 壓縮、原文封存與長輸出讀取。 |
| `document_import.py` | 以 Python 套件擷取文件文字，保存原檔與匯入紀錄。 |
| `images.py` | 圖片驗證、縮放、儲存、引用及模型訊息轉換。 |
| `jobs.py` | Python 子程序、背景狀態、輸出、停止及檔案變更紀錄。 |
| `memory.py` | SQLite 專案、對話、歷史搜尋及工作上下文儲存。 |
| `plan_tasks.py` | 讀寫 tasks.md 勾選狀態與版本衝突檢查。 |
| `project_memory.py` | 專案 L2 增量摘要、固定記憶與來源游標。 |
| `workspace.py` | 工作區範圍、安全相對路徑與檔案走訪。 |
