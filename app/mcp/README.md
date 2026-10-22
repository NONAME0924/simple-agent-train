# MCP 連線程式

[English](README.en.md)

通用程式可公開；實際 mcp.json 與憑證不提交。

| 檔案／目錄 | 用途 |
| --- | --- |
| `__init__.py` | Python 套件入口；部分套件也在此匯出共用函式。 |
| `adapter.py` | 外部工具 Schema 驗證及文字／圖片結果轉換。 |
| `client.py` | MCP 連線生命週期、工具發現、排隊及連線工具。 |
| `config.py` | MCP 設定驗證、環境變數展開與範圍綁定。 |
