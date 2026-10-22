btnRefreshWorkspace.addEventListener("click", loadWorkspaceFiles);

btnViewMap.addEventListener("click", async () => {
  const scope = currentSessionId, project = currentProjectId;
  try {
    // 預載入樹狀清單
    const mapData = await api(workspaceUrl("/api/workspace/map", scope));
    if (scope !== currentSessionId || project !== currentProjectId) return;
    modalMapContent.innerText = mapData.map || "工作區尚無檔案。";

    // 預設顯示樹狀清單模式
    switchMapTab("list");
    mapModal.classList.remove("hidden");
    document.getElementById("map-tab-list").focus();
  } catch (err) {
    alert("載入代碼地圖失敗: " + err.message);
  }
});

const graphViewer = (() => {
  const viewport = document.getElementById("graph-viewport");
  const container = document.getElementById("mermaid-graph-container");
  const zoomLabel = document.getElementById("graph-zoom-label");
  let svg = null, width = 0, height = 0, scale = 1, drag = null;

  function setScale(value, anchor = null) {
    if (!svg) return;
    const next = Math.max(0.05, Math.min(4, value));
    const ratio = next / scale;
    const left = anchor ? (viewport.scrollLeft + anchor.x - 32) * ratio + 32 - anchor.x : 0;
    const top = anchor ? (viewport.scrollTop + anchor.y - 32) * ratio + 32 - anchor.y : 0;
    svg.style.width = `${width * next}px`;
    svg.style.height = `${height * next}px`;
    scale = next;
    viewport.scrollLeft = left;
    viewport.scrollTop = top;
    zoomLabel.textContent = `${Math.round(scale * 100)}%`;
  }

  function zoom(factor, anchor = { x: viewport.clientWidth / 2, y: viewport.clientHeight / 2 }) {
    setScale(scale * factor, anchor);
  }

  viewport.addEventListener("wheel", event => {
    if (!event.ctrlKey && !event.metaKey) return;
    event.preventDefault();
    const rect = viewport.getBoundingClientRect();
    zoom(event.deltaY < 0 ? 1.1 : 1 / 1.1, { x: event.clientX - rect.left, y: event.clientY - rect.top });
  }, { passive: false });

  viewport.addEventListener("pointerdown", event => {
    if (event.button !== 0 || !event.isPrimary || event.target.closest("a, [data-code-target]")) return;
    drag = { x: event.clientX, y: event.clientY, left: viewport.scrollLeft, top: viewport.scrollTop };
    viewport.setPointerCapture(event.pointerId);
    viewport.classList.add("is-dragging");
    event.preventDefault();
  });
  viewport.addEventListener("pointermove", event => {
    if (!drag) return;
    viewport.scrollLeft = drag.left - event.clientX + drag.x;
    viewport.scrollTop = drag.top - event.clientY + drag.y;
  });
  function endDrag(event) {
    drag = null;
    viewport.classList.remove("is-dragging");
    if (viewport.hasPointerCapture(event.pointerId)) viewport.releasePointerCapture(event.pointerId);
  }
  viewport.addEventListener("pointerup", endDrag);
  viewport.addEventListener("pointercancel", endDrag);
  viewport.addEventListener("lostpointercapture", () => {
    drag = null;
    viewport.classList.remove("is-dragging");
  });

  return {
    zoom,
    find(query) {
      if (!svg) return;
      const text = query.trim().toLowerCase();
      let first = null;
      svg.querySelectorAll("g.node").forEach(node => {
        const match = Boolean(text && node.textContent.toLowerCase().includes(text));
        node.classList.toggle("graph-hit", match);
        node.style.opacity = text && !match ? "0.3" : "1";
        if (match && !first) first = node;
      });
      if (first) {
        const rect = first.getBoundingClientRect(), view = viewport.getBoundingClientRect();
        viewport.scrollLeft += rect.left - view.left - viewport.clientWidth / 2 + rect.width / 2;
        viewport.scrollTop += rect.top - view.top - viewport.clientHeight / 2 + rect.height / 2;
      }
    },
    reset: () => setScale(1),
    fit: () => setScale(Math.min((viewport.clientWidth - 64) / width, (viewport.clientHeight - 64) / height, 1)),
    async render(code, targets = {}) {
      svg = null;
      zoomLabel.textContent = "100%";
      const graph = document.createElement("div");
      graph.className = "mermaid";
      graph.textContent = code;
      container.replaceChildren(graph);
      mermaid.initialize({
        startOnLoad: false,
        theme: document.documentElement.dataset.theme === "dark" ? "dark" : "default",
        themeVariables: { fontSize: "18px" },
        flowchart: { useMaxWidth: false, nodeSpacing: 40, rankSpacing: 60 }
      });
      await mermaid.run({ nodes: [graph] });
      svg = graph.querySelector("svg");
      if (!svg) throw new Error("未產生圖表");
      width = svg.viewBox.baseVal.width;
      height = svg.viewBox.baseVal.height;
      setScale(1);
      svg.querySelectorAll("g.node").forEach(node => {
        const id = node.getAttribute("data-id") || node.id.replace(/^flowchart-/, "").replace(/-\d+$/, "");
        const target = targets[id];
        if (!target) return;
        node.dataset.codeTarget = id;
        node.style.cursor = "pointer";
        node.setAttribute("tabindex", "0");
        node.setAttribute("role", "button");
        node.setAttribute("aria-label", `開啟 ${target.path} 第 ${target.line} 行`);
        node.addEventListener("click", () => previewFile(target.path, target.line));
        node.addEventListener("keydown", event => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            previewFile(target.path, target.line);
          }
        });
      });
      document.getElementById("graph-search").value = "";
    }
  };
})();

