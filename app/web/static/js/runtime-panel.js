/* 背景工作與 L2 資料面板；不參與聊天串流控制。 */
(() => {
  let loading = false;
  let renderedSession = "";
  let renderedProject = "";
  let timer = null, hasActiveJobs = false, pendingRefresh = false, pendingMemory = false, pollDelay = 10000;
  const jobRows = new Map();
  function schedulePoll() {
    clearTimeout(timer);
    if (hasActiveJobs && renderedSession === currentSessionId && !document.hidden) {
      timer = setTimeout(() => window.refreshRuntimePanel(false), pollDelay);
    }
  }
  const labels = { running: "執行中", stopping: "停止中", completed: "已完成", failed: "失敗", killed: "已停止", interrupted: "已中斷" };

  async function loadJob(item, base, session, project, force = false) {
    if (item.loading || !item.row.open || (!force && item.loadedStatus === item.status && !["running", "stopping"].includes(item.status))) return;
    item.loading = true;
    if (!item.loadedStatus) item.output.textContent = "讀取中…";
    try {
      const job = await api(`${base}/${encodeURIComponent(item.id)}`);
      if (session !== currentSessionId || project !== currentProjectId || !item.row.isConnected) return;
      item.loadedStatus = job.status;
      item.output.textContent = `${labels[job.status]} · ID=${job.id}\n開始=${job.started_at}\n結束=${job.ended_at || (job.status === "interrupted" ? "未知（紀錄已中斷）" : "尚未結束")}\n退出碼=${job.exit_code ?? "尚無"}\n${job.error || ""}\nstdout（尾端）:\n${job.stdout}\nstderr（尾端）:\n${job.stderr}`;
      item.links.replaceChildren();
      for (const kind of ["stdout", "stderr"]) {
        const link = document.createElement("a");
        link.href = `${base}/${encodeURIComponent(job.id)}/output/${kind}`;
        link.textContent = `下載完整 ${kind}`; link.className = "text-button"; link.download = "";
        item.links.appendChild(link);
      }
      if (job.changed_files?.length && job.workspace_matches !== false) {
        const title = document.createElement("div");
        title.textContent = "工作期間變更的檔案（可能包含同工作區其他任務的變更）：";
        item.links.appendChild(title);
        for (const path of job.changed_files) {
          const link = document.createElement("a");
          link.href = workspaceUrl(`/api/workspace/download?path=${encodeURIComponent(path)}`, session);
          link.textContent = path; link.className = "text-button"; link.download = "";
          item.links.appendChild(link);
        }
      }
    } catch (error) {
      if (session === currentSessionId && project === currentProjectId && item.row.isConnected) {
        item.loadedStatus = ""; item.output.textContent = `${error.message}（收合後可再次展開重試）`;
      }
    } finally { item.loading = false; }
  }

  window.refreshRuntimePanel = async function (includeMemory = true) {
    if (!currentSessionId) return;
    if (loading) { pendingRefresh = true; pendingMemory ||= includeMemory; return; }
    clearTimeout(timer);
    loading = true;
    const sessionId = currentSessionId;
    const projectId = currentProjectId;
    const base = `/api/sessions/${encodeURIComponent(sessionId)}/jobs`;
    try {
      const data = await api(base);
      if (sessionId !== currentSessionId || projectId !== currentProjectId) return;
      if (renderedSession !== sessionId || renderedProject !== projectId) {
        includeMemory = true;
        jobRows.clear();
        document.getElementById("job-list").replaceChildren();
        document.getElementById("context-usage").textContent = sessionRuns.get(sessionId)?.contextUsage || "上下文用量會在執行時更新。";
        document.getElementById("project-memory-text").textContent = "";
        delete document.getElementById("runtime-error").dataset.memoryError;
        renderedSession = sessionId;
      }
      if (renderedProject !== projectId) {
        document.getElementById("project-memory-text").textContent = "";
        renderedProject = projectId;
        includeMemory = true;
      }
      const active = data.jobs.filter(job => ["running", "stopping"].includes(job.status)).length;
      hasActiveJobs = active > 0; pollDelay = 10000;
      document.getElementById("job-count").textContent = `${active} 個進行中 / 共 ${data.jobs.length} 個`;
      const background = document.getElementById("background-status");
      const latest = data.jobs[data.jobs.length - 1];
      const failed = latest && ["failed", "interrupted"].includes(latest.status);
      background.classList.toggle("hidden", !active && !failed);
      background.classList.toggle("danger", !active && failed);
      background.textContent = active ? `背景工作 ${active} 個執行中` : failed ? "背景工作失敗／中斷" : "";
      const list = document.getElementById("job-list");
      const ids = new Set(data.jobs.map(job => job.id));
      for (const [id, item] of jobRows) {
        if (!ids.has(id)) { item.row.remove(); jobRows.delete(id); }
      }
      if (data.jobs.length && !jobRows.size) list.replaceChildren();
      for (const job of data.jobs.slice().sort((a, b) => Date.parse(a.started_at) - Date.parse(b.started_at))) {
        let item = jobRows.get(job.id);
        if (!item) {
          const row = document.createElement("details"), info = document.createElement("summary");
          const output = document.createElement("pre"), links = document.createElement("div");
          const stop = document.createElement("button");
          row.className = "job-entry"; output.className = "panel-pre"; links.className = "job-downloads";
          stop.className = "text-button danger"; stop.textContent = "停止工作";
          item = { id: job.id, row, info, output, links, stop, loadedStatus: "", loading: false };
          row.ontoggle = () => { if (row.open) loadJob(item, base, sessionId, projectId); };
          stop.onclick = async () => {
            stop.disabled = true;
            try { await api(`${base}/${encodeURIComponent(job.id)}/stop`, "POST"); }
            catch (error) { alert(error.message); }
            window.refreshRuntimePanel(false);
          };
          row.append(info, stop, output, links); jobRows.set(job.id, item);
          // 依開始時間加入新項目；更新時保留既有展開內容原位。
          list.prepend(row);
        }
        item.status = job.status;
        const elapsed = Math.max(0, Math.floor((Date.parse(job.ended_at || job.interrupted_at || new Date().toISOString()) - Date.parse(job.started_at)) / 1000));
        item.info.textContent = `${labels[job.status] || job.status} · ${job.argv[1] || "Python"} · ${elapsed} 秒 · ${job.id.slice(0, 8)}`;
        item.stop.hidden = !["running", "stopping"].includes(job.status);
        item.stop.disabled = job.status === "stopping";
        await loadJob(item, base, sessionId, projectId, includeMemory);
        if (sessionId !== currentSessionId || projectId !== currentProjectId) return;
      }
      if (!data.jobs.length) list.textContent = "目前沒有背景工作。Agent 暫停不會停止已啟動的工作。";
      if (includeMemory) {
        const text = document.getElementById("project-memory-text");
        if (!projectId) text.textContent = "一般對話不建立 L2 專案記憶。";
        else {
          const result = await api(`/api/projects/${encodeURIComponent(projectId)}/memory`);
          if (sessionId !== currentSessionId || projectId !== currentProjectId) return;
          text.textContent = result.memory
            ? `更新=${result.memory.updated_at} · 來源至訊息 #${result.memory.source_cursor}\n\n${result.memory.summary}`
            : "尚無 L2 摘要；專案對話執行後會自動更新。";
          text.textContent += "\n\n固定記憶：\n" + (result.pinned || "尚無固定內容");
        }
      }
      window.refreshProjectTools?.(includeMemory);
      const notice = document.getElementById("runtime-error");
      notice.textContent = notice.dataset.memoryError || "";
    } catch (error) {
      pollDelay = Math.min(pollDelay * 2, 60000);
      if (sessionId === currentSessionId && projectId === currentProjectId) document.getElementById("runtime-error").textContent = error.message;
    } finally {
      loading = false;
      if (pendingRefresh) {
        const memory = pendingMemory; pendingRefresh = pendingMemory = false;
        window.refreshRuntimePanel(memory);
      } else schedulePoll();
    }
  };
  document.addEventListener("visibilitychange", () => {
    clearTimeout(timer);
    if (!document.hidden && hasActiveJobs) window.refreshRuntimePanel(false);
  });
})();
