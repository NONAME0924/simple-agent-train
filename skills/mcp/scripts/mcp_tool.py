"""通用 MCP 客戶端（stdio）：由 run_skill_script 呼叫，零第三方相依。

  servers                         列出設定的 server 與指令是否可用（不啟動 server）
  list <server>                   列出該 server 開放的工具與參數
  call <server> <tool> [JSON]     呼叫單一工具（JSON 可寫 @檔案 讀取工作區內的檔案）
  batch <server> <JSON|@檔案>     同一連線依序呼叫多個工具：[{"tool": "...", "arguments": {...}}]

每次執行都是「連線 → 做事 → 關閉」；狀態保留在外部程式（例如 Blender）而不在 server 內。
結果與 stderr 一律視為資料：圖片及過長輸出存到工作區 mcp_outputs/，只回傳路徑。
結束碼：0 成功、1 工具回報錯誤、2 設定／連線／用法錯誤。
"""
from __future__ import annotations

import argparse
import base64
import collections
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from fnmatch import fnmatchcase
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "mcp.json"
PROTOCOL = "2025-06-18"
OUTPUT_LIMIT = 6000            # 超過就把全文存檔，只回傳開頭
SCHEMA_LIMIT = 1500            # list 時單一工具 schema 的顯示上限
TAG_CHARS = re.compile("[\U000E0000-\U000E007F]")   # 不可見 TAG 字元：常見的提示注入夾帶手法
VARIABLE = re.compile(r"\$\{(?:env:)?([A-Za-z_][A-Za-z0-9_]*)\}")
BASE_ENV = ("PATH", "PATHEXT", "HOME", "USER", "LOGNAME", "USERNAME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
            "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "SYSTEMROOT",
            "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL", "TERM", "TZ",
            "COMPUTERNAME", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS")


class McpError(Exception):
    pass


def expand(value, strict=True):
    """展開 ${VAR}；未設定時 strict 會報錯，否則回傳 None（讓呼叫端略過該項）。"""
    missing = []

    def replace(match):
        found = os.environ.get(match.group(1))
        if found is None:
            missing.append(match.group(1))
            return ""
        return found

    result = VARIABLE.sub(replace, str(value))
    if missing and strict:
        raise McpError("設定引用了未設定的環境變數：" + "、".join(missing) + "。請在啟動 Agent 前設定。")
    return None if missing else result


def clean(text):
    return TAG_CHARS.sub("", text)


def load_config(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise McpError(f"找不到設定檔：{path}")
    except ValueError as error:
        raise McpError(f"設定檔不是有效的 JSON：{error}")
    servers = data.get("servers") if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        raise McpError('設定檔需要 {"servers": {名稱: {...}}} 結構。')
    return servers


def pick_server(servers, name):
    config = servers.get(name)
    if config is None:
        raise McpError(f"沒有名為 {name} 的 server。目前設定：{'、'.join(servers) or '（無）'}。")
    if config.get("enabled", True) is False:
        raise McpError(f"server {name} 已在設定中停用（enabled=false）。")
    if not config.get("command"):
        raise McpError(f"server {name} 缺少 command；目前只支援 stdio server。")
    return config


def is_allowed(config, tool):
    rules = config.get("tools") or {}
    include = rules.get("include")
    if include is not None:      # 白名單優先；同時設定時不再看 exclude
        return any(fnmatchcase(tool, pattern) for pattern in include)
    return not any(fnmatchcase(tool, pattern) for pattern in rules.get("exclude") or [])


class McpClient:
    def __init__(self, name, config):
        self.name, self.config = name, config
        self.proc = None
        self.messages = queue.Queue()
        self.stderr_tail = collections.deque(maxlen=30)
        self.counter = 0

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.close()

    def start(self):
        command = expand(self.config["command"])
        executable = shutil.which(command)
        if not executable:
            raise McpError(f"找不到指令：{command}。請先安裝它（例如 uv、node），或修改 mcp.json 的 command。")
        args = [expand(item) for item in self.config.get("args") or []]
        env = {key: os.environ[key] for key in BASE_ENV if key in os.environ}   # 不整份繼承，避免洩漏無關機密
        for key, value in (self.config.get("env") or {}).items():
            expanded = expand(value, strict=False)
            if expanded is not None:      # 引用未設定變數的項目直接略過，不傳字面佔位符
                env[key] = expanded
        options = {"stdin": subprocess.PIPE, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "env": env}
        if self.config.get("cwd"):
            options["cwd"] = expand(self.config["cwd"])
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NO_WINDOW
        else:
            options["start_new_session"] = True
        try:
            self.proc = subprocess.Popen([executable, *args], **options)
        except OSError as error:
            raise McpError(f"無法啟動 {command}：{error}")
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        self.request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                    "clientInfo": {"name": "agent-mcp-skill", "version": "1.0"}},
                     float(self.config.get("connect_timeout", 60)))
        self.notify("notifications/initialized")

    def _read_stdout(self):
        for raw in self.proc.stdout:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                self.stderr_tail.append("[非 JSON 輸出] " + line[:200])
                continue
            if isinstance(message, dict):
                self.messages.put(message)
        self.messages.put(None)

    def _read_stderr(self):
        for raw in self.proc.stderr:     # 必須持續讀取，否則 server 寫滿管道會卡住
            self.stderr_tail.append(raw.decode("utf-8", "replace").rstrip()[:300])

    def _stderr(self):
        return ("\n--- server stderr 末段 ---\n" + "\n".join(self.stderr_tail)) if self.stderr_tail else ""

    def _send(self, message):
        try:
            self.proc.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            raise McpError("無法寫入 MCP server，它可能已結束。" + self._stderr())

    def notify(self, method, params=None):
        self._send({"jsonrpc": "2.0", "method": method, **({"params": params} if params is not None else {})})

    def request(self, method, params, timeout):
        self.counter += 1
        request_id = self.counter
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method,
                    **({"params": params} if params is not None else {})})
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise McpError(f"等待 {method} 回應逾時（{timeout:g} 秒）。" + self._stderr())
            try:
                message = self.messages.get(timeout=remaining)
            except queue.Empty:
                continue
            if message is None:
                raise McpError("MCP server 已結束，沒有回應。" + self._stderr())
            if "method" in message:       # server 主動發出的請求或通知
                if "id" in message:
                    ok = message["method"] == "ping"
                    self._send({"jsonrpc": "2.0", "id": message["id"],
                                **({"result": {}} if ok else {"error": {"code": -32601, "message": "Method not found"}})})
                continue
            if message.get("id") == request_id:
                if "error" in message:
                    error = message["error"] or {}
                    raise McpError(f"{method} 失敗：{error.get('message', error)}（code {error.get('code')}）")
                return message.get("result") or {}

    def list_tools(self):
        tools, cursor = [], None
        timeout = float(self.config.get("timeout", 120))
        while True:
            result = self.request("tools/list", {"cursor": cursor} if cursor else {}, timeout)
            tools += result.get("tools") or []
            cursor = result.get("nextCursor")
            if not cursor:
                return tools

    def call_tool(self, tool, arguments):
        return self.request("tools/call", {"name": tool, "arguments": arguments},
                            float(self.config.get("timeout", 120)))

    def close(self):
        if not self.proc:
            return
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=3)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True)
            else:
                os.killpg(self.proc.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            self.proc.kill()


def output_folder():
    folder = Path.cwd() / "mcp_outputs"
    folder.mkdir(exist_ok=True)
    return folder


def save_file(label, index, suffix, data):
    stem = re.sub(r"\W+", "_", label)[:40]
    path = output_folder() / f"{stem}_{int(time.time() * 1000)}_{index}.{suffix}"
    path.write_bytes(data)
    return path.relative_to(Path.cwd()).as_posix()


def render(result, label):
    """把 MCP 結果轉成純文字；圖片與過長內容存檔，只留路徑。"""
    parts = []
    for index, block in enumerate(result.get("content") or []):
        kind = block.get("type")
        if kind == "text":
            parts.append(clean(block.get("text", "")))
        elif kind == "image":
            suffix = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}.get(
                block.get("mimeType"), "bin")
            parts.append(f"[圖片已存檔：{save_file(label, index, suffix, base64.b64decode(block.get('data', '')))}]")
        elif kind == "resource":
            resource = block.get("resource") or {}
            if "text" in resource:
                parts.append(clean(resource["text"]))
            elif "blob" in resource:
                parts.append(f"[資源已存檔：{save_file(label, index, 'bin', base64.b64decode(resource['blob']))}]")
        elif kind == "resource_link":
            parts.append(f"[資源連結：{clean(str(block.get('uri', '')))}]")
        else:
            parts.append(f"[略過不支援的內容類型：{kind}]")
    if not parts and result.get("structuredContent") is not None:
        parts.append(clean(json.dumps(result["structuredContent"], ensure_ascii=False)))
    text = "\n".join(parts) or "（工具沒有回傳內容）"
    if len(text) > OUTPUT_LIMIT:
        path = save_file(label, "full", "txt", text.encode("utf-8"))
        text = text[:OUTPUT_LIMIT] + f"\n[輸出過長，共 {len(text)} 字元，只顯示開頭；全文已存：{path}]"
    return text


