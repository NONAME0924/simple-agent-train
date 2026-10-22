# 啟動與打包

[English](README.en.md)

根目錄 launcher.py 是共用服務入口，本目錄保存準備及打包程式。

| 檔案／目錄 | 用途 |
| --- | --- |
| `Launcher.cs` | Windows EXE 的 C# 原始碼，轉交 Python 啟動器。 |
| `bootstrap.py` | Linux／macOS 建立虛擬環境與依賴準備。 |
| `package.py` | 依清單打包；source 排除技能與環境本體，linux／all 供本機執行包使用。 |
