"""保留 MCP 原始 Schema，將文字、資料與圖片接到現有工具結果。"""
import base64
import hashlib
import json
import re
from jsonschema.validators import validator_for
from app.storage.images import MAX_IMAGE_BYTES, MAX_IMAGES, save_image
from app.tools.registry import ToolResult


class MCPTool:
    def __init__(self, server, config, definition, manager):
        self.server, self.original_name = server, definition.name
        name = re.sub(r"[^A-Za-z0-9_-]", "_", definition.name)
        self.name = f"mcp__{server}__{name}"
        if len(self.name) > 64:
            self.name = self.name[:55] + "_" + hashlib.sha256(definition.name.encode()).hexdigest()[:8]
        self.func = self.call
        self.manager = manager
        self.modes = ("agent", "plan") if definition.name in config.read_only else ("agent",)
        self.parameters = definition.inputSchema
        validator = validator_for(self.parameters)
        validator.check_schema(self.parameters)
        self.validator = validator(self.parameters)
        self.schema = {"type": "function", "function": {"name": self.name,
            "description": f"[{server}] {definition.description or definition.name}", "parameters": self.parameters}}

    def validate(self, arguments):
        error = next(self.validator.iter_errors(arguments), None)
        if error:
            location = ".".join(map(str, error.absolute_path)) or "參數"
            raise ValueError(f"{location}：{error.message}")
        return arguments

    async def call(self, **arguments):
        return await self.manager.call(self.server, self.original_name, arguments)


def tool_result(result, session_id, server):
    texts, images, ok = [], [], not result.isError
    for block in result.content:
        if block.type == "text":
            texts.append(block.text)
        elif block.type == "image":
            try:
                if len(images) >= MAX_IMAGES or len(block.data) > (MAX_IMAGE_BYTES * 4 // 3 + 4):
                    raise ValueError("MCP 圖片超過附件數量或大小限制。")
                images.append(save_image(session_id, base64.b64decode(block.data, validate=True), f"{server}-view.png"))
            except (ValueError, OSError) as error:
                texts.append(f"圖片保存失敗：{error}")
                ok = False
        elif block.type == "resource_link":
            texts.append(f"資源：{block.uri}")
        else:
            texts.append(f"收到 {block.type} 內容；本版僅處理文字、資料與圖片。")
    if result.structuredContent is not None:
        texts.append(json.dumps(result.structuredContent, ensure_ascii=False))
    # Blender 部分工具把例外當普通文字回傳，仍要如實標成失敗。
    if server == "blender" and any(re.match(r"^(error\b|failed\b|could not\b)", text.strip(), re.I) for text in texts):
        ok = False
    text = "\n".join(texts) or ("已取得場景圖片。" if images else "工具未回傳文字。")
    return ToolResult(text, ok=ok, images=images)
