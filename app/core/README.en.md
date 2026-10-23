# Agent core

[繁體中文](README.md)

Orchestrates runs; tools and storage stay in their own modules.

| File/directory | Purpose |
| --- | --- |
| `__init__.py` | Python package entry; some packages also export shared helpers here. |
| `agent.py` | Task loop coordinating models, tools, modes, and completion. |
| `conclusion.py` | Collects current-run results and builds summary inputs and brief fallbacks. |
| `execution.py` | Pause checkpoints, argument validation, sync/async calls, and execution logs. |
| `intent.py` | Routes automatic requests to direct execution or planning. |
| `model_client.py` | Ollama streaming, completion markers, empty-response recovery, and timeout diagnostics. |
| `prompt.py` | Assembles system prompts, AGENTS.md, Skill catalogs, and tool lists. |
| `skill_registry.py` | Discovers Skills, parses metadata, and reads selected ranges with a heading index and relative paths. |
