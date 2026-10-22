"""直接使用 .specify/tasks.md 作為任務清單，不另建待辦資料庫。"""
import hashlib
import json
import re
import threading
from pathlib import Path
from typing import Literal
from app.logging_setup import log
from app.storage.workspace import resolve_path

TASK_FILE = ".specify/tasks.md"
TaskStatus = Literal["pending", "running", "completed", "blocked"]
PATTERN = re.compile(r"^(\s*[-*+]\s+\[)([ xX>!])(\]\s+)(.*)$")
MARKS = {"pending": " ", "running": ">", "completed": "x", "blocked": "!"}
STATUSES = {" ": "pending", ">": "running", "x": "completed", "X": "completed", "!": "blocked"}
_lock = threading.Lock()


def task_list():
    path = Path(resolve_path(TASK_FILE))
    text = path.read_text(encoding="utf-8-sig") if path.is_file() else ""
    tasks = []
    for line, value in enumerate(text.splitlines(), 1):
        match = PATTERN.match(value)
        if match:
            tasks.append({"line": line, "title": match[4], "status": STATUSES[match[2]]})
    return {"path": TASK_FILE, "revision": hashlib.sha256(text.encode()).hexdigest(), "tasks": tasks}


def change_task(task_line, status, revision=""):
    if status not in MARKS:
        raise ValueError("任務狀態必須為 pending、running、completed 或 blocked。")
    with _lock:
        current = task_list()
        if revision and revision != current["revision"]:
            raise ValueError("任務文件已改變，請重新載入後再修改。")
        path = Path(resolve_path(TASK_FILE))
        lines = path.read_text(encoding="utf-8-sig").splitlines(keepends=True)
        if task_line < 1 or task_line > len(lines) or not PATTERN.match(lines[task_line - 1].rstrip("\r\n")):
            raise ValueError("該行不是任務項目。")
        lines[task_line - 1] = PATTERN.sub(lambda match: match[1] + MARKS[status] + match[3] + match[4], lines[task_line - 1], count=1)
        path.write_text("".join(lines), encoding="utf-8")
        log("task.updated", path=str(path), task_line=task_line, status=status)
        return task_list()


def read_plan_tasks() -> str:
    """讀取目前專案 SDD 任務、行號與狀態；資料來源為 .specify/tasks.md。"""
    return json.dumps(task_list(), ensure_ascii=False)


def update_task_status(task_line: int, status: TaskStatus, revision: str = "") -> str:
    """更新 SDD 任務狀態 pending/running/completed/blocked；task_line 為文件行號，revision 可避免覆蓋新版。"""
    return json.dumps(change_task(task_line, status, revision), ensure_ascii=False)
