"""Ollama 請求與串流解析；不依賴任務流程。"""
import json
import time
import httpx
from app.config import MODEL_READ_TIMEOUT
from app.logging_setup import log, log_context
from app.storage.images import model_messages
from app.core.prompt import load_prompt


async def stream_model(client, base_url, model, messages, tools=(), options=None, think=None, retry_empty=False):
    payload = {"model": model, "messages": model_messages(messages, log_context.get().get("session_id")), "stream": True,
               "options": options or {}}
    if tools:
        payload["tools"] = tools
    if think is not None:
        payload["think"] = think
    started = time.perf_counter()
    last_line_at, received_lines = started, 0
    log("model.start", model=model, message_count=len(messages),
        input_characters=sum(len(str(message.get("content") or "")) for message in messages),
        tools=[tool["function"]["name"] for tool in tools], options=payload["options"], think=think,
        read_timeout=MODEL_READ_TIMEOUT)
    text, thinking, calls = "", "", []
    try:
        async with client.stream("POST", f"{base_url}/api/chat", json=payload) as response:
            if response.status_code != 200:
                body = (await response.aread()).decode("utf-8", errors="replace")
                raise RuntimeError(f"Ollama HTTP {response.status_code}: {body}")
            async for line in response.aiter_lines():
                last_line_at = time.perf_counter()
                received_lines += 1
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    log("model.invalid_chunk", level=40, exc_info=True, raw=line)
                    raise
                if data.get("error"):
                    raise RuntimeError(data["error"])
                message = data.get("message", {})
                if message.get("thinking"):
                    thinking += message["thinking"]
                    yield {"type": "thinking", "delta": message["thinking"]}
                if message.get("content"):
                    text += message["content"]
                    yield {"type": "content", "delta": message["content"]}
                calls.extend(message.get("tool_calls") or [])
                if data.get("done"):
                    valid = bool(text.strip() or calls)
                    details = {"done_reason": data.get("done_reason"), "prompt_tokens": data.get("prompt_eval_count"),
                               "output_tokens": data.get("eval_count"), "thinking_chars": len(thinking),
                               "content_chars": len(text), "tool_call_count": len(calls)}
                    log("model.end", model=model, ok=valid, level=20 if valid else 30,
                        content=text, calls=calls, **details,
                        duration=time.perf_counter() - started)
                    if not valid and retry_empty:
                        await response.aclose()
                        yield {"type": "model_retry"}
                        log("model.empty_retry", level=30, model=model, think=think, **details)
                        retry_messages = [{"role": "system", "content": load_prompt("empty_response")}] + messages
                        async for event in stream_model(client, base_url, model, retry_messages, tools,
                                options=options, think=think, retry_empty=False):
                            yield event
                        return
                    yield {"type": "model_done", "content": text, "thinking": thinking, "calls": calls, **details}
                    return
        raise RuntimeError("模型串流在完成標記前中斷。")
    except BaseException as error:
        log("model.failed", level=40, exc_info=True, model=model, content=text,
            thinking=thinking, calls=calls, error_type=type(error).__name__,
            error=str(error) or type(error).__name__, read_timeout=MODEL_READ_TIMEOUT,
            received_lines=received_lines, last_line_age=time.perf_counter() - last_line_at,
            duration=time.perf_counter() - started)
        if isinstance(error, httpx.ReadTimeout):
            raise RuntimeError(
                f"等待 Ollama 回應逾時（連續 {MODEL_READ_TIMEOUT:g} 秒未讀到後續資料）。"
                "本次處理已中斷，未完成接收的工具呼叫不會執行。"
                "請查看 Ollama 服務紀錄、模型負載與連線狀態；"
                "可在 .env 調整 AGENT_MODEL_READ_TIMEOUT 後重啟。") from error
        raise


async def complete_model(client, base_url, model, messages, *, options=None):
    result = None
    async for event in stream_model(client, base_url, model, messages, options=options, think=False):
        if event["type"] == "model_done":
            result = event
    if not result or result["calls"] or not result["content"].strip():
        raise RuntimeError("摘要模型未提供有效文字。")
    return result["content"].strip()
