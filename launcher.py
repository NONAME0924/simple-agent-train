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


def main():
    parser = argparse.ArgumentParser(description="AI Agent 快速啟動")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    os.chdir(APP_DIR)

    # app/config.py 統一讀取 .env，既有環境變數優先；介面只在本機提供。
    from app.config import DEFAULT_MODEL, OLLAMA_BASE_URL, SERVER_PORT

    port = args.port if args.port is not None else SERVER_PORT
    url = f"http://127.0.0.1:{port}"
    try:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", port))
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
    print("Close this window or press Ctrl+C to stop.\n", flush=True)
    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=port, reload=False)


if __name__ == "__main__":
    main()
