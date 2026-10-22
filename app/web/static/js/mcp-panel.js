/* MCP 狀態僅按需更新，設定由 mcp.json 與 .env 管理。 */
(() => {
  const byId = id => document.getElementById(id);
  let revision = 0;
  window.resetMcpPanel = function () {
    revision++;
    byId("mcp-list").replaceChildren(); byId("mcp-status").textContent = "";
    if (!byId("panel-mcp").hidden) window.refreshMcpPanel();
  };
  window.refreshMcpPanel = async function (server = "", action = "") {
    if (!currentSessionId) return;
    const request = ++revision, session = currentSessionId;
    const base = `/api/sessions/${encodeURIComponent(session)}/mcp`;
    byId("mcp-status").textContent = action === "connect" ? "啟動 MCP 並確認 Blender 場景，請稍候…" : action ? "中斷連線…" : "讀取中…";
    byId("mcp-list").querySelectorAll("button").forEach(button => { button.disabled = true; });
    try {
      let actionError = "";
      if (action) {
        try { await api(`${base}/${encodeURIComponent(server)}/${action}`, "POST"); }
        catch (error) { actionError = error.message; }
      }
      const data = await api(base);
      if (request !== revision || session !== currentSessionId) return;
      const list = byId("mcp-list"); list.replaceChildren();
      byId("mcp-status").textContent = actionError ? `${server} 操作未完成，請展開該項目的錯誤資訊。` : data.servers.length ? "" : "尚未設定 MCP。";
      for (const item of data.servers) {
        const row = document.createElement("div"); row.className = "mcp-entry";
        const title = document.createElement("strong"); title.textContent = item.name;
        const status = document.createElement("p"); status.className = "help-text";
        status.textContent = `${item.instance} · ${!item.available ? "已綁定其他專案／對話" : item.connected ? item.application_ok === true ? "Blender 場景可用" : item.application_ok === false ? "MCP 已連線，Blender 尚未就緒" : "MCP 已連線，場景尚未確認" : item.phase === "failed" ? "MCP 連線失敗，可重試" : item.phase === "starting" ? "MCP 啟動中" : "未連線"}${item.busy ? " · 任務使用中" : ""}`;
        row.append(title, status);
        const buttons = document.createElement("div"); buttons.className = "button-row";
        for (const [actionName, label] of [["connect", item.connected ? "重新確認" : "連線"], ["disconnect", "中斷並解除綁定"]]) {
          const button = document.createElement("button"); button.className = "text-button"; button.textContent = label;
          button.disabled = !item.available || item.busy || (actionName === "disconnect" && !item.bound);
          button.onclick = () => window.refreshMcpPanel(item.name, actionName); buttons.appendChild(button);
        }
        row.appendChild(buttons);
        const message = item.name === server && actionError ? actionError : item.error;
        if (message) {
          const error = document.createElement("details"), title = document.createElement("summary"), body = document.createElement("pre");
          error.className = "runtime-error"; title.textContent = "連線錯誤與排查資訊";
          body.className = "panel-pre"; body.textContent = message;
          error.append(title, body); row.appendChild(error);
        }
        if (item.tools.length) {
          const details = document.createElement("details"), summary = document.createElement("summary"), tools = document.createElement("pre");
          summary.textContent = `${item.tools.length} 個工具 · Skill：${item.skill || "未指定"}`;
          tools.className = "panel-pre"; tools.textContent = item.tools.map(tool => `${tool.read_only ? "查詢" : "實作"} · ${tool.name}`).join("\n");
          details.append(summary, tools); row.appendChild(details);
        }
        list.appendChild(row);
      }
    } catch (error) {
      if (request === revision && session === currentSessionId) {
        byId("mcp-status").textContent = error.message;
        byId("mcp-list").querySelectorAll("button").forEach(button => { button.disabled = false; });
      }
    }
  };
  byId("mcp-refresh").onclick = () => window.refreshMcpPanel();
})();
