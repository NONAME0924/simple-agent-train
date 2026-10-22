/* 日誌按需讀取；不加入定時查詢。 */
(() => {
  const byId = id => document.getElementById(id);
  let revision = 0;
  window.resetLogPanel = function () {
    revision++;
    byId("logs-list").replaceChildren();
    byId("logs-status").textContent = "";
    byId("logs-download").removeAttribute("href");
    if (!byId("panel-logs").hidden) window.refreshLogPanel();
  };
  window.refreshLogPanel = async function () {
    if (!currentSessionId) return;
    const request = ++revision, session = currentSessionId;
    const query = new URLSearchParams({ scope: byId("logs-scope").value, level: byId("logs-level").value,
      category: byId("logs-category").value });
    const base = `/api/sessions/${encodeURIComponent(session)}/logs`;
    byId("logs-status").textContent = "讀取中…";
    byId("logs-list").replaceChildren();
    byId("logs-download").href = `${base}/download?scope=${encodeURIComponent(query.get("scope"))}`;
    try {
      const data = await api(`${base}?${query}`);
      if (request !== revision || session !== currentSessionId) return;
      byId("logs-status").textContent = `${data.source} · ${data.entries.length} 筆${data.limited ? " · 顯示近期紀錄，較早內容請下載來源檔或查看輪替備份" : ""}`;
      if (!data.entries.length) byId("logs-list").textContent = "目前讀取範圍內沒有符合的日誌。";
      for (const entry of data.entries) {
        const row = document.createElement("details"); row.className = "log-entry";
        row.dataset.level = entry.level;
        const title = document.createElement("summary");
        const stamp = new Date(entry.time);
        const category = { system: "系統", model: "模型", tool: "工具", mcp: "MCP 連線", memory: "記憶與上下文" }[entry.category] || "系統";
        title.textContent = `${Number.isNaN(stamp.getTime()) ? entry.time || "" : stamp.toLocaleString()} · ${entry.level || "INFO"} · ${category} · ${entry.tool || entry.event || entry.logger || "事件"}`;
        const body = document.createElement("pre"); body.className = "panel-pre";
        body.textContent = JSON.stringify(entry, null, 2);
        if (entry.traceback) body.textContent += `\n\n錯誤堆疊：\n${entry.traceback}`;
        row.append(title, body); byId("logs-list").appendChild(row);
      }
    } catch (error) {
      if (request === revision && session === currentSessionId) byId("logs-status").textContent = error.message;
    }
  };
  for (const id of ["logs-level", "logs-scope", "logs-category"]) byId(id).onchange = () => window.refreshLogPanel();
  byId("logs-refresh").onclick = () => window.refreshLogPanel();
})();
