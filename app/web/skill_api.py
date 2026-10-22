"""全域 Skill 總表與說明預覽；安裝統一走 Agent 工具。"""
from pathlib import Path
from fastapi import APIRouter, HTTPException
from app.core.skill_registry import skill_registry

router = APIRouter()


@router.get("/api/skills")
def list_skills():
    return {"skills": skill_registry.inventory()}


@router.get("/api/skills/{skill_id}")
def skill_details(skill_id: str):
    item = next((item for item in skill_registry.inventory() if item["id"] == skill_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="找不到這個全域 Skill。")
    if not item["valid"]:
        return {**item, "content": "", "truncated": False}
    try:
        with Path(item["path"]).open(encoding="utf-8-sig") as stream:
            content = stream.read(256 * 1024 + 1)
        return {**item, "content": content[:256 * 1024], "truncated": len(content) > 256 * 1024}
    except (OSError, UnicodeError) as error:
        raise HTTPException(status_code=404, detail="Skill 檔案已移除或無法讀取，請重新整理。") from error
