"""專屬協程持有 SDK 連線；同一外部實例依任務排隊，不自動重送操作。"""
import asyncio
import time
import sys
import tempfile
from contextlib import AsyncExitStack
from datetime import timedelta
import httpx
from app.config import APP_DIR
from app.logging_setup import log, log_context
from app.mcp.adapter import MCPTool, tool_result
from app.mcp.config import bind, bindings, scope_key, servers
from app.storage.memory import memory_manager
from app.tools.history_memory import memory_session


def _error_message(error):
    if isinstance(error, ModuleNotFoundError):
        return (f"目前 Python（{sys.executable}）缺少套件 {error.name}。"
                "Linux／macOS 請使用 sh run.sh 準備環境；Windows 請完整更新內附 runtime。")
    nested = getattr(error, "exceptions", ())
    if nested:
        return "；".join(dict.fromkeys(_error_message(item) for item in nested))
    return f"{type(error).__name__}: {error}" if str(error) else type(error).__name__


class Connection:
    def __init__(self, name, config, manager):
        self.name, self.config, self.manager = name, config, manager
        self.tools, self.error, self.application = {}, "", None
        self.application_error = ""
        self.stderr = tempfile.TemporaryFile()
        self.queue = asyncio.Queue()
        self.ready = asyncio.get_running_loop().create_future()
        self.ready.add_done_callback(lambda item: item.exception() if not item.cancelled() else None)
        self.active = False
        self.task = asyncio.create_task(self.serve())

    async def serve(self):
        current = None
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            from mcp.client.streamable_http import streamable_http_client
            async with AsyncExitStack() as stack:
                config = self.config
                if config.url:
                    http = await stack.enter_async_context(httpx.AsyncClient(headers=config.headers,
                        timeout=httpx.Timeout(config.connect_timeout, read=config.timeout)))
                    streams = await stack.enter_async_context(streamable_http_client(config.url, http_client=http))
                else:
                    params = StdioServerParameters(command=config.command, args=config.args, env=config.env, cwd=str(APP_DIR))
                    streams = await stack.enter_async_context(stdio_client(params, errlog=self.stderr))
                session = await stack.enter_async_context(ClientSession(*streams[:2],
                    read_timeout_seconds=timedelta(seconds=config.connect_timeout)))
                await session.initialize()
                cursor = None
                while True:
                    page = await session.list_tools(cursor=cursor)
                    for definition in page.tools:
                        if not config.include or definition.name in config.include:
                            tool = MCPTool(self.name, config, definition, self.manager)
                            if tool.name in self.tools:
                                raise ValueError("MCP 工具名稱轉換後重複，請縮小 include 範圍。")
                            self.tools[tool.name] = tool
                    cursor = page.nextCursor
                    if not cursor:
                        break
                log("mcp.connected", server=self.name, instance=config.instance, tools=list(self.tools))
                self.ready.set_result(None)
                while True:
                    current = await self.queue.get()
                    tool, arguments, context, future = current
                    token = log_context.set(context)
                    started = time.perf_counter()
                    self.active = True
                    try:
                        raw = await session.call_tool(tool, arguments, read_timeout_seconds=timedelta(seconds=config.timeout))
                        result = await asyncio.to_thread(tool_result, raw, context["session_id"], self.name)
                        if tool == "get_scene_info":
                            self.application = result.ok
                            self.application_error = "" if result.ok else str(result)
                        log("mcp.result", server=self.name, instance=config.instance, tool=tool,
                            ok=result.ok, images=result.images, duration=time.perf_counter() - started,
                            **({} if context.get("call_id") else {"arguments": arguments, "result": str(result)}),
                            level=20 if result.ok else 40)
                        if not future.done():
                            future.set_result(result)
                    except asyncio.CancelledError:
                        if not future.done():
                            future.set_exception(RuntimeError("MCP 連線已關閉，執行中的操作結果未確認。"))
                        raise
                    except Exception as error:
                        self.error = f"MCP 呼叫中斷，操作結果未確認：{_error_message(error)}。請先確認 Blender 狀態，再手動中斷及重新連線。"
                        log("mcp.call_failed", level=40, exc_info=True, server=self.name, tool=tool,
                            arguments=arguments, outcome="unknown", duration=time.perf_counter() - started)
                        if not future.done():
                            future.set_exception(RuntimeError(self.error))
                        break
                    finally:
                        self.active = False
                        current = None
                        log_context.reset(token)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.error = _error_message(error)
            # 子程序結束後讀取尾端，保留原始啟動錯誤，避免只剩 EOF／TaskGroup。
            self.stderr.seek(0, 2)
            self.stderr.seek(max(0, self.stderr.tell() - 8192))
            stderr = self.stderr.read().decode("utf-8", errors="replace").strip()
            if stderr:
                self.error += "\nMCP 程序輸出（尾端）：\n" + stderr
            log("mcp.connection_failed", level=40, exc_info=True, server=self.name, error=self.error)
        finally:
            self.stderr.close()
            error = RuntimeError(self.error or "MCP 連線已關閉。")
            if not self.ready.done():
                self.ready.set_exception(error)
            pending = ([current] if current else [])
            while not self.queue.empty():
                pending.append(self.queue.get_nowait())
            for _, _, _, future in pending:
                if not future.done():
                    future.set_exception(error)

    async def call(self, tool, arguments, context):
        if self.task.done() or self.error:
            raise RuntimeError(self.error or "MCP 已離線，請手動重新連線。")
        future = asyncio.get_running_loop().create_future()
        # 呼叫端斷線不取消已送出的操作；結果仍由連線協程保存及記錄。
        future.add_done_callback(lambda item: item.exception() if not item.cancelled() else None)
        self.queue.put_nowait((tool, arguments, context, future))
        return await asyncio.shield(future)


