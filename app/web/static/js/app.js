let currentSessionId = "";
let currentProjectId = null;
let allProjects = [];
let allSessions = [];
let sessionBusy = false;
let isGenerating = false;
let hasSdd = false;
let modeDecision = null;
const sessionRuns = new Map();
const sessionDrafts = new Map();
let pendingAttachments = [];
let uploading = false;

// DOM 元素快取
const sessionList = document.getElementById("session-list");
const chatContainer = document.getElementById("chat-container");
const welcomeCard = document.getElementById("welcome-card");
const userInput = document.getElementById("user-input");
const sendBtn = document.getElementById("send-btn");
const chatMode = document.getElementById("chat-mode");
const reasoningLevel = document.getElementById("reasoning-level");
try {
  const saved = localStorage.getItem("agent-reasoning-level");
  if (["low", "medium", "high"].includes(saved)) reasoningLevel.value = saved;
} catch (_) { /* 無法儲存偏好時沿用預設值。 */ }
reasoningLevel.onchange = () => {
  try { localStorage.setItem("agent-reasoning-level", reasoningLevel.value); } catch (_) { /* 本次選擇仍有效。 */ }
};
const pauseBtn = document.getElementById("pause-btn");
const runStatus = document.getElementById("run-status");
const btnNewChat = document.getElementById("btn-new-chat");
const btnNewProject = document.getElementById("btn-new-project");
const projectSelect = document.getElementById("session-project");
const currentChatTitle = document.getElementById("current-chat-title");
const displaySessionId = document.getElementById("display-session-id");
const sidebar = document.getElementById("sidebar");
const toggleSidebar = document.getElementById("toggle-sidebar");

// 工作區相關 DOM
const btnToggleWorkspace = document.getElementById("btn-toggle-workspace");
const workspaceDrawer = document.getElementById("workspace-drawer");
const btnCloseWorkspace = document.getElementById("btn-close-workspace");
const btnRefreshWorkspace = document.getElementById("btn-refresh-workspace");
const btnViewMap = document.getElementById("btn-view-map");
const workspaceFilesContainer = document.getElementById("workspace-files-container");
const workspaceFileBadge = document.getElementById("workspace-file-badge");

// Modal 相關 DOM
const fileModal = document.getElementById("file-modal");
const modalFileTitle = document.getElementById("modal-file-title");
const modalFileLines = document.getElementById("modal-file-lines");
const modalFileContent = document.getElementById("modal-file-content");

const mapModal = document.getElementById("map-modal");
const modalMapContent = document.getElementById("modal-map-content");

function renderRunStatus(run) {
  pauseBtn.classList.toggle("hidden", !run);
  pauseBtn.disabled = !run || run.controlPending || run.state === "pausing";
  pauseBtn.textContent = run?.state === "paused" ? "繼續" : "暫停";
  runStatus.textContent = !run ? "" : run.state === "running"
    ? { preparing: "準備中…", compacting: "整理上下文…", memory: "更新專案記憶…", detecting: "判斷處理模式…", retrying: "模型回應為空，恢復一次…", summarizing: "已達上限，統整結果…" }[run.phase] || "執行中"
    : { pausing: "暫停中…", paused: "已暫停" }[run.state] || "";
  if (run?.contextUsage) document.getElementById("context-usage").textContent = run.contextUsage;
}
function setRunState(state, phase = "", sessionId = currentSessionId) {
  const run = sessionRuns.get(sessionId);
  if (!run) return;
  const changed = run.state !== state;
  run.state = state; run.phase = phase;
  if (sessionId === currentSessionId) renderRunStatus(run);
  if (changed) renderSessionList();
}

