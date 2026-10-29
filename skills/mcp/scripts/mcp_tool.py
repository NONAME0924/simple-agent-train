"""MCP 套件系統與通用 stdio 客戶端：由 run_skill_script 呼叫，零第三方相依。

套件管理
  packages                       列出已安裝的 MCP 套件（也可寫 servers）
  install <來源> [--force]        安裝套件：工作區內的資料夾／.zip，或 https 的 .zip 網址
  remove <名稱> --yes             移除套件
  enable|disable <名稱>           啟用／停用套件
  configure <名稱> [--command 路徑] [--env 鍵=值]... [--unset-env 鍵]... [--reset]
                                 設定本機專屬的覆寫（寫入 local.json，不進 git）

使用套件
  list <名稱>                     列出該套件開放的工具與參數
  call <名稱> <工具> [JSON]        呼叫單一工具（JSON 可寫 @檔案 讀取工作區內的檔案）
  batch <名稱> <JSON|@檔案>        同一連線依序呼叫多個工具：[{"tool": "...", "arguments": {...}}]

本程式不認識任何特定套件。套件放在 packages/<名稱>/，以 mcp-package.json 描述如何啟動它的 server。
設定值可用 ${變數}：${PYTHON}（目前的 Python）、${SKILL_DIR}（本 Skill 目錄）、${PACKAGE_DIR}（該套件目錄）、
其他名稱則為環境變數（env 內引用未設定的變數會略過該項；command/args 引用未設定的變數會報錯）。

每次執行都是「連線 → 做事 → 關閉」；狀態保留在外部程式而不在 server 內。
結果與 stderr 一律視為資料：圖片及過長輸出存到工作區 mcp_outputs/，只回傳路徑。
結束碼：0 成功、1 工具回報錯誤、2 設定／連線／用法錯誤。
"""
from __future__ import annotations

import argparse
import base64
import collections
import ipaddress
import json
import os
import queue
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from fnmatch import fnmatchcase
from pathlib import Path
from urllib.parse import urlparse