async function toggleMapFullscreen() {
  try {
    const panel = document.getElementById("map-panel");
    if (document.fullscreenElement === panel) await document.exitFullscreen();
    else await panel.requestFullscreen();
  } catch (error) {
    alert("無法切換全螢幕：" + error.message);
  }
}
document.addEventListener("fullscreenchange", () => {
  document.getElementById("graph-fullscreen").textContent = document.fullscreenElement ? "離開全螢幕" : "全螢幕";
});

async function switchMapTab(mode) {
  const scope = currentSessionId, project = currentProjectId;
  const tabList = document.getElementById("map-tab-list");
  const tabGraph = document.getElementById("map-tab-graph");
  const viewList = document.getElementById("map-view-list");
  const viewGraph = document.getElementById("map-view-graph");

  if (mode === "list") {
    tabList.className = "map-tab is-active";
    tabGraph.className = "map-tab";
    viewList.classList.remove("hidden");
    viewGraph.classList.add("hidden");
  } else {
    tabList.className = "map-tab";
    tabGraph.className = "map-tab is-active";
    viewList.classList.add("hidden");
    viewGraph.classList.remove("hidden");

    // 每次切換到有向圖模式都重新渲染（確保最新狀態）
    try {
      const graphData = await api(workspaceUrl("/api/workspace/graph", scope));
      if (scope !== currentSessionId || project !== currentProjectId || viewGraph.classList.contains("hidden") || mapModal.classList.contains("hidden")) return;
      const mermaidCode = graphData.mermaid || "graph TD\n  Empty[\"工作區為空\"]";

      await graphViewer.render(mermaidCode, graphData.nodes || {});
    } catch (err) {
      const container = document.getElementById("mermaid-graph-container");
      container.innerHTML = `<span class="runtime-error">有向圖載入失敗: ${escapeHtml(err.message)}</span>`;
    }
  }
}

function closeFileModal() { fileModal.classList.add("hidden"); }
function closeMapModal() {
  if (document.fullscreenElement === document.getElementById("map-panel")) {
    document.exitFullscreen().catch(() => {});
  }
  mapModal.classList.add("hidden");
}

// ==========================================
// 工作區檔案管理與圖示化渲染
// ==========================================

async function loadWorkspaceFiles() {
  if (!currentSessionId) return;
  const scope = currentSessionId, project = currentProjectId;
  try {
    const data = await api(workspaceUrl("/api/workspace/files"));
    if (scope !== currentSessionId || project !== currentProjectId) return;
    document.getElementById("workspace-path").textContent = data.workspace_dir;
    const files = data.files || [];
    const paths = new Set(files.map(file => file.path.replaceAll("\\", "/")));
    hasSdd = ["spec.md", "plan.md", "tasks.md"].every(name => paths.has(`.specify/${name}`));
    updateMode();

    workspaceFileBadge.innerText = files.length;
    renderWorkspaceFiles(files);
  } catch (err) {
    if (scope === currentSessionId && project === currentProjectId) workspaceFilesContainer.textContent = "檔案載入失敗：" + err.message;
  }
}

function workspaceUrl(path, sessionId = currentSessionId) {
  const url = new URL(path, location.origin);
  url.searchParams.set("session_id", sessionId);
  return url.pathname + url.search;
}

function renderWorkspaceFiles(files) {
  workspaceFilesContainer.replaceChildren();
  if (!files.length) { workspaceFilesContainer.textContent = "工作區尚無檔案。"; return; }
  for (const file of files) {
    const row = document.createElement("div"); row.className = "file-entry";
    row.innerHTML = `<div class="file-entry-header"><div class="file-name">${escapeHtml(file.path)}
      <small>${file.size} bytes · ${escapeHtml(file.updated_at)}</small></div><button class="text-button">檢視文字</button></div>`;
    row.querySelector("button").onclick = () => previewFile(file.path);
    if (file.ast?.items?.length) {
      const structure = document.createElement("details"); structure.className = "file-structure";
      const title = document.createElement("summary"); title.textContent = "程式結構"; structure.appendChild(title);
      for (const item of file.ast.items) {
        const button = document.createElement("button"); button.className = "search-result";
        button.textContent = `${item.signature || item.name} · L${item.start_line}`;
        button.onclick = () => previewFile(file.path, item.start_line); structure.appendChild(button);
        for (const method of item.methods || []) {
          const button = document.createElement("button"); button.className = "search-result";
          button.textContent = `  ${method.signature || method.name} · L${method.start_line}`;
          button.onclick = () => previewFile(file.path, method.start_line); structure.appendChild(button);
        }
      }
      row.appendChild(structure);
    }
    workspaceFilesContainer.appendChild(row);
  }
}

