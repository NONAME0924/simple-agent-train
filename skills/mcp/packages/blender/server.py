#!/usr/bin/env python3
"""Blender Lab 橋接的 stdio MCP server（MCP 套件 blender 的程式，零第三方相依）。

  MCP 客戶端 ⇄（stdio）⇄ 本程式 ⇄（TCP，\\0 分幀 JSON）⇄ Blender 內的 Blender Lab 橋接

橋接協議（已由實際連線驗證）：純 TCP，以 null byte（\\0）分幀，不是 WebSocket，也不是換行分隔。
  請求 {"type": "execute", "code": "<python>", "strict_json": true} + \\0
  回應 {"status": "ok" | "error", "result": ..., "stdout": ..., "stderr": ...} + \\0

環境變數：
  BLENDER_HOST   橋接位址，預設 127.0.0.1
  BLENDER_PORT   橋接埠號，預設 9876（以 Blender 附加元件偏好設定為準）
  BLENDER_PATH   Blender 可執行檔完整路徑；只有 launch_blender 會用到，且不接受由模型指定

安全：橋接本身沒有任何防護，execute_blender_code 會直接改動使用者的場景與檔案。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time

HOST = os.environ.get("BLENDER_HOST", "127.0.0.1").strip() or "127.0.0.1"
MAX_RESPONSE_BYTES = 20 * 1024 * 1024
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
LAUNCH_WAIT_SECONDS = 45


def _port():
    raw = os.environ.get("BLENDER_PORT", "9876").strip() or "9876"
    try:
        port = int(raw)
        if 1 <= port <= 65535:
            return port
    except ValueError:
        pass
    print(f"[blender] BLENDER_PORT={raw!r} 不是有效埠號，改用 9876。", file=sys.stderr, flush=True)
    return 9876


PORT = _port()


class BridgeError(Exception):
    """橋接連線或協議層的錯誤；訊息要能讓模型知道下一步怎麼做。"""


def bridge_execute(code, strict_json=True, timeout=60.0):
    payload = json.dumps({"type": "execute", "code": code, "strict_json": strict_json}).encode("utf-8") + b"\0"
    try:
        with socket.create_connection((HOST, PORT), timeout=min(timeout, 10.0)) as sock:
            sock.settimeout(timeout)
            sock.sendall(payload)
            buffer = bytearray()
            while b"\0" not in buffer:
                if len(buffer) > MAX_RESPONSE_BYTES:
                    raise BridgeError("橋接回應超過 20 MiB，已中止；請讓腳本只回傳需要的資料。")
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buffer.extend(chunk)
    except ConnectionRefusedError:
        raise BridgeError(f"連不上 Blender 橋接 {HOST}:{PORT}。請確認 Blender 已開啟、Blender Lab 附加元件的橋接已啟動"
                          "（附加元件偏好設定可看位址與埠號），或使用 launch_blender。不要反覆重試。")
    except socket.timeout:
        raise BridgeError(f"等待 Blender 回應逾時（{timeout:g} 秒）。腳本可能仍在執行，或 Blender 被對話框卡住；"
                          "請先到 Blender 視窗確認，再決定是否加大 timeout_seconds。")
    except OSError as error:
        raise BridgeError(f"連線 Blender 橋接 {HOST}:{PORT} 失敗：{error}")
    if not buffer:
        raise BridgeError("橋接沒有回應就關閉了連線；可能不是 Blender Lab 橋接（協議不符），請確認埠號。")
    raw = bytes(buffer).split(b"\0", 1)[0]
    try:
        response = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        raise BridgeError("橋接的回應不是有效的 JSON。")
    if not isinstance(response, dict):
        raise BridgeError("橋接的回應格式不符。")
    return response


def format_response(response):
    status = response.get("status")
    lines = [f"status: {status}"]
    result = response.get("result")
    if result is not None:
        lines.append("result: " + (result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)))
    for key in ("stdout", "stderr"):
        value = response.get(key)
        if value:
            lines.append(f"{key}:\n{str(value).rstrip()}")
    if status != "ok" and len(lines) == 1:      # 錯誤但沒有其他欄位：原樣附上，避免吞掉訊息
        lines.append(json.dumps(response, ensure_ascii=False))
    return "\n".join(lines), status != "ok"


REDRAW_CODE = """
import bpy
try:
    for _w in bpy.context.window_manager.windows:
        for _a in _w.screen.areas:
            _a.tag_redraw()
