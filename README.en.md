# AI Agent

[繁體中文](README.md) · English

A local Agent built with Python, FastAPI, and Ollama. A browser interface connects model requests to workspace tools, Python jobs, optional Skills, and MCP servers.

## Features

- Projects and conversations, with a shared workspace and L2 summary within each project.
- Automatic routing to direct execution or SDD planning; implementation starts after plan confirmation.
- Validated tool arguments, Python background jobs, pause/resume, and categorized logs.
- Code search, static Python maps, Markdown previews, and document text import.
- Image attachments when the selected model supports vision.
- Dynamic Skill loading, MCP connections, and a Blender configuration example.

## Getting started

You need a reachable Ollama service and an installed model. This project does not download models.

1. Copy `.env.example` to `.env`.
2. Set `OLLAMA_BASE_URL` and `DEFAULT_MODEL` to match your Ollama installation.
3. Start the application and open `http://127.0.0.1:8000`.

Linux/macOS requires Python 3.10+ with venv/ensurepip:

```sh
cp .env.example .env
# Edit .env before starting. Initial environment setup requires internet access.
sh run.sh --no-browser
```

Windows from source:

```powershell
Copy-Item .env.example .env
# Edit .env, then run:
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe launcher.py
```

A separate Windows distribution may include `runtime/` and `AI-Agent.exe`. These binaries are not included in the source repository. Use `--port 8001` to change the port. Restart the service and refresh the browser after updating.

## Configuration

| Variable | Purpose | Default |
| --- | --- | --- |
| `OLLAMA_BASE_URL` | Model service endpoint | `http://127.0.0.1:11434` |
| `DEFAULT_MODEL` | Ollama model name | Required |
| `AGENT_CONTEXT_TOKENS` | Configured total context length | `32768` |
| `AGENT_OUTPUT_TOKENS` | Generation limit for each ordinary model request | `4096` |
| `AGENT_MODEL_READ_TIMEOUT` | Seconds waiting for more model response data | `600` |
| `SERVER_PORT` | Web service port | `8000` |
| `BLENDER_HOST` / `BLENDER_PORT` | Blender addon endpoint | `127.0.0.1` / `9876` |

Existing environment variables override `.env`. The current output limit is capped at one quarter of the configured context. Context compaction starts at 80% of the available input budget. Actual capacity and speed depend on the model and hardware.

## Architecture

```text
Browser → FastAPI → Agent → Ollama
                     ├─ Built-in tools → Workspace / Python jobs
                     ├─ Skills → Instructions
                     ├─ MCP → External tools / Blender
                     └─ Storage → SQLite / Files / Logs
```

| Location | Responsibility |
| --- | --- |
| [app/core/](app/core/README.en.md) | Task loop, model requests, prompts, and conclusions |
| [app/tools/](app/tools/README.en.md) | Built-in tools, schemas, and validation |
| [app/mcp/](app/mcp/README.en.md) | Generic MCP configuration, connections, and adapters |
| [app/storage/](app/storage/README.en.md) | Conversations, context, workspaces, and jobs |
| [app/web/](app/web/README.en.md) | APIs and the plain JavaScript interface |
| [prompts/](prompts/README.en.md) | System prompts, separate from user `AGENTS.md` preferences |
| [skills/](skills/README.en.md) | Sources of locally installed Skills; Skill contents are ignored |
| [launcher/](launcher/README.en.md) | Startup preparation and clean packaging |

Directory READMEs describe individual files. See the [architecture guide](docs/architecture.en.md). The [detailed usage guide](docs/usage.md) is currently in Traditional Chinese.

Root files:

| File | Purpose |
| --- | --- |
| `launcher.py` / `run.sh` | Shared service entry / Linux and macOS setup entry |
| `requirements.txt` | Direct Python dependencies |
| `requirements.lock.txt` | Pinned deployment dependencies |
| `AGENTS.md` | Shared user preferences |
| `.env.example` / `mcp.example.json` | Public local-setting / MCP examples |
| `.gitignore` | Exclusions for local data and Skill contents |
| `啟動說明.txt` | Brief distribution startup instructions |
| `README.md` / `README.en.md` | Traditional Chinese / English project overview |

## Scope and limitations

- Intended for a local single user; no built-in login or multi-user authorization.
- Workspace path checks are not an operating-system sandbox. Python and MCP tools run with the host account's permissions.
- Pause takes effect at checkpoints; it does not immediately interrupt an active model request, tool, or background process.
- Each run has up to 15 rounds, followed by one summary request if unfinished. Successful tools do not guarantee a correct final artifact.
- Document import extracts text without OCR. Skill-specific Node.js packages, renderers, and other dependencies are separate requirements.
- Some frontend libraries use CDNs. Initial setup, web search, and external model endpoints require network access.

## Local data and attribution

`.gitignore` excludes `.env`, `mcp.json`, Skill contents, the Windows runtime, databases, workspaces, and logs. Logs and uploaded documents can contain sensitive data. See the [publication scope and review](docs/publishing.en.md).

The SDD Skill is a compact adaptation of the author's [NONAME0924/spec-driven-development](https://github.com/NONAME0924/spec-driven-development), using three specification files. The Blender Skill was written for this project; its tools come from [MCP for Blender](https://github.com/ahujasid/mcp-for-blender). The PPTX Skill comes from [Anthropic Skills](https://github.com/anthropics/skills/tree/main/skills/pptx); its bundled license has restrictions, and Skill contents are not committed.

There is currently no root license covering this application's own code. Third-party materials are not collectively labeled MIT. See [third-party and Skill sources](docs/third-party.en.md).
