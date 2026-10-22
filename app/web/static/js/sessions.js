// ==========================================
// 會話管理邏輯 (Sessions)
// ==========================================

async function manageSessions(action) {
  if (sessionBusy || uploading) return;
  if (currentSessionId) sessionDrafts.set(currentSessionId, { text: userInput.value, attachments: pendingAttachments.slice(), projectId: currentProjectId });
  sessionBusy = true;
  updateMode();
  try { await action(); }
  catch (error) { alert(error.message); }
  finally {
    sessionBusy = false;
    projectSelect.value = currentProjectId || "";
    updateMode();
  }
}

function updateProjectSelector() {
  projectSelect.replaceChildren(new Option("一般對話", ""), ...allProjects.map(p => new Option(p.name, p.id)));
  projectSelect.value = currentProjectId || "";
}

async function loadSessionsSidebarOnly() {
  const [sessionData, projectData] = await Promise.all([api("/api/sessions"), api("/api/projects")]);
  allSessions = sessionData.sessions || [];
  allProjects = projectData.projects || [];
  const current = allSessions.find(s => s.id === currentSessionId);
  if (current) {
    currentProjectId = current.project_id || null;
    updateHeaderTitle(current.title);
  } else if (!allProjects.some(p => p.id === currentProjectId)) {
    currentProjectId = null;
  }
  updateProjectSelector();
  renderSessionList();
}

async function loadSessions() {
  await loadSessionsSidebarOnly();
  const sessions = allSessions.filter(s => (s.project_id || null) === currentProjectId);
  const current = sessions.find(s => s.id === currentSessionId) || sessions[0];
  if (current) await showSession(current);
  else await createChat(currentProjectId);
}

function renderSessionList() {
  sessionList.innerHTML = "";
  for (const project of [...allProjects, { id: null, name: "一般對話" }]) {
    const sessions = allSessions.filter(s => (s.project_id || null) === project.id);
    const selected = currentProjectId === project.id;
    const section = document.createElement("div");
    section.className = "project-group";
    const header = document.createElement("div");
    header.className = "project-heading";
    const title = document.createElement("button");
    title.className = "project-title";
    title.textContent = `${selected ? "▾" : "▸"} ${project.name} (${sessions.length})`;
    title.title = project.name;
    title.setAttribute("aria-expanded", String(selected));
    title.onclick = () => selectProject(project.id);
    header.appendChild(title);
    const actions = [["＋", "在此分類新增對話", () => startNewChat(project.id)]];
    if (project.id) actions.push(["✎", "重新命名專案", () => renameProject(project)], ["×", "刪除專案分類", () => deleteProject(project)]);
    for (const [text, label, action] of actions) {
      const button = document.createElement("button");
      button.className = "project-action";
      button.textContent = text;
      button.title = label;
      button.setAttribute("aria-label", label);
      button.onclick = action;
      header.appendChild(button);
    }
    section.appendChild(header);
    if (selected) {
      for (const sess of sessions) {
        const item = document.createElement("div");
        item.className = "session-item" + (sess.id === currentSessionId ? " is-selected" : "");
        const open = document.createElement("button"); open.className = "session-title";
        const run = sessionRuns.get(sess.id);
        open.textContent = (sess.title || "新對話") + (run ? run.state === "paused" ? " · 已暫停" : " · 執行中" : "");
        open.title = open.textContent;
        if (sess.id === currentSessionId) open.setAttribute("aria-current", "page");
        open.onclick = () => switchSession(sess.id);
        const remove = document.createElement("button"); remove.className = "session-delete";
        remove.textContent = "×"; remove.setAttribute("aria-label", `刪除對話 ${open.textContent}`);
        remove.onclick = () => deleteSession(sess.id);
        item.append(open, remove);
        section.appendChild(item);
      }
    }
    sessionList.appendChild(section);
  }
}