def read_json(value, expected, label):
    """JSON 字串，或 @相對路徑（限工作區內，避免任意讀檔）。"""
    if value.startswith("@"):
        path = (Path.cwd() / value[1:]).resolve()
        if Path(value[1:]).is_absolute() or not path.is_relative_to(Path.cwd().resolve()):
            raise McpError("@檔案 必須是工作區內的相對路徑。")
        try:
            value = path.read_text(encoding="utf-8-sig")
        except OSError as error:
            raise McpError(f"讀不到 {label} 檔案：{error}")
    try:
        data = json.loads(value)
    except ValueError as error:
        raise McpError(f"{label} 不是有效的 JSON：{error}")
    if not isinstance(data, expected):
        raise McpError(f"{label} 必須是 JSON {'物件' if expected is dict else '陣列'}。")
    return data


def visible_tools(client):
    return {tool["name"]: tool for tool in client.list_tools() if is_allowed(client.config, tool["name"])}


def run_call(client, tools, tool, arguments, label):
    """回傳 (文字, 是否出錯)；呼叫前先檢查工具存在與必要參數，錯誤訊息要能讓模型自行修正。"""
    if tool not in tools:
        raise McpError(f"server {client.name} 沒有開放工具 {tool}。可用工具：{'、'.join(tools) or '（無）'}。")
    required = (tools[tool].get("inputSchema") or {}).get("required") or []
    missing = [key for key in required if key not in arguments]
    if missing:
        raise McpError(f"工具 {tool} 缺少必要參數：{'、'.join(missing)}（必要參數：{'、'.join(required)}）。")
    result = client.call_tool(tool, arguments)
    return render(result, label), bool(result.get("isError"))


