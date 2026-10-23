# Application

[繁體中文](README.md)

Backend entry points and responsibility-based modules.

| File/directory | Purpose |
| --- | --- |
| `core/` | Orchestrates runs; tools and storage stay in their own modules. |
| `storage/` | Manages local data; user artifacts are stored outside this source directory. |
| `tools/` | Function signatures supply both schemas and argument validation. |
| `web/` | FastAPI routes and browser assets. |
| `__init__.py` | Python package entry; some packages also export shared helpers here. |
| `config.py` | Loads configuration and defines paths, model settings, and budgets. |
| `logging_setup.py` | JSONL logging, categories, levels, scoped files, and rotation. |
