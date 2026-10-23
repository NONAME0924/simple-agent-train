"""系統行為與模式提示；使用者規則獨立放在 AGENTS.md。"""
from pathlib import Path
from app.config import APP_DIR
from app.core.skill_registry import skill_registry
from app.storage.workspace import get_workspace_dir


def load_prompt(name):
    return (APP_DIR / "prompts" / f"{name}.md").read_text(encoding="utf-8-sig")


def prompt_messages(default_prompt: str, mode: str, tool_schemas=(), *, finalizing=False, reasoning_level="medium"):
    if reasoning_level not in ("low", "medium", "high"):
        raise ValueError("思考程度只支援 low、medium、high。")
    messages = [{"role": "system", "content": default_prompt},
                {"role": "system", "content": load_prompt("reasoning") + "\n" + load_prompt(f"reasoning/{reasoning_level}")}]
    tools = [schema["function"] for schema in tool_schemas]
    catalog = "\n".join(
        f"- {tool['name']}：{(tool.get('description') or '未提供說明').splitlines()[0]}"
        for tool in tools
    )
    messages.append({"role": "system", "content": "本輪可用工具（參數依 Schema）：\n" + (catalog or "本輪不提供工具，請交付目前成果。")})
    if any(tool["name"] == "read_skill" for tool in tools):
        messages.append({"role": "system", "content": load_prompt("skills")})
        skills = skill_registry.catalog()
        if skills:
            messages.append({"role": "system", "content": "可用 Skill（以 read_skill 取得開頭與索引，按需選讀必要段落）：\n" + skills})
    paths = (APP_DIR / "AGENTS.md", Path(get_workspace_dir()) / "AGENTS.md")
    for path in dict.fromkeys(paths):
        if path.is_file():
            rules = path.read_text(encoding="utf-8-sig")
            label = "使用者共用偏好" if path == APP_DIR / "AGENTS.md" else "目前工作區規則"
            messages.append({"role": "system", "content": f"{label}（{path}）：\n{rules}"})
    messages.append({"role": "system", "content": load_prompt("preferences")})
    if any(tool["name"] == "install_skill" for tool in tools):
        messages.append({"role": "system", "content": load_prompt("skill_install")})
    mode_prompt = load_prompt("limit_summary" if finalizing else "plan" if mode == "plan" else "agent")
    messages.append({"role": "system", "content": mode_prompt})
    if not finalizing and mode == "agent":
        messages.append({"role": "system", "content": load_prompt("tasks")})
    return messages