except Exception:
    pass
"""

STATUS_CODE = """
import bpy, json
print(json.dumps({
    "blender_version": bpy.app.version_string,
    "file": bpy.data.filepath or None,
    "unsaved_changes": bpy.data.is_dirty,
    "scene": bpy.context.scene.name,
    "objects": len(bpy.data.objects),
    "has_gui": bool(bpy.context.window_manager.windows),
}, ensure_ascii=False))
"""

SCENE_CODE = """
import bpy, json
_limit = __LIMIT__
def _vec(v):
    return [round(float(x), 4) for x in v]
_all = list(bpy.data.objects)
_rows = []
for _o in _all[:_limit]:
    _rows.append({
        "name": _o.name, "type": _o.type,
        "location": _vec(_o.location), "dimensions": _vec(_o.dimensions),
        "parent": _o.parent.name if _o.parent else None,
        "collections": [_c.name for _c in _o.users_collection],
        "hidden": bool(_o.hide_viewport),
    })
print(json.dumps({"scene": bpy.context.scene.name, "total": len(_all), "shown": len(_rows), "objects": _rows},
                 ensure_ascii=False))
"""


def run_code(code, strict_json=True, timeout=60.0, redraw=False):
    response = bridge_execute(code, strict_json, timeout)
    text, failed = format_response(response)
    if redraw and not failed:
        try:
            bridge_execute(REDRAW_CODE, True, 10.0)     # 盡力而為：背景執行的 bpy.ops 不會自動觸發 3D 視口重繪
        except BridgeError:
            pass
    return text, failed


def tool_execute(arguments):
    code = arguments.get("code")
    if not isinstance(code, str) or not code.strip():
        return "code 必須是非空的 Python 程式字串。", True
    strict = arguments.get("strict_json", True)
    redraw = arguments.get("redraw", True)
    if not isinstance(strict, bool) or not isinstance(redraw, bool):
        return "strict_json 與 redraw 必須是布林值（true/false）。", True
    timeout = arguments.get("timeout_seconds", 60)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1 <= timeout <= 600:
        return "timeout_seconds 必須是 1～600 的數字。", True
    return run_code(code, strict, float(timeout), redraw)


def tool_status(_arguments):
    return run_code(STATUS_CODE, True, 15.0)


def tool_scene(arguments):
    limit = arguments.get("max_objects", 100)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        return "max_objects 必須是 1～1000 的整數。", True
    return run_code(SCENE_CODE.replace("__LIMIT__", str(limit)), True, 30.0)


def port_open():
    try:
        with socket.create_connection((HOST, PORT), timeout=1.0):
            return True
    except OSError:
        return False


def tool_launch(_arguments):
    if port_open():
        return f"橋接已在 {HOST}:{PORT} 運作，不重複啟動 Blender。", False
    path = os.environ.get("BLENDER_PATH", "").strip()
    if not path:
        return "未設定環境變數 BLENDER_PATH（Blender 可執行檔的完整路徑），無法啟動；請使用者手動開啟 Blender。", True
    if not os.path.isfile(path):
        return f"找不到 Blender 可執行檔：{path}。請確認 BLENDER_PATH。", True
    if os.name == "posix" and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return "沒有 DISPLAY／WAYLAND_DISPLAY，無法開啟 Blender 視窗；請在有圖形介面的 session 執行，或請使用者手動開啟。", True
    try:
        if os.name == "nt":
            # 透過 cmd start 讓 Blender 脫離本程序的行程樹，客戶端結束時不會被一起終止。
            subprocess.Popen(["cmd", "/c", "start", "", path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
            process = None
        else:
            env = dict(os.environ)
            library = os.path.join(os.path.dirname(path), "lib")
            if os.path.isdir(library):
                env["LD_LIBRARY_PATH"] = library + os.pathsep + env.get("LD_LIBRARY_PATH", "")
            process = subprocess.Popen([path], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as error:
        return f"無法啟動 Blender：{error}", True
    deadline = time.monotonic() + LAUNCH_WAIT_SECONDS
    while time.monotonic() < deadline:
        if port_open():
            return f"Blender 已啟動，橋接 {HOST}:{PORT} 已就緒。", False
        if process is not None and process.poll() is not None:
            return f"Blender 啟動後立即結束（結束碼 {process.returncode}）。", True
        time.sleep(0.5)
    return (f"Blender 已啟動，但 {LAUNCH_WAIT_SECONDS} 秒內橋接 {HOST}:{PORT} 仍未就緒；"
            "請確認 Blender Lab 附加元件已安裝並啟用橋接（可在偏好設定開啟自動啟動）。"), True


TOOLS = [
    {"name": "execute_blender_code",
     "description": "在已開啟的 Blender 內執行 Python（完整 bpy）。多個操作請合併成一段腳本一次送出。"
                    "橋接沒有任何防護，會直接改動場景與檔案；破壞性操作先向使用者確認。成功後預設重繪 3D 視口。",
     "inputSchema": {"type": "object", "properties": {
         "code": {"type": "string", "description": "要執行的 Python 程式碼"},
         "strict_json": {"type": "boolean", "description": "回傳結果要求嚴格 JSON，預設 true；一般不需更動"},
         "redraw": {"type": "boolean", "description": "成功後重繪所有 3D 視口，預設 true"},
         "timeout_seconds": {"type": "number", "description": "等待上限 1～600 秒，預設 60；需小於 mcp.json 的 timeout"}},
         "required": ["code"]}},
    {"name": "get_blender_status",
     "description": "健康檢查：Blender 版本、目前檔案、場景名稱、物件數、是否有圖形視窗。連線前先用它確認橋接可用。",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "get_scene_info",
     "description": "列出場景物件（名稱、類型、位置、尺寸、父物件、所屬集合、是否隱藏）。",
     "inputSchema": {"type": "object", "properties": {
         "max_objects": {"type": "integer", "description": "最多列出幾個物件，1～1000，預設 100"}}}},
    {"name": "launch_blender",
     "description": "啟動 Blender（可執行檔路徑只來自環境變數 BLENDER_PATH）；橋接已在運作時不會重複啟動，最多等待 45 秒讓橋接就緒。",
     "inputSchema": {"type": "object", "properties": {}}},
]
HANDLERS = {"execute_blender_code": tool_execute, "get_blender_status": tool_status,
            "get_scene_info": tool_scene, "launch_blender": tool_launch}
INSTRUCTIONS = ("Blender Lab 橋接。先 get_blender_status 確認可用；建模時把多個操作寫成一段完整 Python，"
                "用 execute_blender_code 一次送出。")


def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def reply(request_id, result=None, error=None):
    send({"jsonrpc": "2.0", "id": request_id, **({"error": error} if error else {"result": result})})


def handle(message):
    method, request_id = message.get("method"), message.get("id")
    if request_id is None:               # 通知（notifications/*）不需回應
        return
    params = message.get("params") or {}
    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0]
        reply(request_id, {"protocolVersion": version, "capabilities": {"tools": {}},
                           "serverInfo": {"name": "blender-lab-bridge", "version": "1.0"},
                           "instructions": INSTRUCTIONS})
    elif method == "ping":
        reply(request_id, {})
    elif method == "tools/list":
        reply(request_id, {"tools": TOOLS})
    elif method == "tools/call":
        handler = HANDLERS.get(params.get("name"))
        if handler is None:
            reply(request_id, error={"code": -32602, "message": f"未知的工具：{params.get('name')}"})
            return
        arguments = params.get("arguments") or {}
        try:
            if not isinstance(arguments, dict):
                text, failed = "arguments 必須是物件。", True
            else:
                text, failed = handler(arguments)
        except BridgeError as error:
            text, failed = str(error), True
        except Exception as error:      # 工具內部錯誤也回報為工具錯誤，不讓 server 崩潰
            text, failed = f"內部錯誤：{type(error).__name__}: {error}", True
        reply(request_id, {"content": [{"type": "text", "text": text}], "isError": failed})
    else:
        reply(request_id, error={"code": -32601, "message": "Method not found"})


def main():
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            print(f"[blender] 略過非 JSON 輸入：{line[:100]}", file=sys.stderr, flush=True)
            continue
        if isinstance(message, dict):
            handle(message)


if __name__ == "__main__":
    main()
