/* 實驗室報帳：成員請款（附照片）、會計審核與經費、管理員檢視。 */
(() => {
  const byId = id => document.getElementById(id);
  const money = value => `${value < 0 ? "-" : ""}$${Math.abs(value).toLocaleString("zh-TW")}`;
  const labels = { pending: "待審核", approved: "已通過", rejected: "已退回", withdrawn: "已撤回" };
  const el = (tag, content, className) => { const node = document.createElement(tag); if (content !== undefined) node.textContent = content; if (className) node.className = className; return node; };
  const btn = (label, action, className = "text-button") => { const node = el("button", label, className); node.type = "button"; node.onclick = action; return node; };
  let me = { is_treasurer: false, can_view: false };
  let selectedFiles = [];

  // 這裡自行處理錯誤，才能讀到「超過餘額需確認」的結構化回應。
  async function call(url, method = "GET", body) {
    const response = await fetch(url, { method, ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }) });
    const data = await response.json();
    if (!response.ok) {
      const detail = data.detail;
      const error = new Error(typeof detail === "string" ? detail : detail?.message || "操作失敗，請確認輸入。");
      error.needsConfirm = Boolean(detail?.needs_confirm); throw error;
    }
    return data;
  }
  const status = message => { byId("fin-status").textContent = message || ""; };
  const guard = async work => { try { status(""); await work(); } catch (error) { status(error.message); } };
  const imageUrl = (request, image) => `/api/finance/requests/${request.id}/images/${image.id}`;

  function viewer(url) {
    const box = el("div", undefined, "fin-viewer"); const image = document.createElement("img"); image.src = url; image.alt = "收據照片";
    box.append(image); box.onclick = () => box.remove(); document.body.append(box);
  }
  function photos(request) {
    const row = el("div", undefined, "fin-photos");
    for (const image of request.images) {
      const thumb = document.createElement("img"); thumb.src = imageUrl(request, image); thumb.alt = image.name; thumb.loading = "lazy";
      thumb.onclick = () => viewer(thumb.src); row.append(thumb);
    }
    return row;
  }
  function card(request, actions) {
    const item = el("div", undefined, "fin-item");
    const head = el("header");
    head.append(el("span", money(request.amount), "fin-amount"), el("span", labels[request.status], `fin-tag ${request.status}`),
      ...(request.original_amount ? [el("span", `原申請 ${money(request.original_amount)}`, "help-text")] : []),
      el("span", `${request.requester || ""}・${request.created_at}`, "help-text"));
    item.append(head, el("div", request.description), photos(request));
    if (request.original_amount) item.append(el("div", `會計已調整金額：${request.adjust_note}`, "help-text"));
    if (request.status === "rejected") item.append(el("div", `退回原因：${request.reject_reason}（${request.decided_by_name || ""}）`, "danger"));
    if (request.status === "approved") item.append(el("div", `已通過，${request.decided_by_name || ""}・${request.decided_at}`, "help-text"));
    if (actions?.length) { const row = el("div", undefined, "button-row"); row.append(...actions); item.append(row); }
    return item;
  }

  async function loadMine() {
    const { requests } = await call("/api/finance/requests/mine");
    byId("fin-my-list").replaceChildren(...(requests.length ? requests.map(request => card(request,
      request.status === "pending" ? [btn("撤回", () => guard(async () => {
        if (!confirm("撤回這筆請款？")) return; await call(`/api/finance/requests/${request.id}/withdraw`, "POST"); await loadMine();
      }), "text-button danger")] : [])) : [el("p", "還沒有請款紀錄。", "help-text")]));
  }
  async function loadReview() {
    const filter = byId("fin-filter").value;
    const { requests } = await call(`/api/finance/requests${filter ? `?status=${filter}` : ""}`);
    byId("fin-review-list").replaceChildren(...(requests.length ? requests.map(request => card(request,
      request.status === "pending" && me.is_treasurer ? [
        btn("調整金額", () => guard(async () => {
          const value = prompt(`調整「${request.description}」的金額（目前 ${money(request.amount)}，新台幣整數）：`, request.amount);
          if (value === null) return;
          const note = prompt("調整原因（必填，申請人會看到）："); if (!note || !note.trim()) return;
          await call(`/api/finance/requests/${request.id}/amount`, "POST", { amount: Number(value), note }); await loadReview();
        })),
        btn("通過並扣款", () => guard(async () => {
          try { await call(`/api/finance/requests/${request.id}/approve`, "POST", { force: false }); }
          catch (error) {
            if (!error.needsConfirm || !confirm(`${error.message}\n\n仍要通過嗎？`)) throw error;
            await call(`/api/finance/requests/${request.id}/approve`, "POST", { force: true });
          }
          await loadReview(); await refreshBadge();
        }), "secondary-button"),
        btn("退回", () => guard(async () => {
          const reason = prompt("退回原因（必填，申請人會看到）："); if (!reason || !reason.trim()) return;
          await call(`/api/finance/requests/${request.id}/reject`, "POST", { reason }); await loadReview(); await refreshBadge();
        }), "text-button danger")] : [])) : [el("p", "沒有符合的請款。", "help-text")]));
  }
  async function loadFund() {
    const fund = await call("/api/finance/fund");
    const tile = (label, value, negative) => { const box = el("div", undefined, negative ? "negative" : ""); box.append(el("span", label, "help-text"), el("strong", money(value))); return box; };
    byId("fin-summary").replaceChildren(tile("總金額", fund.total), tile("已核銷", fund.spent), tile("目前剩餘", fund.remaining, fund.remaining < 0));
    byId("fin-adjust").hidden = !me.is_treasurer; byId("fin-readonly").hidden = me.is_treasurer;
    const names = { add: "加錢", subtract: "減錢", expense: "請款核銷" };
    byId("fin-ledger").replaceChildren(...(fund.ledger.length ? fund.ledger.map(row => {
      const line = el("div", undefined, "fin-row");
      line.append(el("span", row.created_at, "help-text"), el("span", `${names[row.kind]}：${row.note}（${row.actor_name}）`),
        el("strong", `${row.amount > 0 ? "+" : "-"}${Math.abs(row.amount).toLocaleString("zh-TW")}`, row.amount > 0 ? "plus" : "minus"));
      return line;
    }) : [el("p", "還沒有任何紀錄。", "help-text")]));
  }
  async function refreshBadge() {
    try {
      me = await call("/api/finance/me");
      const badge = byId("finance-badge"); badge.hidden = !me.pending; badge.textContent = me.pending;
      byId("fin-tab-review").hidden = !me.can_view; byId("fin-tab-fund").hidden = !me.can_view;
    } catch (_) { /* 未登入或暫時連不上時不顯示數字。 */ }
  }
  window.refreshFinanceBadge = refreshBadge;
  setInterval(() => { if (currentUser && me.can_view) refreshBadge(); }, 60000);

  function tab(name) {
    for (const key of ["mine", "review", "fund"]) { byId(`fin-${key}`).hidden = key !== name; byId(`fin-tab-${key}`).classList.toggle("is-active", key === name); }
    guard(async () => { await refreshBadge(); await ({ mine: loadMine, review: loadReview, fund: loadFund })[name](); });
  }
  byId("btn-finance").onclick = () => { byId("finance-modal").classList.remove("hidden"); status(""); tab("mine"); };
  for (const key of ["mine", "review", "fund"]) byId(`fin-tab-${key}`).onclick = () => tab(key);
  byId("fin-filter").onchange = () => guard(loadReview);
  byId("fin-refresh").onclick = () => guard(async () => { await refreshBadge(); await loadReview(); });

  byId("fin-files").onchange = event => {
    selectedFiles = Array.from(event.target.files).slice(0, 4);
    if (event.target.files.length > 4) status("最多 4 張，只會附上前 4 張。");
    byId("fin-previews").replaceChildren(...selectedFiles.map(file => { const image = document.createElement("img"); image.src = URL.createObjectURL(file); image.alt = file.name; return image; }));
  };
  byId("fin-form").onsubmit = event => {
    event.preventDefault();
    guard(async () => {
      if (!selectedFiles.length) throw new Error("請附上至少一張收據照片。");
      const ids = [];
      for (const file of selectedFiles) {
        if (file.size > 10 * 1024 * 1024) throw new Error(`${file.name} 超過 10 MiB。`);
        const response = await fetch("/api/finance/images", { method: "POST", body: file,
          headers: { "X-File-Name": encodeURIComponent(file.name), "Content-Type": "application/octet-stream" } });
        const data = await response.json(); if (!response.ok) throw new Error(`${file.name}：${data.detail}`);
        ids.push(data.id);
      }
      await call("/api/finance/requests", "POST", { amount: Number(byId("fin-amount").value), description: byId("fin-description").value, images: ids });
      byId("fin-form").reset(); selectedFiles = []; byId("fin-previews").replaceChildren();
      status("已送出，會計審核後會在下方看到結果。"); await loadMine(); await refreshBadge();
    });
  };
  byId("fin-adjust").onsubmit = event => {
    event.preventDefault();
    guard(async () => {
      const kind = byId("fin-adjust-kind").value, amount = Number(byId("fin-adjust-amount").value);
      if (!confirm(`${kind === "add" ? "增加" : "減少"}總金額 ${money(amount)}？`)) return;
      await call("/api/finance/fund/adjust", "POST", { kind, amount, note: byId("fin-adjust-note").value });
      byId("fin-adjust").reset(); await loadFund();
    });
  };
})();
