# MCP Skill

[繁體中文](README.md)

An MCP package system: MCP servers are used as a Skill, not registered as tools, so the per-round prompt does not grow. Connections are made on demand and closed afterwards. The system only installs, enables and calls packages; it knows nothing about any specific package.

| File / directory | Purpose |
| --- | --- |
| `SKILL.md` | Generic flow and cautions for the model (kept under 60 lines so the first read is complete). |
| `scripts/mcp_tool.py` | Package manager and stdio MCP client with no third-party dependencies. Commands: `packages`, `install`, `remove`, `enable`, `disable`, `configure`, `list`, `call`, `batch`. |
| `packages/` | Installed MCP packages, one folder each; see [packages](packages/README.en.md). The project ships with `blender` installed. |
| `local.json` | Per-machine overrides (disabled state, command path, environment), written by `enable` / `disable` / `configure`; not committed. |

## Package format

Put `mcp-package.json` at the root of the package folder:

```json
{
  "name": "my-tool",
  "version": "1.0.0",
  "description": "One-line description",
  "guide": "GUIDE.md",
  "server": {"command": "${PYTHON}", "args": ["-B", "${PACKAGE_DIR}/server.py"],
             "env": {"API_KEY": "${MY_TOOL_API_KEY}"}, "connect_timeout": 20, "timeout": 120,
             "tools": {"include": ["search_*"]}}
}
```

- `${PYTHON}`, `${SKILL_DIR}`, `${PACKAGE_DIR}` and environment variables work in `command`, `args` and `env`; reference secrets through environment variables, never store them in files.
- `tools.include` (allowlist) and `tools.exclude` (denylist) support `*`; `include` wins when both are set.
- `GUIDE.md` holds prerequisites and cautions for the model, read on first use of the package.

## Install and manage

```
python scripts/mcp_tool.py install ./my-tool          # folder or .zip (inside the current directory)
python scripts/mcp_tool.py install https://example.com/my-tool.zip
python scripts/mcp_tool.py disable blender
python scripts/mcp_tool.py configure blender --env BLENDER_PORT=9877
python scripts/mcp_tool.py remove my-tool --yes
```

Installing only copies files and never runs the package; its program starts locally during `list` / `call`, so install only sources you trust. Zips containing paths that escape the target folder or symbolic links are rejected, and packages are capped at 50 MB. GitHub zip URLs (such as `https://github.com/<user>/<repo>/archive/refs/heads/main.zip`) work directly.

## Using the official `blender-mcp`

The official server connects to the same bridge as the bundled `blender` package; use one of them. To switch: put an `mcp-package.json` next to the official server (`name` set to `blender-official`, `server.command` set to the full path of `blender-mcp`, empty `args`), install it, then `disable blender`.
