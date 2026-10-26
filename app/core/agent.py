"""Agent 任務協調：模型、工具、上下文與背景工作分別由專屬模組處理。"""
import asyncio
import os
from typing import AsyncGenerator, Dict, Optional
import httpx
from app.config import OLLAMA_BASE_URL, DEFAULT_MODEL, CONTEXT_TOKENS, OUTPUT_TOKENS, MODEL_READ_TIMEOUT, MAX_AUTONOMOUS_STEPS
from app.storage.context_manager import ContextManager
from app.core.execution import RunControl, call_details, execute_call
from app.core.conclusion import RunSummary, extract_final, failure_reason
from app.core.intent import detect_mode
from app.storage.jobs import job_manager
from app.logging_setup import log, log_context, setup_logging
from app.storage.memory import memory_manager
from app.core.model_client import stream_model
from app.storage.project_memory import project_context, update_project_memory
from app.core.prompt import prompt_messages, load_prompt
from app.tools import register_tools
from app.tools.registry import tool_registry
from app.tools.preferences import preference_source
from app.storage.workspace import workspace_scope, session_workspace

MAX_TEXT_ONLY_RECOVERIES = 2


class ChatAgent:
    def __init__(self, base_url=OLLAMA_BASE_URL, default_model=DEFAULT_MODEL):
        if not default_model:
            raise ValueError("請先複製 .env.example 為 .env，設定 DEFAULT_MODEL 為 Ollama 已安裝的模型名稱。")
        register_tools()
        self.base_url, self.default_model = base_url.rstrip("/"), default_model
        self.runs: Dict[str, RunControl] = {}

    def start_run(self, session_id):
        setup_logging()
        if session_id in self.runs:
            raise ValueError("此對話已有執行中的任務，請先完成或繼續原任務。")
        control = RunControl()
        self.runs[session_id] = control
        return control

    async def _update_memory(self, client, model, session_id):
        try:
            await update_project_memory(client, self.base_url, model, session_id)
        except Exception:
            log("memory.l2_failed", level=40, exc_info=True)
            return False
        return True

    async def stream_chat(self, session_id: str, user_message: str, model: Optional[str] = None,
                          mode: str = "auto", control: Optional[RunControl] = None, images=(),
                          reasoning_level: str = "medium") -> AsyncGenerator[Dict, None]:
        control = control or self.start_run(session_id)
        model = model or self.default_model
        session = memory_manager.get_session(session_id)
        token = log_context.set({**log_context.get(), "session_id": session_id, "run_id": control.run_id,
                                 "project_id": session["project_id"] if session else None})
        workspace_token = None
        preference_token = preference_source.set(user_message)
        output_images = []
        context = ContextManager(session_id, model)
        summary = RunSummary()
        final_content, sdd_saved, limit_reached = "", False, False
        saved_turn = False
        scratchpad = None
        empty_retry_used = False
        text_only_rounds, stop_reason = 0, "completed"
        log("run.start", model=model, mode=mode, reasoning_level=reasoning_level,
            user_message=user_message, images=list(images), max_steps=MAX_AUTONOMOUS_STEPS)
        try:
            workspace_token = workspace_scope.set(session_workspace(session))
            scratchpad = context.load() + [{"role": "user", "content": user_message, "_image_ids": list(images)}]
            yield {"type": "run_state", "state": "running", "phase": "preparing"}
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0, read=MODEL_READ_TIMEOUT)) as client:
                # 補上尚未摘要的舊專案對話；失敗不阻斷主要任務。
                await self._update_memory(client, model, session_id)
                project = project_context(session_id)
                if mode == "auto":
                    async for event in control.checkpoint():
                        yield event
                    scratchpad, _ = await context.prepare(client, self.base_url, project, scratchpad)
                    yield {"type": "run_state", "state": "running", "phase": "detecting"}
                    mode, reason = await detect_mode(client, self.base_url, model, scratchpad)
                else:
                    reason = "依所選規劃模式建立 SDD，完成後等待開始實作。" if mode == "plan" else "依需求直接處理。"
                yield {"type": "mode_selected", "mode": mode, "reason": reason, "reasoning_level": reasoning_level}
                for step in range(1, MAX_AUTONOMOUS_STEPS + 2):
                    async for event in control.checkpoint():
                        yield event
                    finalizing = step > MAX_AUTONOMOUS_STEPS
                    active_schemas = [] if finalizing else tool_registry.get_schemas(mode)
                    prefix = prompt_messages(os.getenv("DEFAULT_SYSTEM_PROMPT", load_prompt("system")),
                        mode, active_schemas, finalizing=finalizing, reasoning_level=reasoning_level) + ([] if finalizing else project)
                    if finalizing:
                        limit_reached = True
                        yield {"type": "run_state", "state": "running", "phase": "summarizing"}
                        if mode == "plan":
                            prefix.append({"role": "system", "content": "三份 SDD 保存狀態：" + ("已成功保存" if sdd_saved else "未成功保存，列為未完成")})
                    working = summary.messages(user_message) if finalizing else scratchpad
                    if context.measure(prefix + working, active_schemas) >= context.threshold:
                        yield {"type": "run_state", "state": "running", "phase": "compacting"}
                    try:
                        prepared, compacted = await context.prepare(client, self.base_url, prefix, working, active_schemas)
                        if not finalizing:
                            scratchpad = prepared
                    except Exception as error:
                        if not finalizing:
                            raise
                        log("run.limit_context_failed", level=40, exc_info=True)
                        final_content = summary.fallback(f"已達 {MAX_AUTONOMOUS_STEPS} 輪上限，結案整理未完成。")
                        if mode == "plan" and not sdd_saved:
                            final_content += "\n\nSDD 狀態：尚未成功保存三份文件。"
                        scratchpad.append({"role": "assistant", "content": final_content})
                        break
                    messages = prefix + prepared
                    if mode == "agent" and text_only_rounds and not finalizing:
                        # 上一輪是 assistant 純文字；必須以 user 訊息收尾，否則模型會把已結束的回合當成完成而直接 EOS（空回應）。
                        messages.append({"role": "user", "content": load_prompt("continue_task")})
                    yield {"type": "context_usage", "estimated_tokens": context.measure(messages, active_schemas),
                           "input_budget": context.input_budget, "threshold": context.threshold, "compacted": compacted}
                    context.save(scratchpad)
                    async for state in control.checkpoint():
                        yield state
                    yield {"type": "run_state", "state": "running", "phase": "summarizing" if finalizing else ""}
                    content, calls, thinking, summary_error = "", [], "", ""
                    model_details = {}
                    try:
                        async for event in stream_model(client, self.base_url, model, messages, active_schemas,
                                options={"num_ctx": CONTEXT_TOKENS, "num_predict": 2048 if finalizing else OUTPUT_TOKENS},
                                think=False if finalizing else None, retry_empty=not (finalizing or empty_retry_used)):
                            async for state in control.checkpoint():
                                yield state
                            if event["type"] == "model_done":
                                content, calls, thinking = event["content"], event["calls"], event["thinking"]
                                model_details = {key: event.get(key) for key in (
                                    "done_reason", "output_tokens", "prompt_tokens", "thinking_chars")}
                                context.observe(messages, active_schemas, event.get("prompt_tokens"))
                            else:
                                if event["type"] == "model_retry":
                                    empty_retry_used = True
                                yield {**event, "type": "progress" if event["type"] == "content" else event["type"],
                                       "step": step, "finalizing": finalizing}
                    except Exception as error:
                        if not finalizing:
                            raise
                        summary_error = str(error)
                        log("run.limit_summary_failed", level=40, exc_info=True)
                    if finalizing:
                        final_content = f"已達執行上限（{MAX_AUTONOMOUS_STEPS} 輪），已停止工具操作。\n\n" + (
                            content.strip() if content.strip() and not calls and not summary_error
                            else summary.fallback("模型未提供有效結案內容。"))
                        if mode == "plan" and not sdd_saved:
                            final_content += "\n\nSDD 狀態：尚未成功保存三份文件。"
                        scratchpad.append({"role": "assistant", "content": final_content})
                        break
                    if not calls:
                        if not content.strip():
                            log("run.empty_response", level=40, model=model, retried=empty_retry_used, **model_details)
                            if step == MAX_AUTONOMOUS_STEPS:
                                continue  # 最後一輪未結案，仍追加一次專用統整。
                            stop_reason = "empty_response"
                            raise RuntimeError("模型未產生回答或工具呼叫，且本次的空回應恢復額度已用完。"
                                               "請在 Log 查看 model.end 與 run.empty_response 的結束原因及輸出用量。")
                        final_text = extract_final(content) if mode == "agent" else None
                        if final_text is not None:
                            # 模型以 [final] 標記最終回答；不需再呼叫 finish_task。
                            log("run.final_marker", step=step, **model_details)
                            final_content = final_text
                            scratchpad.append({"role": "assistant", "content": final_content})
                            break
                        scratchpad.append({"role": "assistant", "content": content})
                        if mode == "plan" and not sdd_saved:
                            scratchpad.append({"role": "user", "content": "請先用 save_sdd 保存規格、方案與待辦，再交付；缺少資訊可明列假設。"})
                            continue
                        if step == MAX_AUTONOMOUS_STEPS:
                            continue
                        # 文字可作進度或說明；實作／對話必須透過 finish_task 明確結案。
                        text_only_rounds += 1
                        log("run.text_only_response", level=30, step=step, consecutive=text_only_rounds,
                            content=content, **model_details)
                        if text_only_rounds <= MAX_TEXT_ONLY_RECOVERIES:
                            continue
                        stop_reason = "no_tool_progress"
                        log("run.no_tool_progress", level=40, step=step, **model_details)
                        final_content = summary.fallback("模型連續未採取下一步或交付結論，已停止本次處理。")
                        scratchpad.append({"role": "assistant", "content": final_content})
                        break
                    text_only_rounds = 0
                    calls.sort(key=lambda call: call.get("function", {}).get("name") == "finish_task")
                    scratchpad.append({"role": "assistant", "content": content, "thinking": thinking, "tool_calls": calls})
                    finished = False
                    for index, call in enumerate(calls):
                        async for state in control.checkpoint():
                            yield state
                        name, arguments = call_details(call)
                        call_id = f"{control.run_id}-{step}-{index}"
                        yield {"type": "tool_start", "step": step, "call_id": call_id, "tool": name,
                               "args": arguments if isinstance(arguments, dict) else {}}
                        result = await execute_call(session_id, name, arguments,
                            {item["function"]["name"] for item in active_schemas}, mode=mode, sdd_saved=sdd_saved, call_id=call_id)
                        summary.record(name, arguments, result)
                        async for state in control.checkpoint():
                            yield state
                        yield {"type": "tool_done", "step": step, "call_id": call_id, "tool": name,
                               "ok": result.ok, "result_full": str(result), "images": result.images}
                        image_ids = [image["id"] for image in result.images]
                        output_images = (output_images + image_ids)[-4:]
                        scratchpad.append({"role": "tool", "tool_name": name,
                            "content": context.spill(result, preserve=name == "read_skill"), "_image_ids": image_ids})
                        if name == "save_sdd" and result.ok:
                            sdd_saved = True
                            yield {"type": "sdd_ready"}
                        if name == "finish_task" and result.ok:
                            final_content, finished = str(result), True
                            # finish_task 已排最後，其餘結果已記錄。
                    if mode == "plan" and sdd_saved:
                        if not finished:
                            final_content = ("規劃已完成，已保存需求規格、技術方案與任務清單。\n\n"
                                "可查看 `.specify/spec.md`、`.specify/plan.md`、`.specify/tasks.md`；"
                                "確認後按「開始實作」，便會依規格開始製作。")
                            scratchpad.append({"role": "assistant", "content": final_content})
                        finished = True
                    context.save(scratchpad)
                    if finished:
                        break
                pending = [job for job in job_manager.list(session_id) if job["status"] in {"running", "stopping"}]
                if pending:
                    final_content += f"\n\n仍有 {len(pending)} 個背景工作未結束，請至「執行」面板確認。"
                    scratchpad.append({"role": "assistant", "content": final_content})
                memory_manager.save_turn(session_id, user_message, final_content, images=images, assistant_images=output_images)
                saved_turn = True
                yield {"type": "answer", "content": final_content, "images": output_images}
                context.save(scratchpad)
                async for state in control.checkpoint():
                    yield state
                yield {"type": "run_state", "state": "running", "phase": "memory"}
                memory_ok = await self._update_memory(client, model, session_id)
                async for state in control.checkpoint():
                    yield state
                stop_reason = "step_limit" if limit_reached else stop_reason
                log("run.end", ok=stop_reason == "completed", level=20 if stop_reason == "completed" else 30,
                    conclusion=final_content, stop_reason=stop_reason)
                yield {"type": "done",
                       "memory_update_ok": memory_ok, "stop_reason": stop_reason}
        except asyncio.CancelledError:
            log("run.interrupted", level=30, exc_info=True)
            raise
        except Exception as error:
            message = str(error).strip() or type(error).__name__
            stop_reason = "empty_response" if stop_reason == "empty_response" else "failed"
            log("run.failed", level=40, exc_info=True, error_type=type(error).__name__, error=message, stop_reason=stop_reason)
            if not saved_turn:
                final_content = summary.fallback(failure_reason(error, stop_reason))
                pending = [job for job in job_manager.list(session_id) if job["status"] in {"running", "stopping"}]
                if pending:
                    final_content += "\n\n背景工作仍在執行，請至「執行」面板確認。"
                memory_manager.save_turn(session_id, user_message, final_content, images=images, assistant_images=output_images)
                if scratchpad is not None:
                    context.save(scratchpad + [{"role": "assistant", "content": final_content}])
                yield {"type": "answer", "content": final_content, "images": output_images}
            yield {"type": "error", "message": failure_reason(error, stop_reason), "stop_reason": stop_reason}
        finally:
            if self.runs.get(session_id) is control:
                self.runs.pop(session_id, None)
            if workspace_token is not None:
                workspace_scope.reset(workspace_token)
            preference_source.reset(preference_token)
            log_context.reset(token)
