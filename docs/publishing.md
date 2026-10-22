# 公開範圍與本機設定

[English](publishing.en.md) · [首頁](../README.md)

## Git 公開內容

保留 `app/`、`prompts/`、啟動原始碼、依賴清單與說明文件。`app/mcp/` 是通用連線程式，`mcp.example.json` 是不含憑證的範例，兩者保留。

| 本機內容 | 規則 |
| --- | --- |
| `.env`、`.env.*` | 排除；只保留 `.env.example` |
| `mcp.json`、`launcher.ini` | 排除；只提交通用範例 |
| `skills/*` | 排除技能內容；只保留 skills/README.md 與 README.en.md 的來源說明 |
| `runtime/*`、`AI-Agent.exe`、`.venv/` | 排除執行環境與編譯產物；runtime 只保留說明 |
| `workspace/*` | 排除作品、SDD 與上傳文件；只保留目錄說明 |
| `memory.db*`、`data/`、`logs/`、模型檔與 ZIP | 排除執行資料 |
| secrets／credentials 目錄、常見私鑰與憑證檔 | 排除 |

## 設定邊界

- 實際模型位址、模型名稱與其他本機參數放在 `.env` 或環境變數。
- MCP 的 headers、env 可用 `${VARIABLE_NAME}` 引用環境變數；不把憑證寫入通用範例或提示語。
- `.env` 是明文檔；Git 忽略不等於加密，也不會移除已追蹤內容或過去的提交。
- Log、工具回傳、文件與圖片可能含使用者資料，不應隨原始碼公開。

## 本次檢視

2026-10-22 人工閱讀應用程式、啟動器、提示語與範例設定，並做文字模式檢查；未發現應用程式中寫死的金鑰、私人模型服務位址或個人絕對路徑。一般的授權欄位名稱、公開上游網址與 loopback 預設值不是憑證。

範圍不包含 `.env`、使用者資料、第三方 runtime 的完整稽核、歷史 Git 提交或未來新增的檔案；不保證排除所有形式的機密資訊。未啟動服務、呼叫模型或執行程式測試，也沒有上傳或建立 Git 提交。

提交前仍應查看暫存區檔案與差異。若某檔案已被追蹤，新增 `.gitignore` 規則不會使它自動停止追蹤。

## 壓縮檔與 Git 不同

`launcher/package.py` 使用自己的檔案清單，不直接採用 `.gitignore`。既有 Linux／Windows 執行包會保留本機 Skills，方便目前使用者執行；不代表該包適合公開上傳。`--platform linux` 排除 Windows runtime 與 EXE，但仍保留 Skills。

打包器另排除 `.env`、實際 MCP 設定、常見憑證名稱、資料與模型檔；任意自訂檔名的機密仍需自行辨識。

若需要與目前 Git 公開範圍一致的原始碼包，使用：

```sh
python launcher/package.py --platform source AI-Agent-source.zip
```

此選項只保留 skills／runtime 的 README，不包含技能本體、Windows 套件或 EXE；通用 MCP 程式與 mcp.example.json 保留。
