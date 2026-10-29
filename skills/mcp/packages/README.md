# MCP 套件

[English](README.en.md)

每個子資料夾是一個已安裝的 MCP 套件，根目錄含 `mcp-package.json`，可選 `GUIDE.md`。

| 套件 | 用途 |
| --- | --- |
| `blender/` | 專案預設安裝：Blender Lab 橋接的 MCP server。可停用、移除或替換。 |

用 `scripts/mcp_tool.py install` 新裝的套件預設不進 git（見專案 `.gitignore`）；只有 `blender` 隨原始碼提交。
