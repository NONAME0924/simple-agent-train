# Storage and runtime data

[繁體中文](README.md)

Manages local data; user artifacts are stored outside this source directory.

| File/directory | Purpose |
| --- | --- |
| `__init__.py` | Python package entry; some packages also export shared helpers here. |
| `context_manager.py` | Token estimates, 80% compaction, archives, and long-output retrieval. |
| `document_import.py` | Extracts document text with Python packages and stores imports and originals. |
| `images.py` | Image validation, resizing, storage, references, and model-message conversion. |
| `jobs.py` | Python processes, job status, output, stopping, and changed-file records. |
| `memory.py` | SQLite projects, messages, history search, and working-context storage. |
| `plan_tasks.py` | Reads and updates tasks.md statuses with revision checks. |
| `project_memory.py` | Project L2 updates, pinned memory, and source cursors. |
| `workspace.py` | Workspace scope, checked relative paths, and file traversal. |
