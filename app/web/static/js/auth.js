/* 登入狀態：啟動時確認、401 時回到登入畫面、登入／申請帳號。 */
let currentUser = null;
let afterLogin = null;
let registerMode = false;

const authOverlay = document.getElementById("auth-overlay");
const authForm = document.getElementById("auth-form");

// 任何 /api 回 401（登入過期、被停用、密碼被重設）都回到登入畫面。
const nativeFetch = window.fetch.bind(window);
window.fetch = async (input, init) => {
  const response = await nativeFetch(input, init);
  const url = typeof input === "string" ? input : input.url;
  if (response.status === 401 && url.startsWith("/api/") && !url.startsWith("/api/auth/login")) showLogin("登入已失效，請重新登入。");
  return response;
};

function setAuthMode(register) {
  registerMode = register;
  document.getElementById("auth-title").textContent = register ? "申請帳號" : "登入 Agent 工作台";
  document.getElementById("auth-submit").textContent = register ? "送出申請" : "登入";
  document.getElementById("auth-switch").textContent = register ? "已有帳號？登入" : "申請帳號";
  document.getElementById("auth-password").autocomplete = register ? "new-password" : "current-password";
  document.getElementById("auth-hint").hidden = !register;
}

function showLogin(message = "") {
  currentUser = null;
  document.getElementById("btn-account").hidden = true;
  document.getElementById("btn-finance").hidden = true;
  document.getElementById("rail-admin").hidden = true;
  window.setAppView?.("chat");
  document.getElementById("auth-error").textContent = message;
  document.getElementById("auth-error").style.color = "";
  document.querySelectorAll(".modal-overlay").forEach(modal => modal.classList.add("hidden"));
  authOverlay.classList.remove("hidden");
  document.getElementById("auth-username").focus();
}

function applyUser(user) {
  currentUser = user;
  authOverlay.classList.add("hidden");
  const button = document.getElementById("btn-account");
  button.hidden = false;
  button.textContent = Array.from(user.username).slice(0, 2).join("").toUpperCase();
  button.title = user.username + (user.role === "admin" ? "（管理員）" : "") + (user.is_treasurer ? "（會計）" : "");
  button.setAttribute("aria-label", `帳號：${button.title}`);
  document.getElementById("rail-admin").hidden = user.role !== "admin";
  // 系統日誌只有管理員能看。
  const system = document.querySelector('#logs-scope option[value="system"]');
  if (system) system.hidden = system.disabled = user.role !== "admin";
  document.getElementById("btn-admin").hidden = user.role !== "admin";
  document.getElementById("btn-finance").hidden = false;
  window.refreshFinanceBadge?.();
}

async function startAfterLogin(callback) {
  afterLogin = callback;
  try {
    const response = await nativeFetch("/api/auth/me");
    if (response.ok) { document.body.dataset.booted = "1"; applyUser((await response.json()).user); callback(); return; }
  } catch (_) { /* 伺服器暫時連不上時顯示登入畫面，錯誤訊息會說明。 */ }
  showLogin();
}

document.getElementById("auth-switch").onclick = () => { setAuthMode(!registerMode); document.getElementById("auth-error").textContent = ""; };
authForm.addEventListener("submit", async event => {
  event.preventDefault();
  const error = document.getElementById("auth-error");
  const body = { username: document.getElementById("auth-username").value.trim(), password: document.getElementById("auth-password").value };
  error.style.color = ""; error.textContent = "";
  try {
    const response = await nativeFetch(registerMode ? "/api/auth/register" : "/api/auth/login", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "操作失敗，請確認輸入。");
    document.getElementById("auth-password").value = "";
    if (registerMode) {
      setAuthMode(false); error.style.color = "var(--accent)"; error.textContent = data.message;
      return;
    }
    // 換了人登入時清掉上一位的畫面狀態，直接重新載入最乾淨。
    if (afterLogin && !document.body.dataset.booted) { document.body.dataset.booted = "1"; applyUser(data.user); afterLogin(); }
    else location.reload();
  } catch (failure) { error.textContent = failure.message; }
});
setAuthMode(false);
