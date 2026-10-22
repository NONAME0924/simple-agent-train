"""從公開來源下載完整 Skill，統一安裝到 Agent 的全域 skills/。"""
import hashlib
import io
import ipaddress
import json
import re
import socket
import stat
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from threading import Lock
from urllib.parse import quote, unquote, urljoin, urlsplit
import httpx
from app.core.skill_registry import GLOBAL_SKILL_DIR, INSTALL_RECORD, skill_metadata, skill_registry
from app.logging_setup import log

MAX_DOWNLOAD = 50 * 1024 * 1024
MAX_EXPANDED = 100 * 1024 * 1024
_install_lock = Lock()


def _public_url(url):
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("請提供不含帳號密碼的公開 HTTP／HTTPS 下載網址。")
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("Skill 下載來源必須是公開網站，不能指向本機或內網。")


def _download(url):
    started = time.monotonic()
    with httpx.Client(timeout=30, headers={"User-Agent": "AI-Agent-Skill-Installer"}, follow_redirects=False) as client:
        for _ in range(6):
            if time.monotonic() - started > 90:
                raise ValueError("Skill 下載超過 90 秒，請稍後重試。")
            _public_url(url)
            with client.stream("GET", url) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers["location"])
                    continue
                response.raise_for_status()
                data = bytearray()
                for chunk in response.iter_bytes(65536):
                    data.extend(chunk)
                    if len(data) > MAX_DOWNLOAD or time.monotonic() - started > 90:
                        raise ValueError("下載超過 50 MiB 或 90 秒，請提供較小的 Skill 壓縮檔。")
                return bytes(data), str(response.url)
    raise ValueError("下載重新導向次數過多。")


def _relative(value):
    if "\\" in value or ":" in value or value.startswith("/") or any(part == ".." for part in value.split("/")):
        raise ValueError("Skill 檔案必須使用安全的相對路徑。")
    for part in value.split("/"):
        if part not in {"", "."} and (part.endswith((" ", ".")) or any(ord(c) < 32 for c in part)
                or re.fullmatch(r"(?i:con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\..*)?", part)):
            raise ValueError("Skill 檔案名稱無法在支援的平台上安全儲存。")
    return PurePosixPath(value)


def _source(url, skill_path, ref):
    parsed = urlsplit(url)
    if parsed.hostname not in {"github.com", "www.github.com", "raw.githubusercontent.com"}:
        return url, skill_path
    parts = [unquote(part) for part in parsed.path.strip("/").split("/")]
    if len(parts) < 2 or not all(re.fullmatch(r"[A-Za-z0-9_.-]+", value) for value in parts[:2]):
        raise ValueError("GitHub 網址必須包含擁有者與倉庫名稱。")
    owner, repo = parts[0], parts[1].removesuffix(".git")
    remaining = parts[2:]
    if parsed.hostname == "raw.githubusercontent.com":
        remaining = ["blob", *remaining]
    if remaining:
        if remaining[0] not in {"tree", "blob"} or len(remaining) < 2:
            return url, skill_path  # release ZIP 等網址直接下載。
        tail = remaining[1:]
        if not ref and len(tail) >= 3 and tail[:2] in (["refs", "heads"], ["refs", "tags"]):
            ref = "/".join(tail[:3])
        ref_parts = ref.split("/") if ref else [tail[0]]
        if tail[:len(ref_parts)] != ref_parts:
            raise ValueError("ref 與網址中的分支不一致；含斜線的分支請提供完整 ref。")
        ref = ref or tail[0]
        inferred = "/".join(tail[len(ref_parts):])
        if inferred.endswith("/SKILL.md") or inferred == "SKILL.md":
            inferred = str(PurePosixPath(inferred).parent)
        skill_path = skill_path or inferred
    return f"https://api.github.com/repos/{owner}/{repo}/zipball/{quote(ref or 'HEAD', safe='')}", skill_path


def _select(archive, selector):
    candidates = []
    metadata_bytes = 0
    for entry in archive.infolist():
        if entry.is_dir() or PurePosixPath(entry.filename).name != "SKILL.md":
            continue
        path = _relative(entry.filename)
        if entry.file_size > 256 * 1024 or stat.S_ISLNK(entry.external_attr >> 16):
            continue
        metadata_bytes += entry.file_size
        if metadata_bytes > 8 * 1024 * 1024:
            raise ValueError("來源包含太多技能說明，請提供目標技能的獨立 ZIP。")
        try:
            metadata = skill_metadata(archive.read(entry).decode("utf-8-sig"))
        except (ValueError, UnicodeError):
            continue
        candidates.append({**metadata, "path": str(path.parent), "entry": entry})
    selected = candidates
    if selector and selector != ".":
        selector = str(_relative(selector)).removesuffix("/SKILL.md").rstrip("/")
        selected = [item for item in candidates if item["name"] == selector or item["path"] == selector
                    or item["path"].endswith("/" + selector)]
    if not selected:
        raise ValueError("來源中找不到符合的有效 SKILL.md；請檢查下載來源、技能名稱與目錄。")
    return selected


