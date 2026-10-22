"""規劃階段的 SDD 寫入工具，只能保存固定的三份文件。"""
from pathlib import Path
from app.tools.workspace_tools import _resolve_safe_path


SDD_FILES = ("spec.md", "plan.md", "tasks.md")


def save_sdd(specification: str, plan: str, tasks: str) -> str:
    """保存 SDD 的需求規格、技術規劃與待辦清單；只寫入工作區 .specify/ 的三份 Markdown。"""
    contents = (specification, plan, tasks)
    if any(not text.strip() for text in contents):
        raise ValueError("三份 SDD 文件都必須有內容。")
    for name, content in zip(SDD_FILES, contents):
        path = Path(_resolve_safe_path(f".specify/{name}"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return "已儲存 SDD：.specify/spec.md、.specify/plan.md、.specify/tasks.md。規劃完成，請按「開始實作」後再製作。"