SKILL_DIR = Path(__file__).resolve().parents[1]
MANIFEST = "mcp-package.json"
PROTOCOL = "2025-06-18"
DEFAULT_CONNECT_TIMEOUT = 20   # 須小於 run_skill_script 的前景等待，錯誤訊息才來得及被看到
DEFAULT_CALL_TIMEOUT = 120
OUTPUT_LIMIT = 6000            # 超過就把全文存檔，只回傳開頭
SCHEMA_LIMIT = 1500            # list 時單一工具 schema 的顯示上限
MAX_PACKAGE_BYTES = 50 * 1024 * 1024
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
ENV_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
TAG_CHARS = re.compile("[\U000E0000-\U000E007F]")   # 不可見 TAG 字元：常見的提示注入夾帶手法
VARIABLE = re.compile(r"\$\{(?:env:)?([A-Za-z_][A-Za-z0-9_]*)\}")
BASE_ENV = ("PATH", "PATHEXT", "HOME", "USER", "LOGNAME", "USERNAME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
            "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "SYSTEMROOT",
            "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL", "TERM", "TZ",
            "COMPUTERNAME", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS")


class McpError(Exception):
    pass


def expand(value, strict=True, extra=None):
    """展開 ${VAR}；未設定時 strict 會報錯，否則回傳 None（讓呼叫端略過該項）。"""
    missing = []
    known = {"PYTHON": sys.executable, **(extra or {})}

    def replace(match):
        name = match.group(1)
        found = known.get(name)
        if found is None:
            found = os.environ.get(name)
        if found is None:
            missing.append(name)
            return ""
        return found

    result = VARIABLE.sub(replace, str(value))
    if missing and strict:
        raise McpError("設定引用了未設定的環境變數：" + "、".join(missing) + "。請在啟動 Agent 前設定。")
    return None if missing else result


def clean(text):
    return TAG_CHARS.sub("", text)


# ───────────────────────── 套件登錄：探索、驗證、本機覆寫 ─────────────────────────

def read_json_file(path, label):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise McpError(f"找不到{label}：{path}")
    except ValueError as error:
        raise McpError(f"{label}不是有效的 JSON（{path}）：{error}")


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def validate_manifest(manifest):
    """檢查 mcp-package.json；錯誤訊息要能讓人直接修正。"""
    if not isinstance(manifest, dict):
        raise McpError(f"{MANIFEST} 必須是 JSON 物件。")
    name = manifest.get("name")
    if not isinstance(name, str) or not NAME_PATTERN.match(name):
        raise McpError("name 必須是 1～40 字的小寫英數、底線或連字號，且以英數開頭。")
    server = manifest.get("server")
    if not isinstance(server, dict) or not isinstance(server.get("command"), str) or not server["command"].strip():
        raise McpError('server.command 必須是非空字串（目前只支援 stdio server）。')
    args = server.get("args", [])
    if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
        raise McpError("server.args 必須是字串陣列。")
    env = server.get("env", {})
    if not isinstance(env, dict) or not all(ENV_KEY_PATTERN.match(str(k)) and isinstance(v, str) for k, v in env.items()):
        raise McpError("server.env 必須是 {名稱: 字串} 物件，名稱限英數與底線。")
    for key in ("connect_timeout", "timeout"):
        if key in server and not _is_number(server[key]):
            raise McpError(f"server.{key} 必須是大於 0 的數字（秒）。")
    rules = server.get("tools", {})
    if not isinstance(rules, dict) or any(
            key in rules and not (isinstance(rules[key], list) and all(isinstance(i, str) for i in rules[key]))
            for key in ("include", "exclude")):
        raise McpError("server.tools 的 include／exclude 必須是字串陣列。")
    for key in ("version", "description", "guide"):
        if key in manifest and not isinstance(manifest[key], str):
            raise McpError(f"{key} 必須是字串。")
    if "enabled" in manifest and not isinstance(manifest["enabled"], bool):
        raise McpError("enabled 必須是 true 或 false。")
    return name


def load_local(root):
    path = root / "local.json"
    if not path.exists():
        return {}
    data = read_json_file(path, "本機設定 local.json")
    if not isinstance(data, dict):
        raise McpError("local.json 必須是 {套件名稱: {...}} 物件。")
    return data


def save_local(root, data):
    path = root / "local.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def merge_server(base, override):
    merged = {**base, **{k: v for k, v in override.items() if k != "env"}}
    if "env" in base or "env" in override:
        merged["env"] = {**base.get("env", {}), **override.get("env", {})}
    return merged


def discover(root):
    """回傳 {名稱: 套件資訊}；壞掉的套件只標示錯誤，不影響其他套件。"""
    local = load_local(root)
    packages = {}
    folder = root / "packages"
    for path in sorted(folder.iterdir() if folder.is_dir() else []):
        if not path.is_dir() or path.name.startswith("."):
            continue
        try:
            manifest = read_json_file(path / MANIFEST, MANIFEST)
            name = validate_manifest(manifest)
            if name != path.name:
                raise McpError(f"資料夾名稱（{path.name}）必須與 manifest 的 name（{name}）相同。")
            override = local.get(name, {}) if isinstance(local.get(name, {}), dict) else {}
            config = merge_server(manifest["server"], override.get("server", {}))
            config["enabled"] = override.get("enabled", manifest.get("enabled", True))
            config["description"] = manifest.get("description", "")
            config["_vars"] = {"SKILL_DIR": str(root), "PACKAGE_DIR": str(path)}
            guide = manifest.get("guide", "GUIDE.md")
            packages[name] = {"config": config, "version": manifest.get("version", ""),
                              "guide": f"packages/{name}/{guide}" if (path / guide).is_file() else None,
                              "customized": bool(override)}
        except McpError as error:
            packages[path.name] = {"error": str(error)}
    return packages


def pick_server(packages, name):
    package = packages.get(name)
    if package is None:
        raise McpError(f"沒有名為 {name} 的套件。已安裝：{'、'.join(packages) or '（無）'}。")
    if "error" in package:
        raise McpError(f"套件 {name} 的設定有誤：{package['error']}")
    config = package["config"]
    if config.get("enabled") is False:
        raise McpError(f"套件 {name} 已停用；需要時請使用者同意後執行 enable {name}。")
    return config


def is_allowed(config, tool):
    rules = config.get("tools") or {}
    include = rules.get("include")
    if include is not None:      # 白名單優先；同時設定時不再看 exclude
        return any(fnmatchcase(tool, pattern) for pattern in include)
    return not any(fnmatchcase(tool, pattern) for pattern in rules.get("exclude") or [])


# ───────────────────────── stdio MCP 客戶端 ─────────────────────────

class McpClient:
    def __init__(self, name, config):
        self.name, self.config = name, config
        self.vars = config.get("_vars", {})
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
        command = expand(self.config["command"], extra=self.vars)
        executable = shutil.which(command)
        if not executable:
            raise McpError(f"找不到指令：{command}。請先安裝它，或用 configure {self.name} --command 設定完整路徑。")
        args = [expand(item, extra=self.vars) for item in self.config.get("args") or []]
        env = {key: os.environ[key] for key in BASE_ENV if key in os.environ}   # 不整份繼承，避免洩漏無關機密
        for key, value in (self.config.get("env") or {}).items():
            expanded = expand(value, strict=False, extra=self.vars)
            if expanded is not None:      # 引用未設定變數的項目直接略過，不傳字面佔位符
                env[key] = expanded
        options = {"stdin": subprocess.PIPE, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "env": env}
        if self.config.get("cwd"):
            options["cwd"] = expand(self.config["cwd"], extra=self.vars)
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NO_WINDOW
        else:
            options["start_new_session"] = True
        connect_timeout = float(self.config.get("connect_timeout", DEFAULT_CONNECT_TIMEOUT))
        # 先印出進度：即使工作被提前停止，get_job 的 stderr 仍看得出卡在哪一步。
        print(f"[mcp] 啟動 {self.name}（連線逾時 {connect_timeout:g} 秒、單次呼叫逾時 "
              f"{float(self.config.get('timeout', DEFAULT_CALL_TIMEOUT)):g} 秒）", file=sys.stderr, flush=True)
        try:
            self.proc = subprocess.Popen([executable, *args], **options)
        except OSError as error:
            raise McpError(f"無法啟動 {command}：{error}")
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        self.request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                    "clientInfo": {"name": "agent-mcp-skill", "version": "2.0"}}, connect_timeout)
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
                hint = ""
                if method == "initialize":
                    hint = ("\n提示：server 在連線逾時內沒有完成 MCP 握手。常見原因：server 啟動時在等外部程式回應"
                            "（例如與外部程式的協議不符，對方一直不回），或套件第一次下載、啟動太慢。"
                            "請先看下方 stderr；確認 server 與外部程式是配對的版本，必要時調大 connect_timeout。")
                raise McpError(f"等待 {method} 回應逾時（{timeout:g} 秒）。{hint}" + self._stderr())
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
        timeout = float(self.config.get("timeout", DEFAULT_CALL_TIMEOUT))
        while True:
            result = self.request("tools/list", {"cursor": cursor} if cursor else {}, timeout)
            tools += result.get("tools") or []
            cursor = result.get("nextCursor")
            if not cursor:
                return tools

    def call_tool(self, tool, arguments):
        return self.request("tools/call", {"name": tool, "arguments": arguments},
                            float(self.config.get("timeout", DEFAULT_CALL_TIMEOUT)))

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


