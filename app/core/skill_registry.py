"""發現本機 Skill 的名稱與用途，完整說明及參考檔案按需讀取。"""
from pathlib import Path
from app.config import APP_DIR
import hashlib
import json
import re
from app.logging_setup import log
from app.storage.workspace import get_workspace_dir

GLOBAL_SKILL_DIR = APP_DIR / "skills"
INSTALL_RECORD = ".agent-install.json"


def skill_metadata(text):
    metadata = _metadata(text.lstrip("\ufeff"))
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", metadata.get("name", "")) or not metadata.get("description"):
        raise ValueError("SKILL.md 必須有有效的 name（小寫英數與連字號）及 description。")
    return metadata


def _metadata(text):
    """讀取 frontmatter 的 name、description，支援單行與 > / | 多行文字。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    values, current = {}, None
    for line in lines[1:]:
        if line.strip() == "---":
            return {key: " ".join(parts).strip() for key, parts in values.items()}
        if line.startswith((" ", "\t")):
            if current:
                values[current].append(line.strip())
            continue
        key, separator, value = line.partition(":")
        current = key if separator and key in ("name", "description") else None
        if current:
            value = value.strip()
            values[current] = [] if value in (">", "|", ">-", "|-") else [value.strip("\"'")]
    return {}


class SkillRegistry:
    def inventory(self):
        """列出全域技能與格式問題；不修改既有技能。"""
        items = []
        for root in (GLOBAL_SKILL_DIR, APP_DIR / "workspace" / "skills"):
            for folder in sorted(root.glob("*")):
                if folder.name.startswith(".") or not folder.is_dir() or not folder.resolve().is_relative_to(root.resolve()):
                    continue
                path = folder / "SKILL.md"
                item = {"id": hashlib.sha256(str(folder).encode()).hexdigest()[:24], "name": folder.name,
                        "description": "", "path": str(path), "scope": "全域", "valid": False,
                        "source_url": "", "installed_at": "", "error": ""}
                try:
                    if not path.resolve().is_relative_to(folder.resolve()):
                        raise ValueError("SKILL.md 不能指向技能目錄外。")
                    if path.stat().st_size > 256 * 1024:
                        raise ValueError("SKILL.md 超過 256 KiB。")
                    item.update(skill_metadata(path.read_text(encoding="utf-8-sig")), valid=True)
                except (OSError, ValueError) as error:
                    item["error"] = str(error)
                record = folder / INSTALL_RECORD
                try:
                    if record.resolve().is_relative_to(folder.resolve()) and record.is_file() and record.stat().st_size <= 65536:
                        saved = json.loads(record.read_text(encoding="utf-8"))
                        if isinstance(saved, dict):
                            for key in ("source_url", "installed_at"):
                                item[key] = str(saved.get(key) or "")
                except (OSError, ValueError):
                    pass  # 舊／手動安裝仍列出，不依賴安裝紀錄才能使用。
                items.append(item)
        effective = {item["name"]: item["id"] for item in items if item["valid"]}
        for item in items:
            item["active"] = item["valid"] and effective.get(item["name"]) == item["id"]
        return items

    def discover(self):
        skills = {}
        # 工作區的同名 Skill 覆蓋內建版本；每次組裝提示語重新讀取。
        for root in dict.fromkeys((APP_DIR / "skills", APP_DIR / "workspace" / "skills", Path(get_workspace_dir()) / "skills")):
            for path in sorted(root.glob("*/SKILL.md")):
                if not path.resolve().is_relative_to(root.resolve()):
                    continue
                try:
                    metadata = _metadata(path.read_text(encoding="utf-8-sig"))
                except (OSError, UnicodeError):
                    log("skill.read_failed", level=40, exc_info=True, path=str(path))
                    continue
                name = metadata.get("name", "")
                if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", name) and metadata.get("description"):
                    skills[name] = {**metadata, "path": path}
        return skills

    def catalog(self):
        return "\n".join(f"- {name}：{skill['description']}" for name, skill in self.discover().items())

    def read(self, name, resource="SKILL.md"):
        skill = self.discover().get(name)
        if skill is None:
            raise ValueError(f"找不到 Skill：{name}")
        folder = skill["path"].parent.resolve()
        path = (folder / resource).resolve()
        if not path.is_relative_to(folder):
            raise ValueError("只能讀取該 Skill 資料夾內的檔案。")
        return f"Skill：{name}\n來源：{path}\n\n{path.read_text(encoding='utf-8-sig')}"


skill_registry = SkillRegistry()


def read_skill(name: str, resource: str = "SKILL.md") -> str:
    """載入已列出的 Skill 完整說明；需要參考資料時，resource 可指定該 Skill 內的相對檔案路徑。"""
    return skill_registry.read(name, resource)