function updateMode(reset = false) {
  const run = sessionRuns.get(currentSessionId);
  isGenerating = Boolean(run);
  if (reset || run) modeDecision = run?.decision || null;
  renderRunStatus(run);
  const busy = isGenerating || sessionBusy || uploading;
  chatMode.disabled = sessionBusy;
  reasoningLevel.disabled = sessionBusy;
  sendBtn.disabled = busy || !currentSessionId || pendingAttachments.some(file => file.state !== "ready");
  document.getElementById("attach-button").disabled = sessionBusy || uploading || !currentSessionId;
  userInput.disabled = sessionBusy;
  document.querySelectorAll(".task-row select").forEach(select => { select.disabled = isGenerating || sessionBusy; });
  btnNewChat.disabled = sessionBusy || uploading;
  btnNewProject.disabled = sessionBusy || uploading;
  projectSelect.disabled = busy || !currentSessionId;
  document.getElementById("mode-hint").textContent = chatMode.value === "auto" && modeDecision
    ? `AI 選擇${modeDecision.mode === "plan" ? "先規劃" : "直接處理"}：${modeDecision.reason}`
    : { auto: "AI 自動判斷如何處理；需要規劃時先建立 SDD", plan: "先建立 SDD，完成後按「開始實作」繼續" }[chatMode.value];
  const button = document.getElementById("implement-plan");
  button.classList.toggle("hidden", !hasSdd);
  chatMode.title = document.getElementById("mode-hint").textContent;
  sendBtn.title = isGenerating ? "本對話正在執行，可先撰寫下一則訊息或切換對話" : "送出訊息";
  document.querySelectorAll(".plan-actions button[data-implement]").forEach(button => { button.disabled = busy || !hasSdd; });
  button.disabled = busy;
}

function implementPlan() {
  if (isGenerating || sessionBusy || uploading || !hasSdd) return;
  chatMode.value = "auto";
  updateMode();
  userInput.value = "我已確認規格，請先讀取 .specify/spec.md、.specify/plan.md、.specify/tasks.md，依照規格與 AGENTS.md 實作，完成後更新待辦狀態。";
  sendMessage({ mode: "agent" });
}

function escapeHtml(text) {
  if (text == null) return "";
  const div = document.createElement("div");
  div.textContent = String(text);
  return div.innerHTML;
}

// 所有功能檔載入後再綁定入口並讀取目前對話。
document.addEventListener("DOMContentLoaded", () => {
  toggleSidebar.addEventListener("click", () => {
    if (window.innerWidth <= 760) {
      closeProjectPanel(false);
      document.body.classList.toggle("navigation-open");
    } else document.body.classList.toggle("navigation-collapsed");
    syncNavigation();
  });
  document.getElementById("navigation-backdrop").onclick = () => {
    document.body.classList.remove("navigation-open"); syncNavigation();
  };
  btnToggleWorkspace.onclick = () => workspaceDrawer.hidden ? openProjectPanel() : closeProjectPanel();
  btnCloseWorkspace.onclick = () => closeProjectPanel();
  document.getElementById("panel-backdrop").onclick = () => closeProjectPanel();
  const tabs = Array.from(document.querySelectorAll("[data-panel]"));
  tabs.forEach((tab, index) => {
    tab.onclick = () => selectProjectTab(tab.dataset.panel);
    tab.onkeydown = event => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1
        : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
      selectProjectTab(tabs[next].dataset.panel); tabs[next].focus();
    };
  });
  window.addEventListener("resize", syncNavigation);
  syncNavigation();
  document.addEventListener("keydown", event => {
    const modal = !fileModal.classList.contains("hidden") ? fileModal : !mapModal.classList.contains("hidden") ? mapModal : null;
    if (event.key === "Escape") {
      if (modal === fileModal) closeFileModal();
      else if (modal === mapModal) closeMapModal();
      else if (!workspaceDrawer.hidden) closeProjectPanel();
      else { document.body.classList.remove("navigation-open"); syncNavigation(); toggleSidebar.focus(); }
    }
    const scope = modal || (!workspaceDrawer.hidden && window.innerWidth < 1200 ? workspaceDrawer : null);
    if (event.key !== "Tab" || !scope) return;
    const controls = Array.from(scope.querySelectorAll('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href],[tabindex="0"]')).filter(el => el.getClientRects().length);
    const first = controls[0], last = controls[controls.length - 1];
    if (!first) return;
    if (!scope.contains(document.activeElement) || (!event.shiftKey && document.activeElement === last)) { event.preventDefault(); first.focus(); }
    else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  });

  // 輸入框自適應高度
  userInput.addEventListener("input", function() {
    this.style.height = "auto";
    this.style.height = Math.min(this.scrollHeight, 128) + "px";
  });

  userInput.addEventListener("keydown", function(e) {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      sendMessage();
    }
  });

  sendBtn.addEventListener("click", sendMessage);
  btnNewChat.addEventListener("click", () => startNewChat());
  btnNewProject.addEventListener("click", createProject);
  pauseBtn.addEventListener("click", async () => {
    const session = currentSessionId, run = sessionRuns.get(session);
    if (!run || run.controlPending || run.state === "pausing") return;
    const action = run.state === "paused" ? "resume" : "pause";
    run.controlPending = true; updateMode();
    try {
      const data = await api(`/api/sessions/${encodeURIComponent(session)}/control`, "POST", { action });
      if (sessionRuns.get(session) !== run) return;
      if (!(data.state === "pausing" && run.state === "paused")) setRunState(data.state, run.phase, session);
    } catch (error) { alert(error.message); }
    finally { run.controlPending = false; updateMode(); }
  });
  manageSessions(loadSessions);
});

