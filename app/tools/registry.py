"""工具定義、嚴格參數驗證與註冊；執行及 log 由 core.execution 負責。"""
import inspect
from typing import Dict, List, Any, Callable
from pydantic import ConfigDict, create_model


class ToolResult(str):
    def __new__(cls, content, ok=True, images=()):
        result = super().__new__(cls, str(content))
        result.ok = ok
        result.images = list(images)
        return result

    @classmethod
    def failed(cls, content):
        return cls(content, ok=False)


class Tool:
    """封裝可被 LLM 調用的工具"""

    def __init__(self, func: Callable, name: str = None, description: str = None, modes: tuple = ("agent",)):
        self.func = func
        self.name = name or func.__name__
        self.description = description or (func.__doc__ or "").strip()
        self.modes = modes
        fields = {
            key: (param.annotation if param.annotation is not inspect.Parameter.empty else str,
                  param.default if param.default is not inspect.Parameter.empty else ...)
            for key, param in inspect.signature(func).parameters.items()
        }
        # Schema 與執行驗證共用函式簽名；拒絕未知欄位及錯誤型別，不猜測參數名稱。
        self.arguments = create_model(self.name + "Arguments",
            __config__=ConfigDict(extra="forbid", strict=True), **fields)
        self.schema = {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.arguments.model_json_schema()
            }
        }

    def validate(self, arguments):
        return self.arguments.model_validate(arguments).model_dump()


class ToolRegistry:
    """管理所有可用工具的註冊與執行中心"""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, func: Callable = None, name: str = None, description: str = None, modes: tuple = ("agent",)):
        """註冊工具；名稱、說明與可用模式同時供 Schema、提示語及執行限制使用。"""
        if func is None:
            # 作為有參數的裝飾器 @tool_registry.register(name="...", description="...")
            def decorator(f):
                self._register_func(f, name, description, modes)
                return f
            return decorator
        else:
            self._register_func(func, name, description, modes)
            return func

    def _register_func(self, func: Callable, name: str = None, description: str = None, modes: tuple = ("agent",)):
        tool = Tool(func, name, description, modes)
        self._tools[tool.name] = tool

    def get_schemas(self, mode: str = None) -> List[Dict[str, Any]]:
        """依模式取得工具清單，也是動態提示語的唯一工具來源。"""
        return [tool.schema for tool in self._tools.values() if mode is None or mode in tool.modes]

    def get_tool(self, name):
        return self._tools.get(name)

# 建立全局單例註冊中心
tool_registry = ToolRegistry()
