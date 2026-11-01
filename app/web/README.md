# Web API

[English](README.en.md)

FastAPI 路由與瀏覽器資源。

| 檔案／目錄 | 用途 |
| --- | --- |
| `static/` | 原生 HTML、CSS、JavaScript，不需要前端建置。 |
| `__init__.py` | Python 套件入口；部分套件也在此匯出共用函式。 |
| `auth.py` | 登入狀態驗證與對話／專案存取規則（由 middleware 統一呼叫）。 |
| `finance_api.py` | 實驗室公帳：請款、收據照片、會計審核與經費增減 API。 |
| `auth_api.py` | 登入、註冊、改密碼與管理員帳號管理 API。 |
| `conversation_api.py` | 專案／對話、圖片、SSE 聊天、控制與工作 API。 |
| `log_api.py` | 日誌範圍、等級與類別篩選及下載。 |
| `server.py` | FastAPI 組裝、生命週期、路由、健康狀態及靜態資源。 |
| `skill_api.py` | 全域技能總表與來源說明 API。 |
| `workspace_api.py` | 工作區檔案、搜尋、地圖、SDD 與文件匯入 API。 |