# ───────────────────────── 結果呈現與參數讀取 ─────────────────────────

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


def workspace_path(value, label):
    """工作區（目前目錄）內的相對路徑；拒絕絕對路徑與跳出工作區。"""
    path = (Path.cwd() / value).resolve()
    if Path(value).is_absolute() or not path.is_relative_to(Path.cwd().resolve()):
        raise McpError(f"{label}必須是工作區內的相對路徑。")
    return path


def read_json(value, expected, label):
    """JSON 字串，或 @相對路徑（限工作區內，避免任意讀檔）。"""
    if value.startswith("@"):
        path = workspace_path(value[1:], "@檔案")
        try:
            value = path.read_text(encoding="utf-8-sig")
        except OSError as error:
            raise McpError(f"讀不到{label}檔案：{error}")
    try:
        data = json.loads(value)
    except ValueError as error:
        raise McpError(f"{label}不是有效的 JSON：{error}")
    if not isinstance(data, expected):
        raise McpError(f"{label}必須是 JSON {'物件' if expected is dict else '陣列'}。")
    return data


def visible_tools(client):
    return {tool["name"]: tool for tool in client.list_tools() if is_allowed(client.config, tool["name"])}


def run_call(client, tools, tool, arguments, label):
    """回傳 (文字, 是否出錯)；呼叫前先檢查工具存在與必要參數，錯誤訊息要能讓模型自行修正。"""
    if tool not in tools:
        raise McpError(f"套件 {client.name} 沒有開放工具 {tool}。可用工具：{'、'.join(tools) or '（無）'}。")
    required = (tools[tool].get("inputSchema") or {}).get("required") or []
    missing = [key for key in required if key not in arguments]
    if missing:
        raise McpError(f"工具 {tool} 缺少必要參數：{'、'.join(missing)}（必要參數：{'、'.join(required)}）。")
    result = client.call_tool(tool, arguments)
    return render(result, label), bool(result.get("isError"))


