# MCP Skill

[English](README.en.md)

MCP 套件系統：以 Skill 方式使用 MCP server，不註冊成工具，不增加每輪的提示長度；需要時才連線，用完即關。系統只負責安裝、啟用與呼叫套件，本身不認識任何特定套件。

| 檔案／目錄 | 用途 |
| --- | --- |
| `SKILL.md` | 給模型的通用流程與注意事項（控制在 60 行內，首次讀取即完整）。 |
| `scripts/mcp_tool.py` | 套件管理與 stdio MCP 客戶端；零第三方相依。指令：`packages`、`install`、`remove`、`enable`、`disable`、`configure`、`list`、`call`、`batch`。 |
| `packages/` | 已安裝的 MCP 套件，每個一個資料夾，見 [packages](packages/README.md)。專案預設安裝 `blender`。 |
| `local.json` | 這台電腦專屬的覆寫（停用、指令路徑、環境變數），由 `enable`／`disable`／`configure` 寫入；不進 git。 |

## 套件格式

套件資料夾根目錄放 `mcp-package.json`：

```json
{
  "name": "my-tool",
  "version": "1.0.0",
  "description": "一句話說明",
  "guide": "GUIDE.md",
  "server": {"command": "${PYTHON}", "args": ["-B", "${PACKAGE_DIR}/server.py"],
             "env": {"API_KEY": "${MY_TOOL_API_KEY}"}, "connect_timeout": 20, "timeout": 120,
             "tools": {"include": ["search_*"]}}
}
```

- `${PYTHON}`、`${SKILL_DIR}`、`${PACKAGE_DIR}` 與環境變數可用在 `command`、`args`、`env`；機密請引用環境變數，不要寫入檔案。
- `tools.include`（白名單）與 `tools.exclude`（黑名單）支援 `*`，兩者並存時以 `include` 為準。
- `GUIDE.md` 是給模型看的使用前提與注意事項，第一次使用套件時由模型讀取。

## 安裝與管理

```
python scripts/mcp_tool.py install ./my-tool          # 資料夾或 .zip（限目前目錄內）
python scripts/mcp_tool.py install https://example.com/my-tool.zip
python scripts/mcp_tool.py disable blender
python scripts/mcp_tool.py configure blender --env BLENDER_PORT=9877
python scripts/mcp_tool.py remove my-tool --yes
```

安裝只複製檔案，不會執行套件；套件的程式會在 `list`／`call` 時由本機啟動，請只安裝你信任的來源。zip 內含會跳出目標資料夾的路徑或符號連結時會被拒絕，套件上限 50 MB。GitHub 的 zip 網址（如 `https://github.com/<帳號>/<倉庫>/archive/refs/heads/main.zip`）可直接使用。

## 使用官方 `blender-mcp`

官方 server 與預設的 `blender` 套件連的是同一個橋接，擇一使用即可。要改用官方版：在官方 server 的資料夾放 `mcp-package.json`（`name` 取 `blender-official`，`server.command` 填 `blender-mcp` 的完整路徑，`args` 為空），安裝後 `disable blender`。
