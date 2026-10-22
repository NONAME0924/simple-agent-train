# System prompts

[繁體中文](README.md)

No credentials or local settings; user preferences belong in AGENTS.md.

| File/directory | Purpose |
| --- | --- |
| `reasoning/` | Prompt-level guidance, not a guaranteed reasoning-token budget. |
| `agent.md` | Direct execution/chat and explicit completion rules. |
| `compact.md` | Working-context compaction instructions. |
| `continue_task.md` | Recovery guidance after text-only responses. |
| `empty_response.md` | One-time empty-response recovery instructions. |
| `intent.md` | Intent classification for automatic mode. |
| `limit_summary.md` | Tool-free current-run summary after the round limit. |
| `mcp.md` | MCP/Blender connection and operation guidance. |
| `plan.md` | SDD planning and persistence rules. |
| `preferences.md` | Separates lasting preferences from one-off requirements. |
| `project_memory.md` | Incremental project L2 instructions. |
| `reasoning.md` | Shared reasoning-level guidance. |
| `skill_install.md` | Skill-source discovery and installation guidance. |
| `skills.md` | Distinguishes Skill instructions from callable tools. |
| `system.md` | Base system behavior. |
| `tasks.md` | Task-list handling rules. |