async function showSession(session) {
  if (!session) return;
  currentSessionId = session.id;
  currentProjectId = session.project_id || null;
  window.resetLogPanel?.();
  window.resetMcpPanel?.();
  window.clearAttachments?.();
  const draft = sessionDrafts.get(session.id);
  userInput.value = draft?.text || "";
  userInput.dispatchEvent(new Event("input"));
  pendingAttachments = draft?.projectId === currentProjectId ? draft.attachments.slice() : [];
  window.renderAttachments?.();
  hasSdd = false;
  document.getElementById("runtime-error").textContent = "";
  delete document.getElementById("runtime-error").dataset.memoryError;
  document.getElementById("background-status").classList.add("hidden");
  document.body.classList.remove("navigation-open"); syncNavigation();
  updateMode(true);
  updateHeaderTitle(session.title);
  updateProjectSelector();
  renderSessionList();
  chatContainer.innerHTML = "";
  closeFileModal();
  closeMapModal();
  clearCodeSearch();
  loadWorkspaceFiles();
  const run = sessionRuns.get(session.id);
  if (run) chatContainer.replaceChildren(...run.nodes);
  else {
    const data = await api(`/api/sessions/${encodeURIComponent(session.id)}/messages`);
    if (currentSessionId !== session.id) return;
    if (!data.messages.length) chatContainer.appendChild(welcomeCard);
    else data.messages.forEach(msg => appendMessage(msg.role, msg.content, msg.images || [], session.id));
  }
  chatContainer.scrollTop = chatContainer.scrollHeight;
  window.refreshRuntimePanel?.(true);
}

function switchSession(sessionId) {
  return manageSessions(() => showSession(allSessions.find(s => s.id === sessionId)));
}

function selectProject(projectId) {
  return manageSessions(async () => {
    if (currentProjectId === projectId && currentSessionId) return;
    currentProjectId = projectId;
    currentSessionId = "";
    await loadSessions();
  });
}

async function createChat(projectId) {
  const session = await api("/api/sessions", "POST", {
    session_id: "sess_" + Date.now() + "_" + Math.random().toString(36).substring(2, 7),
    title: "新對話", project_id: projectId
  });
  currentSessionId = session.id;
  currentProjectId = session.project_id || null;
  await loadSessionsSidebarOnly();
  await showSession(session);
  userInput.focus();
}

function startNewChat(projectId = currentProjectId) {
  return manageSessions(() => createChat(projectId));
}

function createProject() {
  return manageSessions(async () => {
    const name = prompt("請輸入專案名稱（最多 80 字）：");
    if (name === null) return;
    const project = await api("/api/projects", "POST", { name });
    await createChat(project.id);
  });
}

function renameProject(project) {
  return manageSessions(async () => {
    const name = prompt("專案名稱：", project.name);
    if (name === null || name === project.name) return;
    await api(`/api/projects/${encodeURIComponent(project.id)}`, "PATCH", { name });
    await loadSessionsSidebarOnly();
  });
}

function deleteProject(project) {
  return manageSessions(async () => {
    if (!confirm(`刪除「${project.name}」的專案分類？對話會移回一般對話，所有訊息與專案檔案都會保留，檔案不會搬到各對話的新工作區。`)) return;
    await api(`/api/projects/${encodeURIComponent(project.id)}`, "DELETE");
    await loadSessionsSidebarOnly();
    window.clearAttachments?.();
    closeFileModal();
    closeMapModal();
    clearCodeSearch();
    await loadWorkspaceFiles();
    window.refreshRuntimePanel?.(true);
  });
}

function moveCurrentSession(projectId) {
  return manageSessions(async () => {
    await api(`/api/sessions/${encodeURIComponent(currentSessionId)}/project`, "PATCH", { project_id: projectId || null });
    await loadSessionsSidebarOnly();
    window.clearAttachments?.();
    closeFileModal();
    closeMapModal();
    clearCodeSearch();
    await loadWorkspaceFiles();
    window.refreshRuntimePanel?.(true);
  });
}

function deleteSession(sessionId) {
  return manageSessions(async () => {
    if (!confirm("確定要刪除這筆對話紀錄嗎？")) return;
    await api(`/api/sessions/${encodeURIComponent(sessionId)}`, "DELETE");
    sessionDrafts.delete(sessionId);
    if (currentSessionId === sessionId) {
      currentSessionId = "";
      await loadSessions();
    } else await loadSessionsSidebarOnly();
  });
}

function updateHeaderTitle(title) {
  currentChatTitle.innerText = title || "新對話";
  displaySessionId.innerText = currentSessionId;
}
