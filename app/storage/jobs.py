"""本機 Python 背景程序。輸出存檔，log 記錄生命週期與完整輸出。"""
import json
import os
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from app.config import DATA_DIR
from app.logging_setup import log, log_context
from app.tools.registry import ToolResult
from app.storage.workspace import walk_workspace

JOB_DIR = DATA_DIR / "jobs"
ACTIVE = {"running", "stopping"}


def now():
    return datetime.now(timezone.utc).isoformat()


def workspace_files(cwd):
    files = {}
    for folder, dirs, names in walk_workspace(cwd):
        for name in names:
            path = Path(folder) / name
            try:
                stat = path.stat()
                files[path.relative_to(cwd).as_posix()] = (stat.st_mtime_ns, stat.st_size)
            except OSError:
                log("job.file_stat_failed", level=30, exc_info=True, path=str(path))
    return files


class JobManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.records, self.processes, self.settled, self.snapshots = {}, {}, {}, {}
        JOB_DIR.mkdir(parents=True, exist_ok=True)
        for path in JOB_DIR.glob("*/job.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                self.records[record["id"]] = record
                if record["status"] in ACTIVE:
                    record.update(status="interrupted", interrupted_at=now(), ended_at=None,
                                  error="伺服器已重啟；原程序狀態未知，未接管或重跑。")
                    self._save(record)
                    log("job.interrupted", **record)
            except (OSError, ValueError, KeyError):
                log("job.restore_failed", level=40, exc_info=True, path=str(path))

    def _save(self, record):
        path = JOB_DIR / record["id"] / "job.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

    def start(self, session_id, argv, cwd):
        if not session_id:
            raise ValueError("缺少目前對話，無法建立背景工作。")
        job_id = uuid4().hex
        folder = JOB_DIR / job_id
        folder.mkdir()
        record = {"id": job_id, "session_id": session_id, "argv": argv, "cwd": cwd,
                  "status": "running", "started_at": now(), "ended_at": None,
                  "exit_code": None, "context": dict(log_context.get())}
        try:
            before = workspace_files(cwd)
            with (folder / "stdout.txt").open("wb") as stdout, (folder / "stderr.txt").open("wb") as stderr:
                process = subprocess.Popen(argv, cwd=cwd, stdout=stdout, stderr=stderr,
                    env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"},
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                    start_new_session=os.name != "nt")
            with self.lock:
                self.records[job_id], self.processes[job_id] = record, process
                self.settled[job_id] = threading.Event()
                self.snapshots[job_id] = before
                self._save(record)
            log("job.start", job_id=job_id, argv=argv, cwd=cwd)
            threading.Thread(target=self._watch, args=(job_id,), daemon=True).start()
            return job_id
        except Exception:
            log("job.start_failed", level=40, exc_info=True, job_id=job_id, argv=argv)
            raise

    def _watch(self, job_id):
        record, process = self.records[job_id], self.processes[job_id]
        token = log_context.set(record["context"])
        started = time.perf_counter()
        try:
            code = process.wait()
            before = self.snapshots.pop(job_id, {})
            changed_files = [path for path, stat in workspace_files(record["cwd"]).items() if before.get(path) != stat]
            with self.lock:
                status = "killed" if record["status"] == "stopping" else "completed" if code == 0 else "failed"
                record.update(status=status, exit_code=code, ended_at=now(), duration=time.perf_counter() - started,
                              changed_files=changed_files)
                self._save(record)
                self.processes.pop(job_id, None)
            stdout, stderr = self.output(job_id, "stdout"), self.output(job_id, "stderr")
            log("job.end", job_id=job_id, status=status, ok=status == "completed", exit_code=code,
                stdout=stdout, stderr=stderr, changed_files=changed_files, duration=record["duration"],
                level=20 if status == "completed" else 40)
        except Exception:
            with self.lock:
                record.update(status="failed", ended_at=now(), error="背景工作監控失敗；請查看 log。")
                self._save(record)
            log("job.monitor_failed", level=40, exc_info=True, job_id=job_id)
        finally:
            self.settled[job_id].set()
            log_context.reset(token)

    def output(self, job_id, kind, max_bytes=None):
        path = JOB_DIR / job_id / f"{kind}.txt"
        if not path.exists():
            return ""
        with path.open("rb") as handle:
            if max_bytes:
                handle.seek(max(0, path.stat().st_size - max_bytes))
            return handle.read().decode("utf-8", errors="replace")

    def get(self, session_id, job_id):
        with self.lock:
            record = self.records.get(job_id)
            if record is None or record["session_id"] != session_id:
                raise ValueError("找不到此對話的背景工作。")
            return {key: value for key, value in record.items() if key != "context"}

    def list(self, session_id):
        with self.lock:
            return [self.get(session_id, item["id"]) for item in self.records.values() if item["session_id"] == session_id]

    def has_active(self, session_id):
        return any(item["status"] in ACTIVE for item in self.list(session_id))

    def wait(self, job_id, seconds):
        settled = self.settled.get(job_id)
        if settled:
            settled.wait(timeout=seconds)

    def stop(self, session_id, job_id):
        with self.lock:
            record = self.get(session_id, job_id)
            process = self.processes.get(job_id)
            if not process or process.poll() is not None:
                return record
            self.records[job_id]["status"] = "stopping"
            self._save(self.records[job_id])
        try:
            if os.name == "nt":
                result = subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
                if result.returncode and process.poll() is None:
                    raise RuntimeError(result.stderr.decode(errors="replace"))
            else:
                os.killpg(process.pid, signal.SIGTERM)
            log("job.stop_requested", job_id=job_id)
        except Exception:
            with self.lock:
                if process.poll() is None:
                    self.records[job_id]["status"] = "running"
                    self._save(self.records[job_id])
            log("job.stop_failed", level=40, exc_info=True, job_id=job_id)
            raise
        return self.get(session_id, job_id)

    def shutdown(self):
        for record in list(self.records.values()):
            if record["status"] in ACTIVE:
                try:
                    self.stop(record["session_id"], record["id"])
                    self.wait(record["id"], 5)
                except Exception:
                    log("job.shutdown_failed", level=40, exc_info=True, job_id=record["id"])


job_manager = JobManager()


def get_job(job_id: str) -> str:
    """查詢目前對話背景工作的狀態、退出碼與 stdout/stderr 尾端；仍執行中不代表完成。"""
    from app.tools.history_memory import memory_session
    record = job_manager.get(memory_session.get(), job_id)
    return ToolResult(json.dumps({**record, "stdout": job_manager.output(job_id, "stdout", 16000),
        "stderr": job_manager.output(job_id, "stderr", 16000)}, ensure_ascii=False),
        ok=record["status"] not in {"failed", "killed", "interrupted"})


def stop_job(job_id: str) -> str:
    """停止目前對話的一個背景工作及其子程序；Agent 的暫停按鈕不會停止背景工作。"""
    from app.tools.history_memory import memory_session
    return json.dumps(job_manager.stop(memory_session.get(), job_id), ensure_ascii=False)
