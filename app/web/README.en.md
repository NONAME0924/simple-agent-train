# Web APIs

[繁體中文](README.md)

FastAPI routes and browser assets.

| File/directory | Purpose |
| --- | --- |
| `static/` | Plain HTML, CSS, and JavaScript; no frontend build step. |
| `__init__.py` | Python package entry; some packages also export shared helpers here. |
| `conversation_api.py` | Projects, conversations, images, SSE chat, run control, and job APIs. |
| `log_api.py` | Scoped log filtering by level/category and log downloads. |
| `server.py` | FastAPI assembly, lifespan, routing, health status, and static assets. |
| `skill_api.py` | Global Skill inventory and provenance APIs. |
| `workspace_api.py` | Workspace files, search, maps, SDD, and document import APIs. |