def command_servers(servers, _args):
    for name, config in servers.items():
        enabled = config.get("enabled", True) is not False
        command = str(config.get("command", ""))
        found = bool(command) and (shutil.which(VARIABLE.sub("", command)) is not None)
        rules = config.get("tools") or {}
        scope = f"include={rules['include']}" if "include" in rules else (f"exclude={rules['exclude']}" if rules.get("exclude") else "全部工具")
        print(f"- {name}：{'啟用' if enabled else '停用'}｜指令 {command} {'可用' if found else '找不到'}｜{scope}"
              + (f"｜{config['description']}" if config.get("description") else ""))
    if not servers:
        print("（mcp.json 沒有任何 server）")
    return 0


def command_list(servers, args):
    config = pick_server(servers, args.server)
    with McpClient(args.server, config) as client:
        tools = visible_tools(client)
    print(f"server {args.server} 開放 {len(tools)} 個工具：")
    for name, tool in tools.items():
        schema = json.dumps(tool.get("inputSchema") or {}, ensure_ascii=False, separators=(",", ":"))
        if len(schema) > SCHEMA_LIMIT and not args.full:
            schema = schema[:SCHEMA_LIMIT] + "…（已截斷，--full 可看全部）"
        description = clean(" ".join((tool.get("description") or "").split()))
        print(f"\n- {name}：{description[:400] if not args.full else description}\n  參數：{schema}")
    return 0


def command_call(servers, args):
    config = pick_server(servers, args.server)
    arguments = read_json(args.arguments, dict, "參數") if args.arguments else {}
    with McpClient(args.server, config) as client:
        text, failed = run_call(client, visible_tools(client), args.tool, arguments, f"{args.server}_{args.tool}")
    print(text)
    return 1 if failed else 0


def command_batch(servers, args):
    config = pick_server(servers, args.server)
    steps = read_json(args.steps, list, "步驟")
    for number, step in enumerate(steps, 1):
        if not isinstance(step, dict) or not isinstance(step.get("tool"), str) or not isinstance(step.get("arguments", {}), dict):
            raise McpError(f"第 {number} 步格式錯誤；每步需要 {{\"tool\": \"名稱\", \"arguments\": {{...}}}}。")
    failures = 0
    with McpClient(args.server, config) as client:
        tools = visible_tools(client)
        for number, step in enumerate(steps, 1):
            print(f"=== [{number}/{len(steps)}] {step['tool']} ===", flush=True)
            try:
                text, failed = run_call(client, tools, step["tool"], step.get("arguments", {}), f"{args.server}_{step['tool']}")
            except McpError as error:
                text, failed = f"錯誤：{error}", True
            print(text, flush=True)
            failures += failed
            if failed and not args.keep_going:
                print(f"（第 {number} 步失敗，後續 {len(steps) - number} 步未執行；加 --keep-going 可略過失敗繼續）")
                break
    return 1 if failures else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="通用 MCP stdio 客戶端", add_help=True)
    parser.add_argument("--config", default=str(CONFIG), help="設定檔路徑（預設為 Skill 目錄的 mcp.json）")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("servers")
    p = sub.add_parser("list")
    p.add_argument("server")
    p.add_argument("--full", action="store_true")
    p = sub.add_parser("call")
    p.add_argument("server")
    p.add_argument("tool")
    p.add_argument("arguments", nargs="?", default="")
    p = sub.add_parser("batch")
    p.add_argument("server")
    p.add_argument("steps")
    p.add_argument("--keep-going", action="store_true")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    try:
        servers = load_config(args.config)
        return {"servers": command_servers, "list": command_list, "call": command_call,
                "batch": command_batch}[args.command](servers, args)
    except McpError as error:
        print(f"錯誤：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
