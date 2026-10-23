"""任務控制與工具執行；主循環只處理協調。"""
import asyncio
import json
import inspect
import time
from uuid import uuid4
from pydantic import ValidationError
from app.logging_setup import log, log_context
from app.tools.registry import ToolResult, tool_registry
from app.tools.history_memory import memory_session


class RunControl:
    def __init__(self):
        self.run_id = uuid4().hex
        self.ready = asyncio.Event()
        self.ready.set()
        self.waiting = False

    async def checkpoint(self):
        if not self.ready.is_set():
            self.waiting = True
            log("run.paused")
            try:
                yield {"type": "run_state", "state": "paused"}
                await self.ready.wait()
            finally:
                self.waiting = False
            log("run.resumed")
            yield {"type": "run_state", "state": "running"}


def call_details(call):
    function = call.get("function", {})
    name, arguments = function.get("name", ""), function.get("arguments", {})
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            pass  # 原始參數交由 execute_call 留 log。
    return name, arguments


async def execute_call(session_id, name, arguments, allowed, *, mode, sdd_saved, call_id):
    token = log_context.set({**log_context.get(), "call_id": call_id})
    memory_token = memory_session.set(session_id)
    started = time.perf_counter()
    tool = tool_registry.get_tool(name)
    function = f"{tool.func.__module__}.{tool.func.__qualname__}" if tool else name
    log("tool.start", tool=name, function=function, arguments=arguments)
    def success(result):
        result = result if isinstance(result, ToolResult) else ToolResult(result)
        log("tool.end", tool=name, function=function, ok=result.ok, result=str(result), images=result.images,
            duration=time.perf_counter() - started, level=20 if result.ok else 40)
        return result

    def failure(error):
        log("tool.failed", level=40, exc_info=True, tool=name, function=function,
            arguments=arguments, ok=False, duration=time.perf_counter() - started)
        if isinstance(error, ValidationError):
            details = "；".join(f"{'.'.join(map(str, item['loc']))}: {item['msg']}"
                               for item in error.errors(include_url=False))
            return ToolResult.failed(f"工具參數錯誤 ({name}): {details}。可用欄位："
                                     + "、".join(tool.arguments.model_fields))
        return ToolResult.failed(f"工具執行失敗 ({name}): {error}")

    def sync_call(validated):
        # 前端斷線時，同步工具仍在原執行緒記錄完整結果與錯誤。
        try:
            return success(tool.func(**validated))
        except Exception as error:
            return failure(error)

    try:
        if name not in allowed or tool is None:
            raise ValueError(f"目前模式（{mode}）未提供工具：{name}")
        if not isinstance(arguments, dict):
            raise ValueError("工具參數必須是 JSON 物件。")
        if name == "finish_task" and mode == "plan" and not sdd_saved:
            raise ValueError("尚未保存 SDD，請先呼叫 save_sdd 保存三份文件。")
        validated = tool.validate(arguments)
        if inspect.iscoroutinefunction(tool.func):
            return success(await tool.func(**validated))
        return await asyncio.to_thread(sync_call, validated)
    except Exception as error:
        return failure(error)
    finally:
        memory_session.reset(memory_token)
        log_context.reset(token)