let panelReturnFocus = null;
function syncNavigation() {
  const mobile = window.innerWidth <= 760;
  const visible = mobile ? document.body.classList.contains("navigation-open") : !document.body.classList.contains("navigation-collapsed");
  toggleSidebar.setAttribute("aria-expanded", String(visible));
  sidebar.inert = !visible;
  if (!workspaceDrawer.hidden && window.innerWidth < 1200) {
    workspaceDrawer.setAttribute("role", "dialog"); workspaceDrawer.setAttribute("aria-modal", "true");
  } else {
    workspaceDrawer.removeAttribute("role"); workspaceDrawer.removeAttribute("aria-modal");
  }
}
function selectProjectTab(name) {
  document.querySelectorAll("[data-panel]").forEach(tab => {
    const selected = tab.dataset.panel === name;
    tab.setAttribute("aria-selected", String(selected)); tab.tabIndex = selected ? 0 : -1;
    document.getElementById(`panel-${tab.dataset.panel}`).hidden = !selected;
  });
  if (name === "files") loadWorkspaceFiles();
  if (name === "logs") { window.refreshLogPanel?.(); return; }
  if (name === "skills") { window.refreshSkillPanel?.(); return; }
  if (name === "mcp") { window.refreshMcpPanel?.(); return; }
  window.refreshRuntimePanel?.(true);
}
function openProjectPanel(name = document.querySelector('[data-panel][aria-selected="true"]').dataset.panel) {
  if (workspaceDrawer.hidden) panelReturnFocus = document.activeElement;
  workspaceDrawer.hidden = false;
  document.getElementById("panel-backdrop").hidden = false;
  document.body.classList.remove("navigation-open");
  btnToggleWorkspace.setAttribute("aria-expanded", "true");
  selectProjectTab(name); syncNavigation();
  document.getElementById(`tab-${name}`).focus();
}
function closeProjectPanel(restoreFocus = true) {
  const wasOpen = !workspaceDrawer.hidden;
  workspaceDrawer.hidden = true;
  document.getElementById("panel-backdrop").hidden = true;
  btnToggleWorkspace.setAttribute("aria-expanded", "false");
  syncNavigation();
  if (wasOpen && restoreFocus) (panelReturnFocus?.isConnected ? panelReturnFocus : btnToggleWorkspace).focus();
}
