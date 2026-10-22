# MCP connection code

[繁體中文](README.md)

Generic code remains public; actual mcp.json and credentials are ignored.

| File/directory | Purpose |
| --- | --- |
| `__init__.py` | Python package entry; some packages also export shared helpers here. |
| `adapter.py` | Validates external tool schemas and converts text/image results. |
| `client.py` | MCP connection lifecycle, discovery, serialization, and connection tools. |
| `config.py` | Validates MCP settings, expands environment references, and persists scope bindings. |
