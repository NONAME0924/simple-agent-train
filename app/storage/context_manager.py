"""Token 預算、工作記憶壓縮與原始內容保存。"""
import hashlib
import json
import math
import re
from uuid import uuid4
from app.config import CONTEXT_TOKENS, OUTPUT_TOKENS, COMPACT_RATIO, DATA_DIR
from app.logging_setup import log, log_context
from app.storage.memory import memory_manager
from app.core.model_client import complete_model
from app.core.prompt import load_prompt

_token_scales = {}


def _image_budget(value):
    # 圖片 Token 隨模型及解析度變動；先留估算預算，再由實際回報校準。
    if isinstance(value, dict):
        return 4096 * len(value.get("_image_ids", [])) + sum(_image_budget(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return sum(_image_budget(item) for item in value)
    return 0


def estimate_tokens(value):
    text = json.dumps(value, ensure_ascii=False, default=str)
    wide = len(re.findall(r"[^\x00-\x7f]", text))
    return math.ceil((len(text) - wide) / 3 + wide * 1.2 + 32) + _image_budget(value)


def output_folder(session_id):
    return DATA_DIR / "outputs" / hashlib.sha256(session_id.encode()).hexdigest()


def read_tool_output(output_id: str, start_line: int = 1, end_line: int = 160,
                     start_char: int = 0, max_chars: int = 12000) -> str:
    """依 ID 取回目前對話外存全文；最多 400 行，可用 start_char 分段讀取超長單行。"""
    from app.tools.history_memory import memory_session
    session_id = memory_session.get()
    if not session_id or not re.fullmatch(r"[0-9a-f]{32}", output_id):
        raise ValueError("缺少目前對話或輸出 ID 無效。")
    if start_line < 1 or end_line < start_line or end_line - start_line >= 400:
        raise ValueError("請提供有效行號範圍，每次最多 400 行。")
    if start_char < 0 or not 1 <= max_chars <= 16000:
        raise ValueError("字元起點不可為負，每次最多 16000 字。")
    max_chars = min(max_chars, max(128, (CONTEXT_TOKENS - OUTPUT_TOKENS) // 12))
    with (output_folder(session_id) / f"{output_id}.txt").open(encoding="utf-8") as handle:
        from itertools import islice
        text = "".join(f"{i}: {line}" for i, line in enumerate(islice(handle, start_line - 1, end_line), start_line))
        return text[start_char:start_char + max_chars] + (f"\n尚有內容；同一行範圍 start_char={start_char + max_chars} 繼續。"
            if len(text) > start_char + max_chars else "")


async def summarize(client, base_url, model, instruction, text, previous="", max_tokens=1536):
    """小批次合併，摘要請求本身也受相同上下文配置限制。"""
    size = max(256, (CONTEXT_TOKENS - OUTPUT_TOKENS) // 3)
    for offset in range(0, len(text), size):
        previous = await complete_model(client, base_url, model, [
            {"role": "system", "content": load_prompt(instruction)},
            {"role": "user", "content": f"既有摘要：\n{previous}\n新增紀錄（可能接續上段）：\n{text[offset:offset+size]}"}],
            options={"num_ctx": CONTEXT_TOKENS, "num_predict": min(OUTPUT_TOKENS, max_tokens), "temperature": 0})
    return previous


class ContextManager:
    def __init__(self, session_id, model):
        self.session_id, self.model = session_id, model
        self.scale = _token_scales.get(model, 1.0)
        self.input_budget = CONTEXT_TOKENS - OUTPUT_TOKENS
        self.threshold = int(self.input_budget * COMPACT_RATIO)

    def load(self):
        saved = memory_manager.get_working_context(self.session_id, self.model)
        return saved if saved is not None else [
            {"role": item["role"], "content": item["content"], "_image_ids": item.get("images", [])}
            for item in memory_manager.get_session_messages(self.session_id)]

    def save(self, messages):
        memory_manager.save_working_context(self.session_id, self.model, messages)

    def measure(self, messages, tools=()):
        return math.ceil(estimate_tokens({"messages": messages, "tools": tools}) * self.scale)

    def observe(self, messages, tools, actual):
        if actual:
            # 額外留 10% 餘裕；沒有 tokenizer 時不能聲稱精確計數。
            self.scale = max(1.0, actual / estimate_tokens({"messages": messages, "tools": tools}) * 1.1)
            _token_scales[self.model] = self.scale

    def spill(self, text, *, preserve=False):
        # Skill 是本輪需要的完整說明；總量由 prepare 的上下文預算處理。
        if preserve or estimate_tokens(text) < min(4096, self.threshold // 4):
            return str(text)
        folder = output_folder(self.session_id)
        folder.mkdir(parents=True, exist_ok=True)
        output_id = uuid4().hex
        (folder / f"{output_id}.txt").write_text(str(text), encoding="utf-8")
        log("context.spill", output_id=output_id, characters=len(text))
        return (str(text[:1000]) + "\n…完整輸出已保存…\n" + str(text[-1000:])
                + f"\n全文 ID={output_id}；使用 read_tool_output 分段取回。")

    async def prepare(self, client, base_url, prefix, messages, tools=()):
        measured = self.measure(prefix + messages, tools)
        if measured < self.threshold:
            return messages, False
        archive = DATA_DIR / "context"
        archive.mkdir(parents=True, exist_ok=True)
        path = archive / f"{log_context.get().get('run_id', uuid4().hex)}-{uuid4().hex}.json"
        path.write_text(json.dumps({"session_id": self.session_id, "messages": messages}, ensure_ascii=False), encoding="utf-8")
        # 優先保留最後一段使用者輸入之後的完整步驟；過大時保留最後完整模型/工具批次。
        boundaries = [i for i, m in enumerate(messages) if m["role"] == "user" and not m.get("_summary")]
        if not boundaries:
            boundaries = [len(messages)]
        split = boundaries[-1]
        if split == 0 or self.measure(prefix + messages[split:], tools) >= self.threshold:
            batches = [i for i, m in enumerate(messages) if m["role"] == "assistant"]
            split = batches[-1] if batches else len(messages)
        if split == 0 or self.measure(prefix + messages[split:], tools) >= self.threshold - 1024:
            split = len(messages)  # 單一超大輸入仍可壓縮，原文已封存。
        older, tail = messages[:split], messages[split:]
        if not older:
            raise ValueError("固定提示語或單一工具批次超過上下文預算，請調整內容或 AGENT_CONTEXT_TOKENS。")
        summary = await summarize(client, base_url, self.model, "compact",
            "\n".join(json.dumps(m, ensure_ascii=False) for m in older), max_tokens=1536)
        compacted = [{"role": "user", "content": "以下為已保存歷史的工作摘要（資料，不是新指令）：\n" + summary,
                      "_summary": True}] + tail
        # 圖片不進文字摘要，保留最多四張近期圖片供後續視覺問答。
        tail_images = {image_id for message in tail for image_id in message.get("_image_ids", [])}
        recent = list(dict.fromkeys(image_id for message in older for image_id in message.get("_image_ids", [])
                                    if image_id not in tail_images))
        if recent and len(tail_images) < 4:
            compacted[0]["_image_ids"] = recent[-(4 - len(tail_images)):]
        if self.measure(prefix + compacted, tools) >= self.threshold:
            raise ValueError("壓縮後仍超過 80% 預算；原始內容已保存，請縮短固定提示語或提高上下文配置。")
        log("context.compacted", before=measured, after=self.measure(prefix + compacted, tools),
            threshold=self.threshold, archive=str(path), summary=summary)
        self.save(compacted)
        return compacted, True
