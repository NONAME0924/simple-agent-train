/* 大介面：左側功能列切換「聊天／報帳／管理」。各頁的資料與操作仍由原本的 finance.js、account.js 負責。 */
(() => {
  const byId = id => document.getElementById(id);
  const items = Array.from(document.querySelectorAll(".rail-item[data-view]"));
  function setView(view) {
    document.body.dataset.view = view;
    for (const item of items) {
      const active = item.dataset.view === view;
      item.classList.toggle("is-active", active);
      if (active) item.setAttribute("aria-current", "page"); else item.removeAttribute("aria-current");
    }
    byId("finance-modal").classList.toggle("hidden", view !== "finance");
    byId("admin-modal").classList.toggle("hidden", view !== "admin");
    byId("equipment-pane").classList.toggle("hidden", view !== "equipment" && view !== "equipment-admin");
    byId("lunch-pane").classList.toggle("hidden", view !== "lunch");
  }
  window.setAppView = setView;
  byId("rail-chat").addEventListener("click", () => setView("chat"));
  // 報帳頁的載入由 finance.js 綁在同一顆按鈕上；這裡只切換畫面。
  byId("btn-finance").addEventListener("click", () => setView("finance"));
  byId("rail-admin").addEventListener("click", () => { setView("admin"); byId("btn-admin").click(); });
  byId("rail-lunch").addEventListener("click", () => { setView("lunch"); window.loadLunch?.(); });
  byId("rail-equipment").addEventListener("click", () => { setView("equipment"); window.loadEquipment?.("view"); });
  byId("rail-equipment-admin").addEventListener("click", () => { setView("equipment-admin"); window.loadEquipment?.("manage"); });
})();
