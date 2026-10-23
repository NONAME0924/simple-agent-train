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
    """執行已發現 Skill 內的 .py 腳本；先用 read_skill 了解用途及必要參數。
    name 是 Skill 名稱，script 是相對該 Skill 的路徑，例如 scripts/thumbnail.py。
    arguments 是字串陣列，每個參數一項，不含 python 或腳本路徑，也不需額外加引號。
    使用 Agent 的 Python；輸入／輸出相對路徑以目前工作區為準，Skill 資源應依原始腳本位置存取。
    不複製腳本或自動安裝依賴。background=True 立即回傳工作 ID；前景等待超時仍保留背景工作。
    wait_seconds 為 1～60 秒，用 get_job 查詢、stop_job 停止。未要求時不主動執行測試。
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
