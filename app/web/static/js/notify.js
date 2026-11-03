/* 站內通知：功能列鈴鐺、未讀數字、通知清單；點通知跳到對應頁面。 */
(() => {
  const byId = id => document.getElementById(id);
  const panel = byId("notify-panel"), button = byId("btn-notify");
  const el = (tag, content, className) => { const node = document.createElement(tag); if (content !== undefined) node.textContent = content; if (className) node.className = className; return node; };

  function setBadge(count) {
    const badge = byId("notify-badge"); badge.hidden = !count; badge.textContent = count > 99 ? "99+" : count;
    button.setAttribute("aria-label", count ? `通知，${count} 則未讀` : "通知");
  }
  async function refresh() {
    if (!currentUser) return;
    try { setBadge((await api("/api/notifications/unread")).unread); } catch (_) { /* 暫時連不上就下次再試 */ }
  }
  window.refreshNotify = refresh;
  setInterval(refresh, 60000);

  // 連結格式：finance:review[:id]、finance:mine[:id]、admin:users、equipment[:id]
  function go(link) {
    const [area, sub, id] = (link || "").split(":");
    if (area === "finance") { byId("btn-finance").click(); if (sub === "review") byId("fin-tab-review").click(); }
    else if (area === "admin") byId("rail-admin").click();
    else if (area === "equipment") {
      byId(currentUser?.is_equipment_manager ? "rail-equipment-admin" : "rail-equipment").click();
      if (sub) window.openEquipment?.(Number(sub));
    }
  }

  async function load() {
    const list = byId("notify-list");
    try {
      const data = await api("/api/notifications");
      setBadge(data.unread);
      list.replaceChildren(...(data.notifications.length ? data.notifications.map(item => {
        const row = el("button", undefined, `notify-item${item.read_at ? "" : " is-unread"}`); row.type = "button";
        row.append(el("strong", item.title), ...(item.body ? [el("span", item.body, "notify-body")] : []),
          el("span", `${item.sender_name}・${item.created_at.slice(5, 16)}`, "help-text"));
        row.onclick = async () => {
          if (!item.read_at) { try { await api(`/api/notifications/${item.id}/read`, "POST"); } catch (_) { /* 標記失敗不影響跳轉 */ } }
          close(); if (item.link) go(item.link); refresh();
        };
        return row;
      }) : [el("p", "目前沒有通知。", "help-text")]));
    } catch (error) { list.replaceChildren(el("p", error.message, "runtime-error")); }
  }
  function open() { panel.classList.remove("hidden"); button.setAttribute("aria-expanded", "true"); load(); byId("notify-close").focus(); }
  function close() { panel.classList.add("hidden"); button.setAttribute("aria-expanded", "false"); }
  button.onclick = () => panel.classList.contains("hidden") ? open() : close();
  byId("notify-close").onclick = () => { close(); button.focus(); };
  byId("notify-read-all").onclick = async () => { try { await api("/api/notifications/read-all", "POST"); } finally { load(); } };
  document.addEventListener("keydown", event => { if (event.key === "Escape" && !panel.classList.contains("hidden")) { close(); button.focus(); } });
  document.addEventListener("click", event => { if (!panel.classList.contains("hidden") && !panel.contains(event.target) && !button.contains(event.target)) close(); });
})();
