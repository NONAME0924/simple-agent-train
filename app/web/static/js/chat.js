/* 訊息展示與串流事件；附件引用仍使用原有聊天 API。 */
const attachmentMarker = "\n\n附件文字檔：\n";
const toolTitles = {
  google_search: "網路搜尋", save_sdd: "建立規格", update_user_preference: "更新共用偏好", search_workspace_code: "搜尋程式",
  read_skill: "讀取 Skill", install_skill: "全域安裝 Skill", list_installed_skills: "查看 Skill 總表", get_workspace_code_map: "程式地圖", list_workspace_files: "瀏覽檔案",
  read_workspace_file: "讀取檔案", write_workspace_file: "寫入檔案", edit_code_chunk: "修改程式",
  run_python: "執行 Python", run_skill_script: "執行 Skill 腳本",
  search_history_memory: "搜尋記憶", read_web_page: "讀取網頁", finish_task: "整理結果"
};

function imageUrl(session, imageId) {
  return `/api/sessions/${encodeURIComponent(session)}/images/${encodeURIComponent(imageId)}`;
}

function renderImageGallery(parent, images, session) {
  const gallery = document.createElement("div"); gallery.className = "message-images";
  for (const reference of images || []) {
    const file = typeof reference === "string" ? { id: reference, name: "場景圖片" } : reference;
    const link = document.createElement("a"); link.href = imageUrl(session, file.id); link.target = "_blank"; link.rel = "noopener";
    const image = document.createElement("img"); image.src = link.href; image.alt = file.name; image.loading = "lazy";
    link.appendChild(image); gallery.appendChild(link);
  }
  if (gallery.children.length) parent.appendChild(gallery);
}

function appendMessage(role, text = "", images = [], session = currentSessionId) {
  if (welcomeCard.parentNode === chatContainer) welcomeCard.remove();
  const message = document.createElement("div");
  message.className = `message message-${role === "user" ? "user" : "assistant"}`;
  if (role === "user") {
    let visibleText = text, attachments = [];
    const index = text.lastIndexOf(attachmentMarker);
    if (index !== -1) {
      try {
        const refs = JSON.parse(text.slice(index + attachmentMarker.length));
        if (Array.isArray(refs) && refs.every(file => typeof file.name === "string" && typeof file.text_path === "string")) {
          visibleText = text.slice(0, index); attachments = refs;
        }
      } catch (_) { /* 舊訊息或一般文字照原樣顯示。 */ }
    }
    message.innerHTML = `<div class="user-bubble"><p class="user-text">${escapeHtml(visibleText)}</p></div>`;
    for (const file of attachments) {
      const label = document.createElement("span"); label.className = "message-attachment";
      label.textContent = file.name; message.firstChild.appendChild(label);
    }
    if (images.length) {
      const gallery = document.createElement("div"); gallery.className = "message-images";
      for (const reference of images) {
        const file = typeof reference === "string" ? { id: reference, name: "圖片附件" } : reference;
        const link = document.createElement("a"); link.href = imageUrl(session, file.id);
        link.target = "_blank"; link.rel = "noopener";
        const image = document.createElement("img"); image.src = link.href; image.alt = file.name; image.loading = "lazy";
        link.appendChild(image); gallery.appendChild(link);
      }
      message.firstChild.appendChild(gallery);
    }
  } else {
    message.innerHTML = `<details class="activity hidden"><summary>執行過程</summary>
      <div class="activity-body"><div class="tool-container"></div></div></details>
      <p class="tool-notice runtime-error"></p>
      <div class="content-box prose">${text ? marked.parse(text) : '<span class="content-placeholder">準備中…</span>'}</div>
      <div class="plan-actions hidden"></div>`;
    renderImageGallery(message, images, session);
  }
  chatContainer.appendChild(message);
  chatContainer.scrollTop = chatContainer.scrollHeight;
  return message;
}

