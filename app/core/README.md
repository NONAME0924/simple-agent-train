# Agent 核心

[English](README.en.md)

協調流程；工具與儲存實作留在各自模組。

| 檔案／目錄 | 用途 |
| --- | --- |
| `__init__.py` | Python 套件入口；部分套件也在此匯出共用函式。 |
| `agent.py` | 任務主循環，協調模型、工具、模式與結案。 |
| `conclusion.py` | 收集本次執行結果，組裝結案資料與簡短保底。 |
| `execution.py` | 暫停檢查點、參數驗證、同步／非同步工具呼叫與紀錄。 |
| `intent.py` | 自動模式的直接處理／規劃判斷。 |
| `model_client.py` | Ollama 串流、完成標記、空回應恢復與逾時診斷。 |
| `prompt.py` | 組裝系統提示、AGENTS.md、技能目錄與工具清單。 |
| `skill_registry.py` | 發現技能、解析中繼資料，以相對路徑提供章節索引與分段讀取。 |
