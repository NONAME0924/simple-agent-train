"""執行 Skill 內的 Python 腳本，沿用對話工作區與背景工作。"""
from pathlib import Path
import sys
from app.core.skill_registry import skill_registry
from app.logging_setup import log
from app.storage.jobs import job_manager, get_job
from app.storage.workspace import get_workspace_dir
from app.tools.history_memory import memory_session


def run_skill_script(name: str, script: str, arguments: list[str] | None = None,
                     background: bool = False, wait_seconds: int = 30) -> str:
    """執行 Skill 內的 .py 腳本；先用 read_skill 了解用途與參數。
    script 是相對該 Skill 的路徑（如 scripts/thumbnail.py）；arguments 每項一個字串，不含 python 或腳本路徑。
    輸入／輸出路徑以目前工作區為準，不複製腳本、不自動安裝依賴。
    background=True 立即回傳工作 ID；wait_seconds 為 1～60，逾時保留背景工作，用 get_job／stop_job 管理。
    """
    if not 1 <= wait_seconds <= 60:
        raise ValueError("wait_seconds 必須為 1～60 秒。")
    skill = skill_registry.discover().get(name)
    if skill is None:
        raise ValueError(f"找不到 Skill：{name}。請使用目前可用 Skill 的名稱。")
    folder = skill["path"].parent.resolve()
    path = (folder / script).resolve()
    if Path(script).is_absolute() or not path.is_relative_to(folder):
        raise ValueError("script 必須是該 Skill 內的相對路徑，不能指向目錄外。")
    if path.suffix.lower() != ".py":
        raise ValueError("只支援 .py 腳本；script 不需包含 python 指令或命令列參數。")
    if not path.is_file():
        raise FileNotFoundError(f"Skill {name} 中找不到腳本：{script}。請核對 Skill 說明，確認已安裝完整腳本與資源。")
    job_id = job_manager.start(memory_session.get(),
        [sys.executable, "-B", str(path), *(arguments or [])], get_workspace_dir())
    log("skill.script_started", name=name, script=str(path), job_id=job_id)
    if not background:
        job_manager.wait(job_id, wait_seconds)
    return get_job(job_id)