async function sendMessage(options = {}) {
  let message = userInput.value.trim();
  if (isGenerating || sessionBusy || uploading || !currentSessionId || pendingAttachments.some(file => file.state !== "ready")) return;
  if (!message && !pendingAttachments.length) return;
  const images = pendingAttachments.filter(file => file.kind === "image");
  const documents = pendingAttachments.filter(file => file.kind !== "image");
  if (images.length > 4) return;
  if (!message) message = images.length ? "請分析這些圖片與附件。" : "請閱讀這些附件的文字內容。";
  if (documents.length) message += attachmentMarker + JSON.stringify(documents.map(({ name, text_path }) => ({ name, text_path })));
  const session = currentSessionId, project = currentProjectId;
  const run = { state: "running", phase: "preparing", mode: options.mode || chatMode.value,
    reasoningLevel: reasoningLevel.value, decision: null, nodes: [], controlPending: false };
  sessionRuns.set(session, run); sessionDrafts.delete(session);
  pendingAttachments = []; window.renderAttachments?.();
  updateMode(true); renderSessionList();
  userInput.value = ""; userInput.style.height = "auto";
  appendMessage("user", message, images, session);
  const reply = appendMessage("assistant");
  run.nodes = Array.from(chatContainer.childNodes);
  const visible = () => currentSessionId === session && currentProjectId === project;
  const activity = reply.querySelector(".activity"), tools = reply.querySelector(".tool-container");
  const content = reply.querySelector(".content-box"), notice = reply.querySelector(".tool-notice");
  let rawContent = "", receivedAnswer = false, receivedDone = false, streamError = false, planReady = false;
  let progressNote = null, progressStep = null;
  const thinkingRounds = new Map();

  function updateActivity() {
    const records = Array.from(tools.querySelectorAll(".tool-record"));
    const failed = records.filter(record => record.dataset.state === "failed").length;
    const running = records.filter(record => record.dataset.state === "running").length;
    activity.classList.remove("hidden"); activity.classList.toggle("has-failure", failed > 0);
    activity.firstElementChild.textContent = `執行過程${records.length ? ` · ${records.length} 次工具呼叫` : ""}${running ? " · 執行中" : ""}${failed ? ` · ${failed} 個失敗` : ""}`;
    if (failed && !streamError) notice.textContent = `${failed} 次工具呼叫失敗，可展開執行過程查看完整錯誤。`;
  }
  function handleEvent(event) {
    if (run.phase === "retrying" && ["progress", "content", "thinking", "tool_start"].includes(event.type)) setRunState("running", "", session);
    if (event.type === "run_state") {
      setRunState(event.state, event.phase, session);
      if (!receivedAnswer) {
        const placeholder = content.querySelector(".content-placeholder");
        if (placeholder) placeholder.textContent = event.phase === "summarizing" ? "正在統整結果…" : "處理中…";
      }
    } else if (event.type === "model_retry") {
      setRunState("running", "retrying", session);
    } else if (event.type === "mode_selected") {
      run.decision = event; setRunState("running", "", session);
      if (visible()) updateMode();
      const decision = document.createElement("p"); decision.className = "help-text";
      const level = { low: "低", medium: "中", high: "高" }[event.reasoning_level || run.reasoningLevel];
      decision.textContent = `${event.mode === "plan" ? "規劃" : "直接處理"}：${event.reason} · 思考：${level}`;
      tools.appendChild(decision); updateActivity();
    } else if (event.type === "sdd_ready") {
      planReady = true;
      if (visible()) { hasSdd = true; loadWorkspaceFiles(); }
      const actions = reply.querySelector(".plan-actions"); actions.classList.remove("hidden");
      actions.innerHTML = '<span>規劃已建立</span><button class="text-button">查看規劃</button><button class="secondary-button" data-implement disabled>開始實作</button>';
      actions.querySelector(".text-button").onclick = () => openProjectPanel("plan");
      const implement = actions.querySelector("[data-implement]");
      if (implement) implement.onclick = implementPlan;
    } else if (event.type === "answer") {
      if (receivedAnswer) return;
      receivedAnswer = true;
      rawContent = event.content || ""; content.innerHTML = marked.parse(rawContent);
      reply.querySelector(":scope > .message-images")?.remove();
      renderImageGallery(reply, event.images, session);
    } else if (event.type === "done") {
      receivedDone = true;
      if (!visible()) return;
      const memoryNotice = document.getElementById("runtime-error");
      if (event.memory_update_ok === false) {
        memoryNotice.dataset.memoryError = "專案記憶更新失敗，對話已保存；完整錯誤見 log。";
        memoryNotice.textContent = memoryNotice.dataset.memoryError;
      } else delete memoryNotice.dataset.memoryError;
    } else if (event.type === "context_usage") {
      run.contextUsage = `上下文估算 ≈${event.estimated_tokens.toLocaleString()} / ${event.input_budget.toLocaleString()} tokens · 80% 自動壓縮${event.compacted ? " · 已壓縮" : ""}`;
      if (visible()) document.getElementById("context-usage").textContent = run.contextUsage;
    } else if (event.type === "thinking") {
      const key = event.finalizing ? "summary" : event.step;
      if (!thinkingRounds.has(key)) {
        const record = document.createElement("details"), title = document.createElement("summary");
        title.textContent = event.finalizing ? "結案統整思考" : event.step ? `第 ${event.step} 輪思考` : "思考紀錄（輪次未知）";
        const text = document.createElement("pre"); text.className = "thinking-content";
        record.className = "thinking-box"; record.append(title, text); tools.appendChild(record);
        thinkingRounds.set(key, text);
      }
      thinkingRounds.get(key).append(document.createTextNode(event.delta || "")); updateActivity();
    } else if (event.type === "tool_start") {
      const record = document.createElement("details"); record.className = "tool-record";
      record.dataset.callId = event.call_id; record.dataset.state = "running";
      const summary = document.createElement("summary"), result = document.createElement("pre");
      record.dataset.title = `第 ${event.step || 1} 輪 · ${toolTitles[event.tool] || event.tool}`;
      summary.textContent = record.dataset.title + " · 執行中";
      result.className = "tool-result"; result.textContent = `參數：\n${JSON.stringify(event.args || {}, null, 2)}`;
      record.append(summary, result); tools.appendChild(record); updateActivity();
    } else if (event.type === "tool_done") {
      const record = Array.from(tools.children).find(item => item.dataset.callId === event.call_id);
      if (record) {
        record.dataset.state = event.ok === false ? "failed" : "completed";
        record.firstElementChild.textContent = record.dataset.title + (event.ok === false ? " · 失敗" : " · 已完成");
        record.querySelector("pre").textContent += `\n\n結果：\n${event.result_full || "無文字輸出"}`;
        renderImageGallery(record, event.images, session);
      }
      updateActivity();
      if (visible() && ["run_python", "run_skill_script", "get_job", "stop_job"].includes(event.tool)) window.refreshRuntimePanel?.(false);
      if (visible() && ["save_sdd", "update_task_status"].includes(event.tool)) window.refreshProjectTools?.(true);
      if (event.tool === "install_skill" && event.ok && !document.getElementById("panel-skills").hidden) window.refreshSkillPanel?.();
    } else if (event.type === "progress" || event.type === "content") {
      if (!progressNote || progressStep !== event.step) {
        progressStep = event.step;
        const record = document.createElement("details"), title = document.createElement("summary");
        title.textContent = event.finalizing ? "結案統整說明" : event.step ? `第 ${event.step} 輪說明` : "執行說明";
        progressNote = document.createElement("pre"); progressNote.className = "tool-result";
        record.append(title, progressNote); tools.appendChild(record);
      }
      progressNote.append(document.createTextNode(event.delta || "")); updateActivity();
    } else if (event.type === "error") {
      streamError = true;
      notice.textContent = receivedAnswer ? "" : `執行失敗：${event.message || "請查看 Log 的 run.failed。"}`;
      content.querySelector(".content-placeholder")?.remove();
    }
  }
  try {
    const response = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, session_id: session, mode: run.mode,
        reasoning_level: run.reasoningLevel, images: images.map(file => file.id) }) });
    if (!response.ok) {
      const data = await response.json(); throw new Error(data.detail || `伺服器錯誤 (${response.status})`);
    }
    const reader = response.body.getReader(), decoder = new TextDecoder();
    let buffer = "";
    function consume(frame) {
      const value = frame.trim();
      if (!value.startsWith("data:")) return;
      const data = value.slice(5).trim();
      if (data === "[DONE]") return;
      handleEvent(JSON.parse(data));
    }
    while (true) {
      const chunk = await reader.read();
      buffer += decoder.decode(chunk.value || new Uint8Array(), { stream: !chunk.done });
      const frames = buffer.split(/\r?\n\r?\n/); buffer = frames.pop();
      for (const frame of frames) consume(frame);
      const nearBottom = chatContainer.scrollHeight - chatContainer.scrollTop - chatContainer.clientHeight < 180;
      if (visible() && nearBottom) chatContainer.scrollTop = chatContainer.scrollHeight;
      if (chunk.done) { if (buffer.trim()) consume(buffer); break; }
    }
    if (!receivedDone && !streamError) notice.textContent = "連線已結束，未收到完成確認。請查看執行紀錄與背景工作。";
  } catch (error) {
    streamError = true;
    notice.textContent = `無法完成回覆：${error.message}`;
  } finally {
    for (const record of tools.querySelectorAll('[data-state="running"]')) {
      record.dataset.state = "interrupted"; record.firstElementChild.textContent = record.dataset.title + " · 未收到完成結果";
    }
    if (!activity.classList.contains("hidden")) updateActivity();
    content.querySelector(".content-placeholder")?.remove();
    if (!rawContent) content.textContent = receivedDone && !streamError
      ? (planReady ? "規劃已保存，可查看後開始實作。" : "本次處理已結束，可展開執行過程查看結果。") : "";
    sessionRuns.delete(session); updateMode(); renderSessionList();
    if (visible()) { window.refreshRuntimePanel?.(true); loadWorkspaceFiles(); }
    loadSessionsSidebarOnly().catch(error => {
      if (visible()) document.getElementById("runtime-error").textContent = error.message;
    });
  }
}
