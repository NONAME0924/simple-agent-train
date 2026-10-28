# MCP Skill

[繁體中文](README.md)

Uses MCP servers as a Skill: they are not registered as tools, so the per-round prompt does not grow. Connections are made on demand and closed afterwards.

| File / directory | Purpose |
| --- | --- |
| `SKILL.md` | Usage flow and cautions for the model (kept under 60 lines so the first read is complete). |
| `mcp.json` | Server list: command, environment, timeouts, `tools.include` / `exclude`. Reference secrets as `${VAR}`; never store them in the file. |
| `scripts/mcp_tool.py` | stdio MCP client with no third-party dependencies; supports `servers`, `list`, `call`, `batch`. |

Ships with the official [Blender Lab MCP](https://projects.blender.org/lab/blender_mcp) (`blender-mcp`). If `blender-mcp` is not on PATH, set `command` to the executable's full path, e.g. `D:/path/venv/Scripts/blender-mcp.exe`.
