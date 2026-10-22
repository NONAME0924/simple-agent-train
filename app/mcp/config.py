"""本機連線設定與專案／對話綁定，不把憑證放進模型提示語。"""
import json
import os
import re
import sys
from pydantic import BaseModel, ConfigDict, Field
from app.config import APP_DIR, DATA_DIR


class ServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    instance: str
    timeout: int = Field(default=120, ge=1, le=3600)
    connect_timeout: int = Field(default=20, ge=1, le=120)
    include: list[str] = Field(default_factory=list)
    read_only: list[str] = Field(default_factory=list)
    skill: str = ""


def _expand(value):
    values = {**os.environ, "PYTHON": sys.executable,
              "BLENDER_HOST": os.getenv("BLENDER_HOST", "127.0.0.1"),
              "BLENDER_PORT": os.getenv("BLENDER_PORT", "9876")}
    def replace(match):
        if match[1] not in values:
            raise ValueError(f"MCP 缺少環境變數：{match[1]}")
        return values[match[1]]
    if isinstance(value, str):
        return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", replace, value)
    if isinstance(value, list):
        return [_expand(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand(item) for key, item in value.items()}
    return value


def servers():
    path = APP_DIR / "mcp.json"
    data = json.loads((path if path.is_file() else APP_DIR / "mcp.example.json").read_text(encoding="utf-8-sig"))
    result = {}
    for name, item in data.get("mcpServers", {}).items():
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,23}", name):
            raise ValueError("MCP 名稱須為 24 字以內的小寫英數、底線或連字號。")
        config = ServerConfig.model_validate(_expand(item))
        if bool(config.command) == bool(config.url):
            raise ValueError(f"MCP {name} 必須擇一設定 command 或 url。")
        result[name] = config
    return result


def scope_key(session):
    return "project:" + session["project_id"] if session.get("project_id") else "session:" + session["id"]


def bindings():
    path = DATA_DIR / "mcp-bindings.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def bind(instance, scope):
    data = bindings()
    if scope is not None and data.get(instance) not in (None, scope):
        raise ValueError("此 Blender／MCP 實例已綁定其他專案或對話，請先在原處解除連線。")
    if scope is None:
        data.pop(instance, None)
    else:
        data[instance] = scope
    path = DATA_DIR / "mcp-bindings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