class MCPManager:
    def __init__(self):
        self.connections, self.locks, self.owners = {}, {}, {}
        self.connection_locks = {}

    def status(self, session):
        scope, bound = scope_key(session), bindings()
        items = []
        for name, config in servers().items():
            connection = self.connections.get(name)
            if connection:
                config = connection.config  # 先顯示實際連線；修改設定後仍能解除舊綁定。
            connected = bool(connection and connection.ready.done() and not connection.task.done() and not connection.error)
            items.append({"name": name, "instance": config.instance, "skill": config.skill,
                "bound": bound.get(config.instance) == scope, "available": bound.get(config.instance) in (None, scope),
                "connected": connected, "application_ok": connection.application if connection else None,
                "phase": "failed" if connection and connection.error else "ready" if connected else "starting" if connection and not connection.task.done() else "disconnected",
                "error": (connection.error or connection.application_error) if connection else "", "busy": config.instance in self.owners,
                "tools": [{"name": tool.name, "read_only": "plan" in tool.modes}
                          for tool in connection.tools.values()] if connected else []})
        return items

    async def connect(self, session, name):
        async with self.connection_locks.setdefault(name, asyncio.Lock()):
            return await self._connect(session, name)

    async def _connect(self, session, name):
        config = servers().get(name)
        if config is None:
            raise ValueError("找不到 MCP 設定。")
        connection = self.connections.get(name)
        if connection and connection.task.done():
            # 只重啟已結束的連線程序；不重送任何場景工具操作。
            self.connections.pop(name)
            connection = None
        if connection is not None and connection.config != config:
            raise ValueError("MCP 設定已修改，請先中斷舊連線再重新連線。")
        previous_scope = bindings().get(config.instance)
        bind(config.instance, scope_key(session))
        if connection is None:
            log("mcp.connecting", server=name, instance=config.instance)
            connection = self.connections[name] = Connection(name, config, self)
        try:
            await asyncio.wait_for(asyncio.shield(connection.ready), config.connect_timeout)
        except Exception as error:
            if isinstance(error, asyncio.TimeoutError):
                connection.error = f"MCP 初始化超過 {config.connect_timeout} 秒，已停止本次連線。"
            if not connection.task.done():
                connection.task.cancel()
                await asyncio.gather(connection.task, return_exceptions=True)
            # 取出 Future 例外，避免未處理例外；保留錯誤供介面顯示。
            if connection.ready.done() and not connection.ready.cancelled():
                connection.ready.exception()
            connection.error = connection.error or "MCP 連線逾時。"
            if previous_scope is None:
                bind(config.instance, None)
            log("mcp.connect_failed", level=40, server=name, instance=config.instance, error=connection.error)
            raise RuntimeError(connection.error)
        if connection.task.done() or connection.error:
            raise RuntimeError(connection.error or "請先中斷舊連線，再重新連線。")
        return connection

    def tools_for(self, session):
        scope, bound = scope_key(session), bindings()
        return {name: tool for connection in self.connections.values()
                if bound.get(connection.config.instance) == scope and connection.ready.done()
                and not connection.task.done() and not connection.error
                for name, tool in connection.tools.items()}

    async def call(self, server, tool, arguments):
        session_id = memory_session.get()
        session = memory_manager.get_session(session_id)
        connection = self.connections.get(server)
        if not session or not connection or bindings().get(connection.config.instance) != scope_key(session):
            raise ValueError("此 MCP 尚未綁定目前專案／對話，請先連線。")
        context = {**log_context.get(), "session_id": session_id}
        run_id, instance = context.get("run_id"), connection.config.instance
        if not run_id:
            raise ValueError("MCP 工具只能在 Agent 任務中執行。")
        if self.owners.get(instance) != run_id:
            lock = self.locks.setdefault(instance, asyncio.Lock())
            log("mcp.waiting", server=server, instance=instance)
            await lock.acquire()
            self.owners[instance] = run_id
        return await connection.call(tool, arguments, context)

    def release(self, run_id):
        for instance, owner in list(self.owners.items()):
            if owner == run_id:
                self.owners.pop(instance)
                self.locks[instance].release()

    async def disconnect(self, session, name):
        async with self.connection_locks.setdefault(name, asyncio.Lock()):
            await self._disconnect(session, name)

    async def _disconnect(self, session, name):
        connection = self.connections.get(name)
        config = connection.config if connection else servers().get(name)
        if config is None or bindings().get(config.instance) != scope_key(session):
            raise ValueError("這個連線未綁定目前專案／對話。")
        related = {key: item for key, item in self.connections.items() if item.config.instance == config.instance}
        if config.instance in self.owners or any(item.active for item in related.values()):
            raise ValueError("仍有任務使用此 MCP，請等待任務結束。")
        for key, item in related.items():
            item.task.cancel()
        await asyncio.gather(*(item.task for item in related.values()), return_exceptions=True)
        for key in related:
            self.connections.pop(key, None)
        bind(config.instance, None)
        log("mcp.disconnected", server=name, instance=config.instance)

    async def close(self):
        for connection in self.connections.values():
            connection.task.cancel()
        await asyncio.gather(*(item.task for item in self.connections.values()), return_exceptions=True)
        self.connections.clear()

    async def detach(self, session):
        configs = {**servers(), **{name: item.config for name, item in self.connections.items()}}
        for name, config in configs.items():
            if bindings().get(config.instance) == scope_key(session):
                await self.disconnect(session, name)


mcp_manager = MCPManager()


async def connect_mcp(server: str = "blender") -> str:
    """連線並綁定 MCP 到目前專案／對話；預設 Blender。先讀取對應 Skill。
    成功後下一輪會提供該服務的完整工具 Schema；此動作不修改 Blender 場景。
    """
    session = memory_manager.get_session(memory_session.get())
    if not session:
        raise ValueError("缺少目前對話。")
    connection = await mcp_manager.connect(session, server)
    return f"已連線 {server}，取得 {len(connection.tools)} 個工具。連線不代表場景已確認，請用場景查詢工具確認。"


def list_mcp_connections() -> str:
    """列出目前專案／對話可用的 MCP、綁定狀態與對應 Skill，不顯示憑證。"""
    session = memory_manager.get_session(memory_session.get())
    return str(mcp_manager.status(session)) if session else "缺少目前對話。"