# ───────────────────────── 套件安裝 ─────────────────────────

def _check_tree(folder):
    total = 0
    for path in folder.rglob("*"):
        if path.is_symlink():
            raise McpError(f"套件內含符號連結，已拒絕：{path.relative_to(folder)}")
        if path.is_file():
            total += path.stat().st_size
    if total > MAX_PACKAGE_BYTES:
        raise McpError(f"套件超過 {MAX_PACKAGE_BYTES // 1024 // 1024} MB 上限，已拒絕。")


def safe_extract(archive, destination):
    destination = destination.resolve()
    try:
        with zipfile.ZipFile(archive) as bundle:
            total = 0
            for info in bundle.infolist():
                if info.is_dir():
                    continue
                total += info.file_size
                if total > MAX_PACKAGE_BYTES:
                    raise McpError(f"解壓後超過 {MAX_PACKAGE_BYTES // 1024 // 1024} MB 上限，已拒絕。")
                if stat.S_ISLNK(info.external_attr >> 16):
                    raise McpError(f"zip 內含符號連結，已拒絕：{info.filename}")
                target = (destination / info.filename).resolve()
                if not target.is_relative_to(destination):
                    raise McpError(f"zip 內含會跳出目標資料夾的路徑，已拒絕：{info.filename}")
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(info) as source, open(target, "wb") as output:
                    shutil.copyfileobj(source, output)
    except zipfile.BadZipFile:
        raise McpError("不是有效的 zip 檔。")


def download(url, destination):
    parts = urlparse(url)
    host = parts.hostname or ""
    try:
        local = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = False
    if parts.scheme != "https" and not (parts.scheme == "http" and local):
        raise McpError("網址必須是 https（本機測試的 localhost 除外）。")
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read(MAX_PACKAGE_BYTES + 1)
    except OSError as error:
        raise McpError(f"下載失敗：{error}")
    if len(data) > MAX_PACKAGE_BYTES:
        raise McpError(f"下載內容超過 {MAX_PACKAGE_BYTES // 1024 // 1024} MB 上限，已中止。")
    destination.write_bytes(data)


def find_package_root(folder):
    if (folder / MANIFEST).is_file():
        return folder
    children = [child for child in folder.iterdir() if child.is_dir()]
    if len(children) == 1 and (children[0] / MANIFEST).is_file():     # GitHub 的 zip 會多包一層資料夾
        return children[0]
    raise McpError(f"來源裡找不到 {MANIFEST}（需在根目錄，或唯一一層子資料夾內）。")


