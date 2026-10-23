"""內建工具的統一註冊入口。"""
from functools import lru_cache


@lru_cache(maxsize=1)
def register_tools():
    from app.tools.registry import tool_registry
    from app.tools.google_search import google_search
    from app.tools.history_memory import search_history_memory
    from app.tools.read_web_page import read_web_page
    from app.tools.finish_task import finish_task
    from app.tools.planning import save_sdd
    from app.tools.preferences import update_user_preference
    from app.tools.skill_install import install_skill, list_installed_skills
    from app.tools.skill_run import run_skill_script
    from app.core.skill_registry import read_skill
    from app.storage.context_manager import read_tool_output
    from app.storage.jobs import get_job, stop_job
    from app.storage.plan_tasks import read_plan_tasks, update_task_status
    from app.tools.workspace_tools import (
        get_workspace_code_map,
        list_workspace_files,
        read_workspace_file,
        write_workspace_file,
        edit_code_chunk,
        run_python,
        search_workspace_code
    )

    # 工具的說明與模式只在註冊時定義，提示語隨註冊內容自動更新。
    for tool in (
        google_search, search_history_memory, read_web_page, finish_task,
        get_workspace_code_map, list_workspace_files,
        search_workspace_code, save_sdd, read_skill, read_tool_output, get_job, read_plan_tasks, update_user_preference, list_installed_skills,
    ):
        tool_registry.register(tool, modes=("agent", "plan"))

    path_aliases = {"file_name": "path", "file_path": "path", "file": "path"}
    tool_registry.register(read_workspace_file, modes=("agent", "plan"), aliases=path_aliases)
    tool_registry.register(write_workspace_file, aliases=path_aliases)
    tool_registry.register(edit_code_chunk, aliases={**path_aliases,
        "target_code": "old_string", "oldText": "old_string", "old_text": "old_string",
        "replacement_code": "new_string", "newText": "new_string", "new_text": "new_string"})

    for tool in (run_python, run_skill_script, stop_job, update_task_status, install_skill):
        tool_registry.register(tool)
