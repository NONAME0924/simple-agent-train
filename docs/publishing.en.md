# Publication scope and local configuration

[繁體中文](publishing.md) · [Home](../README.en.md)

## Files intended for Git

Keep `app/`, `prompts/`, launcher source, dependency lists, and documentation. `app/mcp/` is generic connection code; `mcp.example.json` is a credential-free example. Both remain in source.

| Local content | Rule |
| --- | --- |
| `.env`, `.env.*` | Ignored; only `.env.example` is included |
| `mcp.json`, `launcher.ini` | Ignored; only generic examples are included |
| `skills/*` | Skill contents ignored; only the two source-index READMEs remain |
| `runtime/*`, `AI-Agent.exe`, `.venv/` | Runtime and build artifacts ignored; runtime keeps only its READMEs |
| `workspace/*` | Artifacts, SDD, and uploads ignored; only directory READMEs remain |
| `memory.db*`, `data/`, `logs/`, models, and ZIPs | Execution data ignored |
| secrets/credentials directories and common private-key/certificate files | Ignored |

## Configuration boundaries

- Put actual model endpoints, model names, and machine-specific parameters in `.env` or environment variables.
- MCP headers and env support `${VARIABLE_NAME}` references. Do not put credentials in examples or prompts.
- `.env` is plaintext. Git ignores do not encrypt files or remove tracked files and earlier commits.
- Logs, tool outputs, documents, and images may contain user data and should not be published with source.

## Review performed

On 2026-10-22, application code, launchers, prompts, and example settings were read and checked using text patterns. No embedded credentials, private model endpoints, or personal absolute paths were found in application source. Generic authorization field names, public upstream URLs, and loopback defaults are not credentials.

The review does not cover `.env`, user data, a full third-party runtime audit, Git history, or future files. It cannot guarantee detection of every kind of secret. No application service, model request, code tests, upload, or Git commit was performed.

Review staged files and diffs before committing. Adding an ignore rule does not untrack a file already in Git.

## Archives differ from Git

`launcher/package.py` has its own include list and does not directly apply `.gitignore`. Existing execution packages retain local Skills for the current user's use; they are not automatically suitable for public redistribution. `--platform linux` excludes the Windows runtime and EXE but retains Skills.

The packager separately excludes `.env`, actual MCP settings, common credential filenames, execution data, and model files. Secrets under arbitrary custom filenames still require review.

To create a source archive matching the current publication scope:

```sh
python launcher/package.py --platform source AI-Agent-source.zip
```

This option retains only the skills/runtime READMEs, excluding Skill contents, Windows packages, and the EXE. Generic MCP code and mcp.example.json remain included.