function toggleFilePreview() {
  const markdown = document.getElementById("file-markdown-view");
  setFilePreview(markdown.hidden);
}
function setFilePreview(rendered) {
  document.getElementById("file-source-view").hidden = rendered;
  document.getElementById("file-markdown-view").hidden = !rendered;
  const toggle = document.getElementById("file-preview-toggle");
  toggle.textContent = rendered ? "原始碼" : "閱讀模式";
  toggle.setAttribute("aria-pressed", String(rendered));
}
// 文件可含外部文字；預覽僅保留 Markdown 排版標籤與安全連結。
function renderMarkdown(text) {
  const template = document.createElement("template");
  template.innerHTML = marked.parse(text);
  const allowed = new Set("p h1 h2 h3 h4 h5 h6 ul ol li blockquote pre code table thead tbody tfoot tr th td em strong del hr br a input".split(" "));
  for (const element of Array.from(template.content.querySelectorAll("*"))) {
    if (!allowed.has(element.localName)) { element.replaceWith(document.createTextNode(element.textContent)); continue; }
    const href = element.getAttribute("href"), checked = element.hasAttribute("checked");
    for (const attribute of Array.from(element.attributes)) element.removeAttribute(attribute.name);
    if (element.localName === "a" && href) {
      try {
        const url = new URL(href, location.href);
        if (["http:", "https:", "mailto:"].includes(url.protocol)) {
          element.href = url.href; element.target = "_blank"; element.rel = "noopener noreferrer";
        }
      } catch (_) {}
    }
    if (element.localName === "input") { element.type = "checkbox"; element.disabled = true; element.checked = checked; }
  }
  return template.content;
}

async function previewFile(filePath, line = null) {
  const scope = currentSessionId, project = currentProjectId;
  try {
    const data = await api(workspaceUrl(`/api/workspace/file?path=${encodeURIComponent(filePath)}`, scope));
    if (scope !== currentSessionId || project !== currentProjectId) return;
    if (document.fullscreenElement === document.getElementById("map-panel")) await document.exitFullscreen();
    modalFileTitle.innerText = data.path;
    modalFileLines.innerText = `${data.lines} 行`;
    modalFileContent.innerHTML = data.content.split("\n").map((text, index) =>
      `<span class="code-line ${index + 1 === line ? "selected" : ""}" data-line="${index + 1}"><span class="code-line-number">${String(index + 1).padStart(4)}  </span>${escapeHtml(text)}</span>`
    ).join("");
    const markdown = /\.(md|markdown)$/i.test(data.path);
    const toggle = document.getElementById("file-preview-toggle");
    toggle.hidden = !markdown;
    const rendered = document.getElementById("file-markdown-view");
    rendered.replaceChildren(markdown ? renderMarkdown(data.content) : document.createTextNode(""));
    rendered.scrollTop = 0;
    document.getElementById("file-source-view").scrollTop = 0;
    setFilePreview(markdown && line === null);
    fileModal.classList.remove("hidden");
    fileModal.querySelector("button:not([hidden])").focus();
    modalFileContent.querySelector(`[data-line="${Number(line)}"]`)?.scrollIntoView({ block: "center" });
  } catch (err) {
    alert("讀取檔案失敗: " + err.message);
  }
}

document.getElementById("code-search-form").addEventListener("submit", async event => {
  event.preventDefault();
  const query = document.getElementById("code-search-query").value.trim();
  if (!query) { clearCodeSearch(); return; }
  const scope = currentSessionId, project = currentProjectId;
  const results = document.getElementById("code-search-results");
  results.classList.remove("hidden");
  results.textContent = "搜尋中…";
  try {
    const params = new URLSearchParams({ q: query, pattern: document.getElementById("code-search-pattern").value.trim() || "*" });
    const data = await api(workspaceUrl(`/api/workspace/search?${params}`, scope));
    if (scope !== currentSessionId || project !== currentProjectId) return;
    results.replaceChildren();
    for (const match of data.matches) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "search-result";
      button.textContent = `${match.path}:${match.line}\n${match.content}`;
      button.style.whiteSpace = "pre-wrap";
      button.onclick = () => previewFile(match.path, match.line);
      results.appendChild(button);
    }
    if (!data.matches.length) results.textContent = "找不到符合的內容。";
    if (data.truncated) results.append("已達結果上限，請縮小搜尋範圍。");
  } catch (error) { if (scope === currentSessionId && project === currentProjectId) results.textContent = error.message; }
});

function clearCodeSearch() {
  document.getElementById("code-search-query").value = "";
  document.getElementById("code-search-results").classList.add("hidden");
}

document.addEventListener("themechange", () => {
  if (!mapModal.classList.contains("hidden") && !document.getElementById("map-view-graph").classList.contains("hidden")) switchMapTab("graph");
});
