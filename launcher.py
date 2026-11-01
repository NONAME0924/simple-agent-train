"""跨平台快速啟動入口；沿用現有資料庫、工作區與 Agent。"""
import argparse
import json
import os
from pathlib import Path
import socket
import threading
import time
import urllib.error
import urllib.request
import webbrowser


APP_DIR = Path(__file__).resolve().parent


def open_when_ready(url):
    for _ in range(100):
        try:
            with urllib.request.urlopen(url + "/openapi.json", timeout=0.5) as response:
                if json.load(response)["info"]["title"] == "AI Agent with Multi-Session Sidebar":
                    webbrowser.open(url)
                    return
        except (OSError, ValueError, KeyError):
            time.sleep(0.2)


def lan_address():
    """猜測這台電腦在區網的位址，只用來提示；失敗就退回主機名稱。"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))  # UDP 不會真的送出封包
            return probe.getsockname()[0]
    except OSError:
        return socket.gethostname()


def main():
    parser = argparse.ArgumentParser(description="AI Agent 快速啟動")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--port", type=int)
    parser.add_argument("--host", help="監聽位址；預設讀 .env 的 SERVER_HOST。0.0.0.0 會開放給同網路的所有裝置。")
    args = parser.parse_args()
    os.chdir(APP_DIR)

    # app/config.py 統一讀取 .env，既有環境變數優先；命令列參數最優先。
    from app.config import DEFAULT_MODEL, OLLAMA_BASE_URL, SERVER_HOST, SERVER_PORT

    host = args.host or SERVER_HOST
    os.environ["SERVER_HOST"] = host  # 讓伺服器端的開放提示讀到實際位址。
    port = args.port if args.port is not None else SERVER_PORT
    url = f"http://127.0.0.1:{port}"  # 本機瀏覽器一律用迴圈位址連。
    try:
        with socket.socket() as listener:
            listener.bind((host, port))
    except OSError:
        try:
            with urllib.request.urlopen(url + "/openapi.json", timeout=1) as response:
                same_app = json.load(response)["info"]["title"] == "AI Agent with Multi-Session Sidebar"
        except (OSError, ValueError, KeyError):
            same_app = False
        if same_app:
            print(f"AI Agent is already running: {url}", flush=True)
            if not args.no_browser:
                webbrowser.open(url)
            return
        raise RuntimeError(f"Port {port} is in use. Set SERVER_PORT or use --port to choose another port.")

    import uvicorn
    from app.web.server import app

    print(f"\nAI Agent: {url}\nModel: {DEFAULT_MODEL}\nOllama: {OLLAMA_BASE_URL}", flush=True)
    if host in {"0.0.0.0", "::"}:
        print(f"對外開放：同網路的人可用 http://{lan_address()}:{port} 連線（需要帳號登入）。", flush=True)
    elif host not in {"127.0.0.1", "localhost", "::1"}:
        print(f"對外開放：http://{host}:{port}（需要帳號登入）。", flush=True)
    print("Close this window or press Ctrl+C to stop.\n", flush=True)
    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    uvicorn.run(app, host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
