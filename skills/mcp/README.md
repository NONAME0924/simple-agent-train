# MCP Skill

[English](README.en.md)

以 Skill 方式使用 MCP server：不註冊成工具，不增加每輪的提示長度；需要時才連線，用完即關。

| 檔案／目錄 | 用途 |
| --- | --- |
| `SKILL.md` | 給模型的使用流程與注意事項（控制在 60 行內，首次讀取即完整）。 |
| `mcp.json` | server 清單：指令、環境變數、逾時、`tools.include`／`exclude`。機密請用 `${變數}`，不要寫入檔案。 |
| `scripts/mcp_tool.py` | stdio MCP 客戶端；零第三方相依，支援 `servers`、`list`、`call`、`batch`。 |

預設包含官方 [Blender Lab MCP](https://projects.blender.org/lab/blender_mcp)（`blender-mcp`）。若 `blender-mcp` 不在 PATH，請把 `command` 改成可執行檔的完整路徑，例如 `D:/path/venv/Scripts/blender-mcp.exe`。