def command_install(root, args):
    source = args.source
    with tempfile.TemporaryDirectory() as scratch:
        scratch = Path(scratch)
        if source.startswith(("http://", "https://")):
            archive = scratch / "download.zip"
            download(source, archive)
            safe_extract(archive, scratch / "src")
            origin = scratch / "src"
        else:
            path = workspace_path(source, "來源")
            if path.is_dir():
                origin = path
            elif path.is_file() and path.suffix.lower() == ".zip":
                safe_extract(path, scratch / "src")
                origin = scratch / "src"
            else:
                raise McpError("來源必須是工作區內的資料夾或 .zip 檔，或 https 的 .zip 網址。")
        package_root = find_package_root(origin)
        _check_tree(package_root)
        manifest = read_json_file(package_root / MANIFEST, MANIFEST)
        name = validate_manifest(manifest)
        target = root / "packages" / name
        if target.exists() and not args.force:
            raise McpError(f"套件 {name} 已存在；要覆蓋請加 --force。")
        (root / "packages").mkdir(exist_ok=True)
        staging, backup = root / "packages" / f".installing-{name}", root / "packages" / f".old-{name}"
        for leftover in (staging, backup):
            shutil.rmtree(leftover, ignore_errors=True)
        shutil.copytree(package_root, staging, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
        try:
            if target.exists():
                target.rename(backup)
            staging.rename(target)
        except OSError as error:
            shutil.rmtree(staging, ignore_errors=True)
            if backup.exists() and not target.exists():
                backup.rename(target)
            raise McpError(f"安裝失敗：{error}")
        shutil.rmtree(backup, ignore_errors=True)
    server = manifest["server"]
    print(f"已安裝套件 {name} {manifest.get('version', '')}→ packages/{name}")
    print(f"需要時才會啟動：{server['command']} {' '.join(server.get('args', []))}")
    print("安裝本身沒有執行該套件；它的程式會在 list／call 時由本機啟動，請只安裝你信任的來源。")
    return 0


def command_remove(root, args):
    packages = discover(root)
    if args.name not in packages:
        raise McpError(f"沒有名為 {args.name} 的套件。已安裝：{'、'.join(packages) or '（無）'}。")
    if not args.yes:
        raise McpError(f"移除會刪除 packages/{args.name} 整個資料夾；確認要移除請加 --yes。")
    shutil.rmtree(root / "packages" / args.name)
    local = load_local(root)
    if local.pop(args.name, None) is not None:
        save_local(root, local)
    print(f"已移除套件 {args.name}。")
    return 0


def command_toggle(root, args, enabled):
    packages = discover(root)
    if args.name not in packages:
        raise McpError(f"沒有名為 {args.name} 的套件。已安裝：{'、'.join(packages) or '（無）'}。")
    local = load_local(root)
    local.setdefault(args.name, {})["enabled"] = enabled
    save_local(root, local)
    print(f"套件 {args.name} 已{'啟用' if enabled else '停用'}（記錄在 local.json，不會進 git）。")
    return 0


def command_configure(root, args):
    packages = discover(root)
    if args.name not in packages or "error" in packages[args.name]:
        raise McpError(f"沒有可設定的套件 {args.name}。已安裝：{'、'.join(packages) or '（無）'}。")
    local = load_local(root)
    if args.reset:
        local.pop(args.name, None)
        save_local(root, local)
        print(f"已清除 {args.name} 的本機覆寫，恢復套件預設。")
        return 0
    entry = local.setdefault(args.name, {})
    server = entry.setdefault("server", {})
    if args.command_path:
        server["command"] = args.command_path
    for pair in args.env or []:
        key, separator, value = pair.partition("=")
        if not separator or not ENV_KEY_PATTERN.match(key):
            raise McpError(f"--env 需要 鍵=值 格式，鍵限英數與底線：{pair!r}")
        server.setdefault("env", {})[key] = value
    for key in args.unset_env or []:
        if key in server.get("env", {}):
            del server["env"][key]
    if not args.command_path and not args.env and not args.unset_env:
        raise McpError("沒有任何要設定的項目；可用 --command、--env 鍵=值、--unset-env 鍵 或 --reset。")
    if not server:
        entry.pop("server")
    save_local(root, local)
    print(f"已更新 {args.name} 的本機設定（local.json，不會進 git）。"
          + (f"command={server['command']}；" if "command" in server else "")
          + (f"env 鍵：{'、'.join(server.get('env', {}))}。" if server.get("env") else ""))
    return 0


# ───────────────────────── 查詢與呼叫 ─────────────────────────

def command_packages(root, _args):
    packages = discover(root)
    for name, package in packages.items():
        if "error" in package:
            print(f"- {name}：設定有誤｜{package['error']}")
            continue
        config = package["config"]
        command = expand(config.get("command", ""), strict=False, extra=config["_vars"]) or str(config.get("command", ""))
        found = shutil.which(command) is not None
        rules = config.get("tools") or {}
        scope = f"include={rules['include']}" if "include" in rules else (
            f"exclude={rules['exclude']}" if rules.get("exclude") else "全部工具")
        print(f"- {name} {package['version']}：{'啟用' if config['enabled'] else '停用'}｜指令 {command} "
              f"{'可用' if found else '找不到'}｜{scope}" + ("｜本機已覆寫設定" if package["customized"] else "")
              + (f"｜{config['description']}" if config["description"] else "")
              + (f"｜指南：read_skill(name=\"mcp\", resource=\"{package['guide']}\")" if package["guide"] else ""))
    if not packages:
        print("（尚未安裝任何 MCP 套件）")
    return 0


def command_list(root, args):
    config = pick_server(discover(root), args.name)
    with McpClient(args.name, config) as client:
        tools = visible_tools(client)
    print(f"套件 {args.name} 開放 {len(tools)} 個工具：")
    for name, tool in tools.items():
        schema = json.dumps(tool.get("inputSchema") or {}, ensure_ascii=False, separators=(",", ":"))
        if len(schema) > SCHEMA_LIMIT and not args.full:
            schema = schema[:SCHEMA_LIMIT] + "…（已截斷，--full 可看全部）"
        description = clean(" ".join((tool.get("description") or "").split()))
        print(f"\n- {name}：{description[:400] if not args.full else description}\n  參數：{schema}")
    return 0


def command_call(root, args):
    config = pick_server(discover(root), args.name)
    arguments = read_json(args.arguments, dict, "參數") if args.arguments else {}
    with McpClient(args.name, config) as client:
        text, failed = run_call(client, visible_tools(client), args.tool, arguments, f"{args.name}_{args.tool}")
    print(text)
    return 1 if failed else 0


def command_batch(root, args):
    config = pick_server(discover(root), args.name)
    steps = read_json(args.steps, list, "步驟")
    for number, step in enumerate(steps, 1):
        if not isinstance(step, dict) or not isinstance(step.get("tool"), str) or not isinstance(step.get("arguments", {}), dict):
            raise McpError(f"第 {number} 步格式錯誤；每步需要 {{\"tool\": \"名稱\", \"arguments\": {{...}}}}。")
    failures = 0
    with McpClient(args.name, config) as client:
        tools = visible_tools(client)
        for number, step in enumerate(steps, 1):
            print(f"=== [{number}/{len(steps)}] {step['tool']} ===", flush=True)
            try:
                text, failed = run_call(client, tools, step["tool"], step.get("arguments", {}), f"{args.name}_{step['tool']}")
            except McpError as error:
                text, failed = f"錯誤：{error}", True
            print(text, flush=True)
            failures += failed
            if failed and not args.keep_going:
                print(f"（第 {number} 步失敗，後續 {len(steps) - number} 步未執行；加 --keep-going 可略過失敗繼續）")
                break
    return 1 if failures else 0


def build_parser():
    parser = argparse.ArgumentParser(description="MCP 套件系統與通用 stdio 客戶端")
    parser.add_argument("--root", default=str(SKILL_DIR), help="Skill 根目錄（預設為本腳本所在 Skill；主要供測試）")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("packages", aliases=["servers"])
    p = sub.add_parser("install")
    p.add_argument("source")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("remove")
    p.add_argument("name")
    p.add_argument("--yes", action="store_true")
    for action in ("enable", "disable"):
        sub.add_parser(action).add_argument("name")
    p = sub.add_parser("configure")
    p.add_argument("name")
    p.add_argument("--command", dest="command_path", metavar="路徑")
    p.add_argument("--env", action="append", metavar="鍵=值")
    p.add_argument("--unset-env", action="append", metavar="鍵")
    p.add_argument("--reset", action="store_true")
    p = sub.add_parser("list")
    p.add_argument("name")
    p.add_argument("--full", action="store_true")
    p = sub.add_parser("call")
    p.add_argument("name")
    p.add_argument("tool")
    p.add_argument("arguments", nargs="?", default="")
    p = sub.add_parser("batch")
    p.add_argument("name")
    p.add_argument("steps")
    p.add_argument("--keep-going", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    root = Path(args.root).resolve()
    handlers = {"packages": command_packages, "servers": command_packages, "install": command_install,
                "remove": command_remove, "enable": lambda r, a: command_toggle(r, a, True),
                "disable": lambda r, a: command_toggle(r, a, False), "configure": command_configure,
                "list": command_list, "call": command_call, "batch": command_batch}
    try:
        return handlers[args.action](root, args)
    except McpError as error:
        print(f"錯誤：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
