# Built-in tools

[繁體中文](README.md)

Function signatures supply both schemas and argument validation.

| File/directory | Purpose |
| --- | --- |
| `__init__.py` | Registers built-in tools and their supported modes. |
| `finish_task.py` | Delivers the final answer and explicitly concludes a run. |
| `google_search.py` | Google News RSS and general web search. |
| `history_memory.py` | History search scoped to the current project or conversation. |
| `planning.py` | Saves the three SDD files: spec.md, plan.md, and tasks.md. |
| `preferences.py` | Updates one shared preference with a quote from the user's message. |
| `read_web_page.py` | Reads web/Markdown text and links. |
| `registry.py` | Tool definitions, Pydantic schemas, strict validation, and ToolResult. |
| `skill_install.py` | Installs Skills from public sources and records provenance and hashes. |
| `workspace_tools.py` | Workspace files, search, static Python AST maps, and Python execution tools. |
