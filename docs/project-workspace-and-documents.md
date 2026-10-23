# 工作區、文件與記憶

[架構](architecture.md) · [使用指南](usage.md)

## 資料範圍

| 位置 | 用途 |
| --- | --- |
| `workspace/projects/<project_id>/` | 同專案各對話共享的檔案與 SDD |
| `workspace/conversations/<session_id>/` | 獨立一般對話的檔案 |
| 目前工作區的 `.specify/` | spec.md、plan.md、tasks.md |
| 目前工作區的 `documents/<id>/` | 匯入原檔與擷取文字 |
| `data/images/` | 對話圖片；訊息以 ID 引用 |
| `memory.db` | 專案、對話、工作上下文與 L2 |

搜尋、預覽、下載與 Python 執行沿用目前工作區。刪除專案分類保留檔案，不自動搬移舊共用檔案。路徑檢查不構成 Python 的作業系統沙箱。

## 文件匯入

使用專案 Python 套件擷取文字，不需要本機 Office，不呼叫模型、不做 OCR，也不讀文件內的圖片像素。

| 格式 | 套件 |
| --- | --- |
| PDF | pypdf |
| DOCX | python-docx |
| PPTX | python-pptx |
| XLSX／XLSM | openpyxl |
| XLS | xlrd |
| ODT／ODS／ODP | odfpy |
| EPUB／HTML | EbookLib／beautifulsoup4 |
| RTF | striprtf |
| 純文字與程式碼 | Python 標準函式庫 |

單檔上限 25 MiB，PDF 上限 1000 頁。舊 DOC／PPT、DOCM／PPTM 與未提供解析器的二進位格式不支援；掃描文件可能沒有可擷取文字。文字結果不保證保留視覺排版。

聊天圖片另走 PNG／JPEG／WebP 流程；每則最多四張，每張最多 10 MiB／2500 萬像素，處理後長邊最多 2048 像素。辨識需要視覺模型。

## L2 與任務

專案 L2 由對話增量摘要，保留來源游標；使用者固定內容獨立保存。一般對話不建立共用 L2。右側面板可查看、編輯與清空記憶。

tasks.md 支援 `[ ]` 未開始、`[>]` 進行中、`[x]` 完成與 `[!]` 阻塞；介面與 Agent 工具更新同一份文件。

自動摘要與模型標示不是成果驗證；實際檔案與工具結果仍需核對。
