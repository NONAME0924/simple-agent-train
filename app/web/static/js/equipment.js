/* 實驗室設備：清單、搜尋、詳細資料與異動紀錄；設備管理可新增、修改、送修、報廢。 */
(() => {
  const byId = id => document.getElementById(id);
  const STATUS = { normal: ["正常", "green"], repair: ["維修中", "warn"], retired: ["報廢", "gray"] };
  const LABELS = { name: "名稱", model: "型號", asset_no: "財產編號", serial_no: "序號", location: "存放位置", custodian: "保管人",
    purchased_on: "購入日期", price: "金額", note: "備註", status: "狀態" };
  const el = (tag, content, className) => { const node = document.createElement(tag); if (content !== undefined) node.textContent = content; if (className) node.className = className; return node; };
  const chip = status => el("span", STATUS[status][0], `chip chip-${STATUS[status][1]}`);
  let filter = "", canManage = false, current = null, timer = null;
  const form = byId("eq-form"), formStatus = byId("eq-form-status");

  async function load() {
    const status = byId("eq-status");
    try {
      const query = new URLSearchParams();
      if (filter) query.set("status", filter);
      if (byId("eq-search").value.trim()) query.set("q", byId("eq-search").value.trim());
      if (byId("eq-location").value) query.set("location", byId("eq-location").value);
      const data = await api(`/api/equipment?${query}`);
      canManage = data.can_manage; byId("eq-add").hidden = !canManage;
      const select = byId("eq-location"), keep = select.value;
      select.replaceChildren(el("option", "所有位置"), ...data.locations.map(name => Object.assign(el("option", name), { value: name })));
      select.firstChild.value = ""; select.value = data.locations.includes(keep) ? keep : "";
      byId("eq-location-list").replaceChildren(...data.locations.map(name => Object.assign(document.createElement("option"), { value: name })));
      status.textContent = `共 ${data.equipment.length} 台。`;
      if (!data.equipment.length) { byId("eq-list").replaceChildren(el("p", canManage ? "還沒有設備，按右上角「新增設備」開始登記。" : "還沒有登記任何設備。", "help-text eq-empty")); return; }
      const table = el("table", undefined, "admin-table eq-table"), head = el("tr");
      for (const label of ["名稱", "財產編號", "存放位置", "保管人", "狀態", "購入日期"]) head.append(el("th", label));
      const thead = el("thead"); thead.append(head); const tbody = el("tbody");
      for (const item of data.equipment) {
        const tr = el("tr"); tr.tabIndex = 0; tr.className = "eq-row";
        const name = el("td"); name.append(el("strong", item.name), ...(item.model ? [el("span", item.model, "help-text eq-sub")] : []));
        const state = el("td"); state.append(chip(item.status));
        tr.append(name, el("td", item.asset_no || "—"), el("td", item.location || "—"), el("td", item.custodian || "—"), state, el("td", item.purchased_on || "—"));
        tr.onclick = () => openItem(item.id);
        tr.onkeydown = event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openItem(item.id); } };
        tbody.append(tr);
      }
      table.append(thead, tbody); byId("eq-list").replaceChildren(table);
    } catch (error) { status.textContent = error.message; }
  }
  window.loadEquipment = load;
  window.refreshEquipmentRole = () => { if (document.body.dataset.view === "equipment") load(); };

  function describe(change) {
    return Object.entries(change.changes).map(([key, [before, after]]) => {
      const show = value => key === "status" ? STATUS[value]?.[0] || value : (value === null || value === "" ? "（空）" : value);
      return change.kind === "created" ? `${LABELS[key] || key}：${show(after)}` : `${LABELS[key] || key}：${show(before)} → ${show(after)}`;
    }).join("；");
  }
  async function openItem(id) {
    formStatus.textContent = "";
    current = id ? await api(`/api/equipment/${id}`).catch(error => { byId("eq-status").textContent = error.message; return undefined; }) : null;
    if (current === undefined) return;
    form.reset();
    for (const input of form.querySelectorAll("input,textarea")) {
      if (input.name && current && input.name in current) input.value = current[input.name] ?? "";
      input.disabled = !canManage;
    }
    byId("eq-modal-title").textContent = current ? current.name : "新增設備";
    byId("eq-modal-state").replaceChildren(...(current ? [chip(current.status)] : []));
    byId("eq-reason-row").hidden = !canManage || !current;
    byId("eq-actions").hidden = !canManage;
    for (const button of form.querySelectorAll("[data-eq-status]")) button.hidden = !current || button.dataset.eqStatus === current.status;
    byId("eq-history-title").hidden = !current;
    byId("eq-history").replaceChildren(...(current ? current.events.map(change => {
      const row = el("div", undefined, "eq-event");
      const kind = { created: "登記", updated: "修改", status: "狀態變更" }[change.kind] || change.kind;
      row.append(el("span", `${change.created_at}・${change.actor_name}・${kind}`, "help-text"), el("span", describe(change)),
        ...(change.note ? [el("span", `原因：${change.note}`, "help-text")] : []));
      return row;
    }) : []));
    byId("eq-modal").classList.remove("hidden");
    form.querySelector("[name=name]").focus();
  }
  window.openEquipment = openItem;

  form.onsubmit = async event => {
    event.preventDefault(); formStatus.textContent = "";
    const body = {};
    for (const input of form.querySelectorAll("input[name],textarea[name]")) {
      if (input.name === "reason") continue;
      const value = input.name === "price" ? (input.value === "" ? null : Number(input.value)) : input.value;
      if (!current || (current[input.name] ?? (input.name === "price" ? null : "")) !== value) body[input.name] = value;
    }
    try {
      if (current) {
        if (!Object.keys(body).length) { formStatus.textContent = "沒有任何變更。"; return; }
        current = await api(`/api/equipment/${current.id}`, "POST", { ...body, reason: form.querySelector("[name=reason]").value });
      } else current = await api("/api/equipment", "POST", body);
      byId("eq-modal").classList.add("hidden"); await load();
    } catch (error) { formStatus.textContent = error.message; }
  };
  for (const button of form.querySelectorAll("[data-eq-status]")) button.onclick = async () => {
    const status = button.dataset.eqStatus, label = button.textContent;
    const reason = prompt(`${label}「${current.name}」：請填原因${status === "normal" ? "（選填）" : "（必填）"}`);
    if (reason === null) return;
    try { await api(`/api/equipment/${current.id}/status`, "POST", { status, reason }); await openItem(current.id); await load(); }
    catch (error) { formStatus.textContent = error.message; }
  };
  byId("eq-add").onclick = () => openItem(null);
  for (const button of document.querySelectorAll("#eq-filters [data-status]")) button.onclick = () => {
    filter = button.dataset.status;
    document.querySelectorAll("#eq-filters [data-status]").forEach(other => other.classList.toggle("is-active", other === button));
    load();
  };
  byId("eq-search").oninput = () => { clearTimeout(timer); timer = setTimeout(load, 250); };
  byId("eq-location").onchange = load;
  for (const button of document.querySelectorAll("[data-eq-export]")) button.onclick = async () => {
    try {
      const response = await fetch(`/api/equipment/export?format=${button.dataset.eqExport}`);
      if (!response.ok) throw new Error("匯出失敗。");
      const url = URL.createObjectURL(await response.blob());
      const name = /filename="([^"]+)"/.exec(response.headers.get("Content-Disposition") || "")?.[1] || "equipment";
      const link = Object.assign(document.createElement("a"), { href: url, download: name });
      document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch (error) { byId("eq-status").textContent = error.message; }
  };
})();
