# AI Agent

繁體中文 · [English](README.en.md)

使用 Python、FastAPI 與 Ollama 的本機 Agent。提供瀏覽器對話介面，透過工具讀寫工作區、執行 Python，並依需要載入 Skill。

## 功能

- 專案與對話分開管理；專案內共享工作區與 L2 摘要。
- 自動判斷直接處理或先規劃；規劃產生 SDD，確認後開始實作。
- 工具參數驗證、Python 背景工作、暫停／繼續與分級 Log。
- 程式搜尋、Python 靜態地圖、Markdown 預覽與文件文字匯入。
- 圖片附件；辨識能力取決於所選模型。
- 動態 Skill 載入與安裝。

## 開始使用

需要可連線的 Ollama 服務及已安裝的模型；本專案不下載模型。

1. 複製 `.env.example` 為 `.env`。
2. 設定 `OLLAMA_BASE_URL` 與 `DEFAULT_MODEL`；模型名稱必須與 Ollama 中的名稱一致。
3. 啟動後開啟 `http://127.0.0.1:8000`。

Linux／macOS 需要 Python 3.10+ 與 venv／ensurepip：

```sh
cp .env.example .env
# 編輯 .env 後啟動；首次準備環境需要網路。
sh run.sh --no-browser
```

Windows 原始碼版本：

```powershell
Copy-Item .env.example .env
# 編輯 .env，再執行以下指令。
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe launcher.py
```

若使用另附 Windows `runtime/` 的發行包，可改用 `AI-Agent.exe`。原始碼不包含這些二進位檔。更換連接埠使用 `--port 8001`；更新後重啟服務並重新整理瀏覽器。

## 設定

| 變數 | 用途 | 預設 |
| --- | --- | --- |
| `OLLAMA_BASE_URL` | 模型服務位址 | `http://127.0.0.1:11434` |
| `DEFAULT_MODEL` | Ollama 模型名稱 | 必填 |
| `AGENT_CONTEXT_TOKENS` | 配置的總上下文長度 | `32768` |
| `AGENT_OUTPUT_TOKENS` | 每次一般模型請求的生成上限 | `4096` |
| `AGENT_MODEL_READ_TIMEOUT` | 等待後續模型資料的秒數 | `600` |
| `AGENT_MAX_STEPS` | 每次任務的主模型決策輪數，未結案另加一次統整 | `15` |
| `SERVER_PORT` | 網頁服務連接埠 | `8000` |

既有環境變數優先於 `.env`。輸出上限目前最多為配置上下文的四分之一；達可用輸入預算 80% 時壓縮上下文。實際容量與速度取決於模型及硬體。

## 架構

```text
瀏覽器 → FastAPI → Agent → Ollama
                    ├─ 內建工具 → 工作區／Python 工作
                    ├─ Skill → 工作說明
                    └─ 儲存 → SQLite／檔案／Log
```

| 位置 | 責任 |
| --- | --- |
| [app/core/](app/core/README.md) | 任務流程、模型請求、提示語與結案 |
| [app/tools/](app/tools/README.md) | 內建工具、Schema 與驗證 |
| [app/storage/](app/storage/README.md) | 對話、上下文、工作區與背景工作 |
| [app/web/](app/web/README.md) | API 與原生 JavaScript 介面 |
| [prompts/](prompts/README.md) | 系統提示語；與使用者 `AGENTS.md` 分開 |
| [skills/](skills/README.md) | 本機技能的來源說明；技能內容不提交 |
| [launcher/](launcher/README.md) | 啟動準備與乾淨打包 |

各程式資料夾的 README 列出檔案用途。詳見[架構說明](docs/architecture.md)與[使用指南](docs/usage.md)。

根目錄檔案：

| 檔案 | 用途 |
| --- | --- |
| `launcher.py`／`run.sh` | 共用服務啟動／Linux 與 macOS 準備入口 |
| `requirements.txt` | 直接使用的 Python 依賴 |
| `requirements.lock.txt` | 部署使用的固定依賴版本 |
| `AGENTS.md` | 使用者共用偏好 |
| `.env.example` | 本機參數的公開範例 |
| `.gitignore` | 本機資料與技能內容的提交排除規則 |
| `啟動說明.txt` | 發行包的簡短啟動指引 |
| `README.md`／`README.en.md` | 中文／英文專案首頁 |

## 使用範圍與限制

- 預設供本機單人使用，沒有內建登入與多使用者權限管理。
- 工作區的路徑隔離不是作業系統沙箱；Python 具有執行帳號的權限。
- 暫停在處理檢查點生效，不會立即中止已開始的模型、工具或背景程序。
- 任務輪數由 `AGENT_MAX_STEPS` 設定，預設 15；未結案時再統整一次。工具成功不保證整體成果正確。
- 文件匯入只擷取文字，不做 OCR；Skill 的 Node.js、渲染器或其他依賴需另備。
- 部分前端函式庫來自 CDN，首次安裝、網路搜尋及外部模型需要網路。

Skill 預設只讀開頭 60 行並附章節索引，依行號選讀相關段落；已有足夠指引就執行，需要時再補讀。Skill 原檔不修改，已選讀的段落不會再被長工具輸出規則截成頭尾。

## 本機資料與來源

`.env`、技能內容、Windows runtime、資料庫、工作區與 Log 由 `.gitignore` 排除。本機資料不應加入原始碼；Log 與上傳文件也可能含敏感內容。[公開範圍與檢查紀錄](docs/publishing.md)。

SDD 以作者的 [NONAME0924/spec-driven-development](https://github.com/NONAME0924/spec-driven-development) 為來源，這裡是配合三份規格文件的精簡版本。PPTX Skill 來源為 [Anthropic Skills](https://github.com/anthropics/skills/tree/main/skills/pptx)，其附帶授權限制已記錄；技能內容不提交。

主程式目前沒有根目錄整體授權檔，不將第三方內容一律標為 MIT。各來源與授權範圍見[第三方與技能來源](docs/third-party.md)。
