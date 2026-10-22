"""自動模式先由模型判斷意圖，再開放對應模式的工具。"""
import json
import httpx


from app.core.prompt import load_prompt
from app.logging_setup import log, log_context
from app.storage.images import model_messages
from app.config import CONTEXT_TOKENS


async def detect_mode(client, base_url, model, messages):
    try:
        log("intent.start", model=model, message_count=len(messages))
        response = await client.post(f"{base_url}/api/chat", json={
            "model": model,
            "messages": [{"role": "system", "content": load_prompt("intent")}] + model_messages(messages, log_context.get().get("session_id")),
            "stream": False,
            "think": False,
            "format": {
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["agent", "plan"]},
                    "reason": {"type": "string"},
                },
                "required": ["mode", "reason"],
                "additionalProperties": False,
            },
            "options": {"temperature": 0, "num_ctx": CONTEXT_TOKENS, "num_predict": 256},
        })
        if response.status_code != 200:
            raise RuntimeError(f"Ollama HTTP {response.status_code}: {response.text}")
        decision = json.loads(response.json()["message"]["content"])
        if not isinstance(decision, dict) or decision.get("mode") not in ("agent", "plan"):
            raise ValueError("模型未回傳有效模式")
        log("intent.end", decision=decision, ok=True)
        return decision["mode"], str(decision.get("reason") or "依本次需求選擇模式")
    except (httpx.HTTPError, KeyError, TypeError, ValueError, RuntimeError) as error:
        log("intent.failed", level=40, exc_info=True)
        raise RuntimeError("預設模式的意圖判斷失敗，請稍後重試；完整錯誤已記錄於 Log。") from error
