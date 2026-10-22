/* Skill 僅顯示名稱與一行用途，完整說明在各項目下方按需載入。 */
(() => {
  const byId = id => document.getElementById(id);
  let revision = 0;
  async function loadSkill(skill, row, content, request) {
    content.textContent = "讀取中…";
    try {
      const data = await api(`/api/skills/${encodeURIComponent(skill.id)}`);
      if (request !== revision || !row.isConnected) return;
      const text = (data.content || "").replace(/^\uFEFF?---\r?\n[\s\S]*?\r?\n---(?:\r?\n|$)/, "");
      content.replaceChildren(renderMarkdown(data.error || text || "沒有說明內容。"));
      if (data.truncated) content.appendChild(document.createTextNode("（內容過長，僅顯示前段。）"));
      const metadata = document.createElement("details"), title = document.createElement("summary");
      metadata.className = "skill-metadata"; title.textContent = "來源與安裝資訊";
      const location = document.createElement("p"); location.textContent = data.path;
      metadata.append(title, location);
      if (data.installed_at) {
        const installed = document.createElement("p"); installed.textContent = `安裝時間：${new Date(data.installed_at).toLocaleString()}`;
        metadata.appendChild(installed);
      }
      if (/^https?:\/\//i.test(data.source_url)) {
        const source = document.createElement("a"); source.href = data.source_url;
        source.target = "_blank"; source.rel = "noopener noreferrer"; source.textContent = "開啟來源網站";
        metadata.appendChild(source);
      }
      content.appendChild(metadata);
      return true;
    } catch (error) {
      if (request === revision && row.isConnected) content.textContent = `${error.message}（收合後可再次展開重試）`;
      return false;
    }
  }
  window.refreshSkillPanel = async function () {
    const request = ++revision;
    byId("skills-status").textContent = "讀取中…";
    byId("skills-list").replaceChildren();
    try {
      const data = await api("/api/skills");
      if (request !== revision) return;
      byId("skills-status").textContent = `共 ${data.skills.length} 項 · ${data.skills.filter(item => item.active).length} 項可載入`;
      for (const skill of data.skills) {
        const row = document.createElement("details"), summary = document.createElement("summary");
        row.className = "skill-entry";
        const name = document.createElement("strong"), state = document.createElement("span"), description = document.createElement("span");
        name.textContent = skill.name; state.className = "skill-state";
        state.textContent = !skill.valid ? "格式錯誤" : skill.active ? "可載入" : "同名覆蓋";
        if (!skill.valid) state.classList.add("danger");
        description.className = "help-text skill-description";
        description.textContent = skill.description || skill.error; description.title = description.textContent;
        summary.append(name, state, description);
        const content = document.createElement("div"); content.className = "prose skill-content";
        let loaded = false, loading = false;
        row.ontoggle = async () => {
          if (!row.open || loaded || loading) return;
          loading = true; loaded = await loadSkill(skill, row, content, request); loading = false;
        };
        row.append(summary, content); byId("skills-list").appendChild(row);
      }
      if (!data.skills.length) byId("skills-status").textContent = "尚未找到全域 Skill。";
    } catch (error) {
      if (request === revision) byId("skills-status").textContent = error.message;
    }
  };
  byId("skills-refresh").onclick = () => window.refreshSkillPanel();
})();
