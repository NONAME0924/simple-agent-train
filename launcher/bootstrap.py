"""Linux／macOS 首次啟動準備專案環境；套件清單未變時直接啟動。"""
import hashlib
import os
from pathlib import Path
import subprocess
import sys

APP_DIR = Path(__file__).resolve().parents[1]
REQUIREMENTS = APP_DIR / "requirements.lock.txt"
REQUIRED_MODULES = ("fastapi", "uvicorn", "dotenv", "httpx")


def run(command):
    subprocess.run(command, check=True, cwd=APP_DIR)


def prepare():
    if sys.version_info < (3, 10):
        raise RuntimeError("需要 Python 3.10 以上版本，請透過 PYTHON_EXEC 指定。")
    # 明確指定既有虛擬環境時沿用；其餘都在專案內建立，不安裝到系統 Python。
    custom_env = bool(os.getenv("PYTHON_EXEC")) and sys.prefix != sys.base_prefix
    folder = Path(sys.prefix) if custom_env else APP_DIR / ".venv"
    python = folder / "bin" / "python"
    if not python.is_file():
        print(f"建立專案 Python 環境：{folder}", flush=True)
        try:
            run([sys.executable, "-m", "venv", str(folder)])
        except subprocess.CalledProcessError as error:
            raise RuntimeError("無法建立虛擬環境，請先安裝目前 Python 對應的 venv／ensurepip 支援，再重新啟動。") from error
    signature = hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()
    stamp = folder / ".agent-requirements.sha256"
    recorded = stamp.read_text(encoding="utf-8").strip() if stamp.is_file() else ""
    # 只檢查模組位置，不匯入或啟動服務。
    check = "import importlib.util, sys; sys.exit(any(importlib.util.find_spec(name) is None for name in " + repr(REQUIRED_MODULES) + "))"
    available = subprocess.run([str(python), "-B", "-c", check], cwd=APP_DIR).returncode == 0
    if recorded != signature or not available:
        print("首次使用或依賴已更新，正在安裝 Agent 套件；需要網路。", flush=True)
        try:
            pip_ready = subprocess.run([str(python), "-m", "pip", "--version"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
            if not pip_ready:
                run([str(python), "-m", "ensurepip", "--upgrade"])
            run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(REQUIREMENTS)])
        except subprocess.CalledProcessError as error:
            raise RuntimeError("套件安裝未完成，Agent 尚未啟動。請確認網路與上方錯誤後，再執行 run.sh；不需刪除專案或資料。") from error
        stamp.write_text(signature + "\n", encoding="utf-8")
    print(f"使用專案 Python：{python}", flush=True)
    return python


def main():
    # 避免兩次啟動同時建立環境或安裝套件，進入 Agent 前釋放鎖。
    import fcntl
    with (APP_DIR / ".agent-setup.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        python = prepare()
    os.execv(str(python), [str(python), "-u", "-B", str(APP_DIR / "launcher.py"), *sys.argv[1:]])


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError) as error:
        print(f"啟動準備失敗：{error}", file=sys.stderr, flush=True)
        sys.exit(1)
