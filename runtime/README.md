# Windows 執行環境

[English](README.en.md)

本機發行環境；Git 僅保留說明。Lib 等第三方套件目錄沿用各自說明與授權，不逐一增寫專案 README。

| 檔案／目錄 | 用途 |
| --- | --- |
| `DLLs/` | 第三方執行環境內容，沿用套件本身的說明與授權。 |
| `Lib/` | 第三方執行環境內容，沿用套件本身的說明與授權。 |
| `Scripts/` | 第三方執行環境內容，沿用套件本身的說明與授權。 |
| `tcl/` | 第三方執行環境內容，沿用套件本身的說明與授權。 |
| `LICENSE.txt` | Python 發行內容附帶授權。 |
| `python.exe` | Windows Python 執行器。 |
| `python3.dll` | Python 穩定 ABI 動態函式庫。 |
| `python312.dll` | 此本機發行版的 Python 3.12 動態函式庫。 |
| `vcruntime140.dll` | Microsoft C 執行階段動態函式庫。 |
| `vcruntime140_1.dll` | Microsoft C 執行階段支援函式庫。 |

Linux／macOS 使用專案 .venv，不使用此 Windows 環境。Windows 原始碼啟動方式見專案首頁。
