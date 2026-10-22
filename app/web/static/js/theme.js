/* 主題偏好只保存在瀏覽器；首次使用跟隨系統。 */
(() => {
  const system = matchMedia("(prefers-color-scheme: dark)");
  let preference = null;
  try { preference = localStorage.getItem("agent-theme"); } catch (_) {}
  if (!["light", "dark"].includes(preference)) preference = null;
  function apply() {
    const theme = preference || (system.matches ? "dark" : "light");
    document.documentElement.dataset.theme = theme;
    const button = document.getElementById("theme-toggle");
    if (button) {
      button.textContent = theme === "dark" ? "淺色" : "暗色";
      button.setAttribute("aria-label", `切換為${theme === "dark" ? "淺色" : "暗色"}模式`);
      button.setAttribute("aria-pressed", String(theme === "dark"));
    }
    document.dispatchEvent(new Event("themechange"));
  }
  window.toggleTheme = () => {
    preference = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    try { localStorage.setItem("agent-theme", preference); } catch (_) {}
    apply();
  };
  system.addEventListener("change", () => { if (!preference) apply(); });
  document.addEventListener("DOMContentLoaded", apply);
  apply();
})();
