"""依專案／對話分流並分類 JSONL log，略過例行讀取與第三方存取雜訊。"""
import hashlib
import json
import logging
import re
from collections import OrderedDict
from contextvars import ContextVar
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from app.config import APP_DIR

log_context = ContextVar("log_context", default={})


def is_quiet_read(method, path, status):
    return method in {"GET", "HEAD"} and 200 <= int(status) < 400


def event_category(event):
    prefix = str(event).split(".", 1)[0]
    if prefix in {"model", "intent"}:
        return "model"
    if prefix in {"tool", "job", "workspace", "skill", "search", "web", "document", "image", "task", "preferences"} or event in {"mcp.result", "mcp.call_failed"}:
        return "tool"
    if prefix == "mcp":
        return "mcp"
    if prefix in {"memory", "context"}:
        return "memory"
    return "system"


class QuietJobPolls(logging.Filter):
    def filter(self, record):
        args = record.args
        return not (isinstance(args, tuple) and len(args) == 5 and is_quiet_read(args[1], args[2], args[4]))


def _folder_name(value):
    value = str(value)
    return value if re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value) else hashlib.sha256(value.encode()).hexdigest()


def log_path(scope):
    folder = APP_DIR / "logs"
    if scope.get("project_id"):
        return folder / "projects" / _folder_name(scope["project_id"]) / "agent.jsonl"
    if scope.get("session_id"):
        return folder / "conversations" / _folder_name(scope["session_id"]) / "agent.jsonl"
    return folder / "system.jsonl"


class ScopedLogHandler(logging.Handler):
    agent_log = True

    def __init__(self):
        super().__init__()
        self.handlers = OrderedDict()

    def emit(self, record):
        try:
            if record.name == "uvicorn.access":
                return  # HTTP 結果由 middleware 統一記錄，避免重複。
            record.context = dict(log_context.get())
            fields = getattr(record, "fields", {})
            scope = {**record.context, **fields.get("context", {}), **fields}
            path = log_path(scope)
            handler = self.handlers.pop(path, None)
            if handler is None:
                if len(self.handlers) >= 32:
                    self.handlers.popitem(last=False)[1].close()
                path.parent.mkdir(parents=True, exist_ok=True)
                handler = RotatingFileHandler(path, maxBytes=10 * 1024 * 1024, backupCount=8, encoding="utf-8")
                handler.setFormatter(JsonFormatter())
            self.handlers[path] = handler
            handler.emit(record)
        except Exception:
            self.handleError(record)

    def close(self):
        self.acquire()
        try:
            for handler in self.handlers.values():
                handler.close()
            self.handlers.clear()
        finally:
            self.release()
            super().close()


class JsonFormatter(logging.Formatter):
    def format(self, record):
        item = {"time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
                "level": record.levelname, "logger": record.name, "event": record.getMessage(),
                **getattr(record, "context", {}), **getattr(record, "fields", {})}
        item.setdefault("category", event_category(item["event"]))
        if record.exc_info:
            item["traceback"] = self.formatException(record.exc_info)
        return json.dumps(item, ensure_ascii=False, default=str)


def setup_logging():
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, QuietJobPolls) for item in access.filters):
        access.addFilter(QuietJobPolls())
    for name in ("httpx", "httpcore", "mcp"):
        logging.getLogger(name).setLevel(logging.WARNING)
    root = logging.getLogger()
    if any(getattr(handler, "agent_log", False) for handler in root.handlers):
        return
    root.addHandler(ScopedLogHandler())
    root.setLevel(logging.INFO)


def log(event, *, level=logging.INFO, exc_info=False, **fields):
    logging.getLogger("aiagent").log(level, event, extra={"fields": fields}, exc_info=exc_info)
