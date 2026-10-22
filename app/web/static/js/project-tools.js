/* L2 管理、SDD 待辦，以及文件與圖片附件。 */
(() => {
  const byId = id => document.getElementById(id);
  const statuses = { pending: "未開始", running: "進行中", completed: "完成", blocked: "阻塞" };
  let editorProject = "", editorVersion = 0, tasksBusy = false, sourceBefore = null;
  let sourceProject = "", shownSession = "", shownProject = "";

  const memoryUrl = project => `/api/projects/${encodeURIComponent(project)}/memory`;
  function requireProject() {
    if (!currentProjectId) throw new Error("請先選擇一個專案；一般對話沒有 L2 記憶。");
    return currentProjectId;
  }
  byId("memory-edit").onclick = async () => {
    try {
      const project = requireProject(), data = await api(memoryUrl(project));
      if (currentProjectId !== project) return;
      editorProject = project; editorVersion = data.version;
      byId("memory-summary-input").value = data.memory?.summary || "";
      byId("memory-pinned-input").value = data.pinned || "";
      byId("memory-editor").classList.remove("hidden");
    } catch (error) { alert(error.message); }
  };
  byId("memory-cancel").onclick = () => byId("memory-editor").classList.add("hidden");
  byId("memory-save").onclick = async () => {
    try {
      if (editorProject !== requireProject()) throw new Error("專案已切換，請重新開啟記憶編輯。");
      const project = editorProject;
      byId("memory-save").disabled = true;
      await api(memoryUrl(editorProject), "PATCH", { summary: byId("memory-summary-input").value,
        pinned: byId("memory-pinned-input").value, version: editorVersion });
      if (currentProjectId === project && editorProject === project) byId("memory-editor").classList.add("hidden");
      window.refreshRuntimePanel?.(true);
    } catch (error) { alert(error.message); }
    finally { byId("memory-save").disabled = false; }
  };
  byId("memory-clear").onclick = async () => {
    try {
      const project = requireProject();
      if (!confirm("清空目前專案的自動摘要？固定內容與原始對話會保留。")) return;
      const data = await api(memoryUrl(project));
      if (currentProjectId !== project) return;
      await api(memoryUrl(project), "PATCH", { summary: "", pinned: data.pinned || "", version: data.version });
      if (currentProjectId === project) byId("memory-editor").classList.add("hidden");
      window.refreshRuntimePanel?.(true);
    } catch (error) { alert(error.message); }
  };

  async function loadSources(more = false) {
    const project = requireProject();
    if (!more || sourceProject !== project) {
      byId("memory-source-list").replaceChildren(); sourceBefore = null; sourceProject = project;
    }
    const data = await api(memoryUrl(project) + "/sources" + (sourceBefore ? `?before=${sourceBefore}` : ""));
    if (project !== currentProjectId) return;
    byId("memory-source-more")?.remove();
    for (const source of data.sources) {
      const item = document.createElement("details");
      const title = document.createElement("summary");
      title.className = "help-text";
      title.textContent = `#${source.id} · ${source.title} · ${source.role} · ${source.created_at}`;
      const content = document.createElement("pre");
      content.className = "panel-pre";
      content.textContent = source.content;
      const open = document.createElement("button");
      open.className = "text-button";
      open.textContent = "開啟來源對話";
      open.onclick = () => switchSession(source.session_id);
      item.append(title, content, open); byId("memory-source-list").appendChild(item);
    }
    if (!data.sources.length && !more) byId("memory-source-list").textContent = "尚無摘要來源。固定內容由使用者維護。";
    sourceBefore = data.next_before;
    if (sourceBefore) {
      const button = document.createElement("button"); button.id = "memory-source-more";
      button.textContent = "更早的來源"; button.className = "text-button";
      button.onclick = () => loadSources(true).catch(error => alert(error.message));
      byId("memory-source-list").appendChild(button);
    }
  }
  byId("memory-sources").onclick = () => loadSources().catch(error => alert(error.message));

  async function refreshTasks() {
    if (tasksBusy || !currentSessionId || byId("tasks-list").contains(document.activeElement)) return;
    const session = currentSessionId, project = currentProjectId; tasksBusy = true;
    try {
      const data = await api(workspaceUrl("/api/workspace/tasks", session));
      if (session !== currentSessionId || project !== currentProjectId) return;
      const done = data.tasks.filter(task => task.status === "completed").length;
      byId("tasks-count").textContent = `${done} / ${data.tasks.length} 完成`;
      const list = byId("tasks-list"); list.replaceChildren();
      if (!data.tasks.length) list.textContent = "尚無 SDD 任務。建立規格後，這裡會讀取 .specify/tasks.md。";
      for (const task of data.tasks) {
        const row = document.createElement("div"); row.className = "task-row";
        const select = document.createElement("select"); select.setAttribute("aria-label", `任務狀態：${task.title}`);
        for (const [value, label] of Object.entries(statuses)) select.add(new Option(label, value));
        select.value = task.status; select.disabled = isGenerating;
        select.onchange = async () => {
          if (isGenerating || sessionBusy) return;
          select.blur(); select.disabled = true;
          try { await api(workspaceUrl("/api/workspace/tasks", session), "PATCH",
              { task_line: task.line, status: select.value, revision: data.revision }); }
          catch (error) { alert(error.message); }
          refreshTasks();
        };
        const text = document.createElement("span"); text.className = "task-title";
        text.textContent = task.title; row.append(select, text); list.appendChild(row);
      }
    } catch (error) { if (session === currentSessionId && project === currentProjectId) byId("tasks-list").textContent = error.message; }
    finally { tasksBusy = false; }
  }

  window.refreshProjectTools = function (force = false) {
    if (shownSession !== currentSessionId || shownProject !== currentProjectId) {
      shownSession = currentSessionId;
      shownProject = currentProjectId;
      byId("memory-editor").classList.add("hidden"); byId("memory-source-list").replaceChildren();
      sourceProject = "";
    }
    for (const name of ["memory-edit", "memory-clear", "memory-sources"]) byId(name).disabled = !currentProjectId;
    if (force || !byId("panel-plan").hidden) refreshTasks();
  };
  window.clearAttachments = () => {
    pendingAttachments = []; renderAttachments();
    byId("document-results").replaceChildren();
    byId("document-files").value = "";
    byId("memory-editor").classList.add("hidden"); byId("memory-source-list").replaceChildren();
  };
  window.renderAttachments = function () {
    const list = byId("attachment-list");
    list.hidden = pendingAttachments.length === 0; list.replaceChildren();
    const labels = { processing: "上傳中…", ready: "已加入", no_text: "無可讀文字，請移除", failed: "匯入失敗，請移除" };
    for (const file of pendingAttachments) {
      const chip = document.createElement("div"); chip.className = "attachment-chip"; chip.dataset.state = file.state;
      chip.title = file.error || file.warnings?.join(" ") || file.name;
      const text = document.createElement("span"); text.textContent = `${file.name} · ${file.error || labels[file.state]}`;
      const remove = document.createElement("button"); remove.textContent = "×";
      remove.setAttribute("aria-label", `移除附件 ${file.name}`);
      remove.onclick = () => { pendingAttachments = pendingAttachments.filter(item => item !== file); renderAttachments(); };
      if (file.kind === "image" && file.id) {
        const preview = document.createElement("a");
        preview.href = imageUrl(currentSessionId, file.id); preview.target = "_blank"; preview.rel = "noopener";
        const image = document.createElement("img"); image.src = preview.href; image.alt = file.name;
        preview.appendChild(image); chip.appendChild(preview);
      }
      chip.append(text, remove); list.appendChild(chip);
    }
    updateMode();
  };

  async function importFiles(files) {
    if (uploading || sessionBusy || !currentSessionId || !files.length) return;
    const session = currentSessionId, project = currentProjectId;
    uploading = true;
    const queue = files.map(file => ({ file, name: file.name, state: "processing",
      kind: file.type.startsWith("image/") || /\.(png|jpe?g|webp|gif|bmp|svg|avif)$/i.test(file.name) ? "image" : "document" }));
    pendingAttachments.push(...queue); renderAttachments();
    try {
      for (const attachment of queue) {
        if (session !== currentSessionId || project !== currentProjectId) break;
        const { file } = attachment;
        const row = document.createElement("div"); row.textContent = `${file.name}：正在上傳…`;
        byId("document-results").prepend(row);
        try {
          if (attachment.kind === "image") {
            const images = pendingAttachments.filter(item => item.kind === "image" && item.state !== "failed");
            if (images.indexOf(attachment) >= 4) throw new Error("每則訊息最多四張圖片，請移除多餘附件。");
            if (file.size > 10 * 1024 * 1024) throw new Error("單張圖片最多 10 MiB。");
            const response = await fetch(`/api/sessions/${encodeURIComponent(session)}/images`, {
              method: "POST", headers: { "X-File-Name": encodeURIComponent(file.name), "Content-Type": "application/octet-stream" }, body: file
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.detail || "圖片上傳失敗");
            if (session !== currentSessionId || project !== currentProjectId) return;
            Object.assign(attachment, data, { state: "ready" });
            row.textContent = `${data.name}：圖片 ${data.width} × ${data.height}，送出訊息後才交給模型。`;
            const preview = document.createElement("a"); preview.className = "text-button";
            preview.href = imageUrl(session, data.id); preview.target = "_blank"; preview.rel = "noopener"; preview.textContent = "預覽圖片";
            row.appendChild(preview); renderAttachments(); continue;
          }
          if (file.size > 25 * 1024 * 1024) throw new Error("單一文件最多 25 MiB。");
          const response = await fetch(workspaceUrl("/api/workspace/import", session), {
            method: "POST", headers: { "X-File-Name": encodeURIComponent(file.name), "Content-Type": "application/octet-stream" }, body: file
          });
          const data = await response.json();
          if (!response.ok) throw new Error(data.detail || "匯入失敗");
          if (session !== currentSessionId || project !== currentProjectId) return;
          attachment.text_path = data.text_path; attachment.warnings = data.warnings || [];
          attachment.state = data.text_path && data.characters > 0 ? "ready" : "no_text";
          row.textContent = `${data.name}：${data.characters} 字。${attachment.warnings.join(" ")}`;
          const download = document.createElement("a"); download.className = "text-button";
          download.href = workspaceUrl(`/api/workspace/download?path=${encodeURIComponent(data.original_path)}`, session);
          download.textContent = "下載原檔"; download.download = ""; row.appendChild(download);
          if (data.text_path) {
            const preview = document.createElement("button"); preview.className = "text-button";
            preview.textContent = "查看文字"; preview.onclick = () => previewFile(data.text_path);
            row.appendChild(preview);
          }
        } catch (error) {
          attachment.state = "failed"; attachment.error = error.message;
          row.textContent = `${file.name}：${error.message}`;
        }
        renderAttachments();
      }
      loadWorkspaceFiles();
    } finally {
      uploading = false; byId("document-files").value = ""; renderAttachments();
    }
  }
  byId("attach-button").onclick = () => byId("document-files").click();
  byId("document-files").onchange = event => importFiles(Array.from(event.target.files));
  userInput.addEventListener("paste", event => {
    const images = Array.from(event.clipboardData.files).filter(file => file.type.startsWith("image/"));
    if (!images.length || uploading || sessionBusy || !currentSessionId) return;
    event.preventDefault(); importFiles(images);
  });
  const drop = byId("document-drop");
  drop.ondragover = event => {
    if (!Array.from(event.dataTransfer.types).includes("Files")) return;
    event.preventDefault();
    if (!sessionBusy && !uploading) drop.classList.add("is-dragging");
  };
  drop.ondragleave = event => { if (!drop.contains(event.relatedTarget)) drop.classList.remove("is-dragging"); };
  drop.ondrop = event => {
    if (!event.dataTransfer.files.length) return;
    event.preventDefault(); drop.classList.remove("is-dragging"); importFiles(Array.from(event.dataTransfer.files));
  };
})();