def list_installed_skills() -> str:
    """列出目前全域 Skill 總表，包含說明、來源、安裝時間、位置與格式問題。"""
    return json.dumps({"skills": skill_registry.inventory()}, ensure_ascii=False)


def install_skill(source_url: str, skill_path: str = "", ref: str = "") -> str:
    """全域安裝使用者要求的 Skill，保留完整 scripts／references／assets，不覆寫既有技能。
    先用 read_web_page 解析使用者提供的網站與安裝說明，找出公開 GitHub 倉庫／Skill 目錄、ZIP 或 SKILL.md 的下載網址後再呼叫。
    skill_path 可指定技能名稱或來源中的相對目錄；多技能來源未指定時會回傳候選，不安裝全部。
    ref 可指定 GitHub 分支／標籤／commit，含斜線的分支須填完整 ref。
    本工具只安裝技能檔案，不執行網站的 shell 指令或自動安裝額外依賴。
    """
    source_url = source_url.strip()
    _public_url(source_url)
    download_url, selector = _source(source_url, skill_path.strip(), ref.strip())
    log("skill.install_start", source_url=source_url, skill_path=selector, ref=ref)
    data, resolved_url = _download(download_url)
    single_file = not zipfile.is_zipfile(io.BytesIO(data))
    if single_file:
        try:
            skill_metadata(data.decode("utf-8-sig"))
        except (ValueError, UnicodeError) as error:
            raise ValueError("這不是有效的 Skill ZIP 或 SKILL.md。若是介紹網站，請先 read_web_page 找出真正的下載來源。") from error
        package = io.BytesIO()
        with zipfile.ZipFile(package, "w") as archive:
            archive.writestr("SKILL.md", data)
        package.seek(0)
    else:
        package = io.BytesIO(data)
    with zipfile.ZipFile(package) as archive:
        if len(archive.infolist()) > 20000:
            raise ValueError("壓縮檔項目過多，請提供只包含目標技能的 ZIP。")
        selected = _select(archive, selector)
        if len(selected) != 1:
            choices = [{"name": item["name"], "path": item["path"], "description": item["description"]} for item in selected]
            log("skill.selection_required", source_url=source_url, candidates=choices)
            return json.dumps({"status": "selection_required", "candidates": choices[:100], "total": len(choices),
                               "message": "依使用者需求選擇技能，再填 skill_path 呼叫；不確定時詢問使用者，不一次安裝全部。"}, ensure_ascii=False)
        chosen = selected[0]
        _relative(chosen["name"])
        folder = PurePosixPath(chosen["path"])
        files = []
        total = 0
        for entry in archive.infolist():
            path = PurePosixPath(entry.filename)
            if entry.is_dir() or not path.is_relative_to(folder):
                continue
            relative = _relative(str(path.relative_to(folder)))
            if stat.S_ISLNK(entry.external_attr >> 16) or relative.name == INSTALL_RECORD:
                raise ValueError("Skill 包含不支援的符號連結或保留的安裝紀錄檔。")
            total += entry.file_size
            if total > MAX_EXPANDED or len(files) >= 3000:
                raise ValueError("Skill 展開超過 100 MiB 或 3000 個檔案。")
            files.append((entry, relative))
        with _install_lock:
            GLOBAL_SKILL_DIR.mkdir(parents=True, exist_ok=True)
            target = GLOBAL_SKILL_DIR / chosen["name"]
            if target.exists() or any(item["name"] == chosen["name"] for item in skill_registry.inventory()):
                raise ValueError(f"全域 Skill {chosen['name']} 已存在，保留原檔，未覆寫。")
            record = {"name": chosen["name"], "source_url": source_url, "download_url": resolved_url,
                      "skill_path": chosen["path"], "sha256": hashlib.sha256(data).hexdigest(),
                      "installed_at": datetime.now(timezone.utc).isoformat(), "files": len(files)}
            with tempfile.TemporaryDirectory(prefix=".install-", dir=GLOBAL_SKILL_DIR) as temporary:
                staging = Path(temporary) / chosen["name"]
                staging.mkdir()
                for entry, relative in files:
                    destination = staging.joinpath(*relative.parts)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(entry) as source, destination.open("xb") as output:
                        while chunk := source.read(65536):
                            output.write(chunk)
                    if entry.external_attr >> 16 & 0o111:
                        destination.chmod(destination.stat().st_mode | 0o111)
                (staging / INSTALL_RECORD).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
                staging.rename(target)
    log("skill.installed", **record, path=str(target), scope="global")
    return json.dumps({"status": "installed", **record, "path": str(target),
                       "message": "已全域安裝，所有專案下一輪主提示語自動載入，不需重啟。",
                       "note": "來源只提供單份 SKILL.md，未包含額外腳本或參考檔案。" if single_file else "技能資料夾已完整保存；額外套件與外部服務依賴需另行處理。"}, ensure_ascii=False)
