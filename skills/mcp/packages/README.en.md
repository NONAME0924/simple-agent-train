# MCP packages

[繁體中文](README.md)

Each subfolder is an installed MCP package, with `mcp-package.json` at its root and an optional `GUIDE.md`.

| Package | Purpose |
| --- | --- |
| `blender/` | Installed by default: an MCP server for the Blender Lab bridge. It can be disabled, removed or replaced. |

Packages added with `scripts/mcp_tool.py install` are not committed by default (see the project `.gitignore`); only `blender` ships with the source.
