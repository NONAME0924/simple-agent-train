/* 午餐輪盤：下拉選類型與價位，符合的店自動放進輪盤；餐廳清單大家一起填。 */
(() => {
  const byId = id => document.getElementById(id);
  const el = (tag, content, className) => { const node = document.createElement(tag); if (content !== undefined) node.textContent = content; if (className) node.className = className; return node; };
  const NS = "http://www.w3.org/2000/svg";
  const svg = (tag, attrs) => { const node = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v); return node; };
  const COLORS = ["#f2c14e", "#f78154", "#4d9078", "#5fa8d3", "#b56576", "#9a8c98", "#e9c46a", "#84a59d", "#f4a261", "#6d97c4"];
  const R = 160;
  let candidates = [], rotation = 0, spinning = false, editing = null;

  function fillSelect(select, values, allLabel) {
    const keep = select.value;
    select.replaceChildren(Object.assign(el("option", allLabel), { value: "" }), ...values.map(v => Object.assign(el("option", v), { value: v })));
    select.value = values.includes(keep) ? keep : "";
  }

  function drawWheel() {
    const wheel = byId("lunch-wheel"), n = candidates.length;
    wheel.replaceChildren();
    wheel.style.transition = "none"; wheel.style.transform = `rotate(${rotation}deg)`;
    if (!n) {
      wheel.append(svg("circle", { r: R, class: "lunch-empty" }));
      const t = svg("text", { "text-anchor": "middle", "dominant-baseline": "middle", class: "lunch-empty-text" }); t.textContent = "沒有符合的店"; wheel.append(t);
      return;
    }
    const step = 360 / n, rad = d => (d - 90) * Math.PI / 180;
    candidates.forEach((shop, i) => {
      const a1 = i * step, a2 = a1 + step, color = COLORS[(n > COLORS.length && i === n - 1 && i % COLORS.length === 0) ? 1 : i % COLORS.length];
      if (n === 1) wheel.append(svg("circle", { r: R, fill: color }));
      else {
        const p1 = [R * Math.cos(rad(a1)), R * Math.sin(rad(a1))], p2 = [R * Math.cos(rad(a2)), R * Math.sin(rad(a2))];
        wheel.append(svg("path", { d: `M0 0L${p1[0]} ${p1[1]}A${R} ${R} 0 ${step > 180 ? 1 : 0} 1 ${p2[0]} ${p2[1]}Z`, fill: color, stroke: "#fff", "stroke-width": 2 }));
      }
      const mid = a1 + step / 2, label = shop.name.length > 7 ? shop.name.slice(0, 6) + "…" : shop.name;
      const t = svg("text", { x: R * 0.6, y: 0, "text-anchor": "middle", "dominant-baseline": "middle", class: "lunch-label",
        transform: `rotate(${mid - 90})`, "font-size": n > 16 ? 10 : n > 10 ? 12 : 14 });
      t.textContent = label; wheel.append(t);
    });
    wheel.append(svg("circle", { r: 18, class: "lunch-hub" }));
  }

  async function load() {
    try {
      const query = new URLSearchParams({ category: byId("lunch-category").value, price: byId("lunch-price").value });
      const data = await api(`/api/lunch?${query}`);
      fillSelect(byId("lunch-category"), data.categories, "全部類型");
      fillSelect(byId("lunch-price"), data.prices, "全部價位");
      byId("lunch-category-list").replaceChildren(...data.categories.map(v => Object.assign(el("option"), { value: v })));
      byId("lunch-price-list").replaceChildren(...data.prices.map(v => Object.assign(el("option"), { value: v })));
      // 若選的值剛好被刪光，fillSelect 會重設成「全部」，這時重新讀一次
      if (query.get("category") !== byId("lunch-category").value || query.get("price") !== byId("lunch-price").value) return load();
      candidates = data.restaurants;
      byId("lunch-count").textContent = `${candidates.length} 家在輪盤上`;
      byId("lunch-spin").disabled = candidates.length < 1;
      byId("lunch-result").textContent = "";
      drawWheel(); renderTable();
    } catch (error) { byId("lunch-status").textContent = error.message; }
  }
  window.loadLunch = load;

  function spin() {
    if (spinning || !candidates.length) return;
    const n = candidates.length, step = 360 / n;
    const pick = crypto.getRandomValues(new Uint32Array(1))[0] % n;
    const jitter = (crypto.getRandomValues(new Uint32Array(1))[0] / 2 ** 32 - 0.5) * step * 0.6;
    // 指針在正上方：讓第 pick 格的中間轉到 0 度
    const target = 360 - ((pick + 0.5) * step + jitter);
    const base = rotation - (rotation % 360);
    rotation = base + 360 * 5 + ((target % 360) + 360) % 360;
    const wheel = byId("lunch-wheel"), reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    spinning = true; byId("lunch-spin").disabled = true; byId("lunch-result").textContent = "轉轉轉…";
    const done = () => {
      spinning = false; byId("lunch-spin").disabled = false;
      const shop = candidates[pick];
      byId("lunch-result").replaceChildren(el("span", "今天吃 "), el("strong", shop.name),
        ...(shop.category || shop.price ? [el("span", `（${[shop.category, shop.price].filter(Boolean).join("・")}）`)] : []),
        ...(shop.note ? [el("span", ` ${shop.note}`, "help-text")] : []));
    };
    if (reduce) { wheel.style.transition = "none"; wheel.style.transform = `rotate(${rotation}deg)`; done(); return; }
    wheel.style.transition = "transform 4s cubic-bezier(.12,.8,.18,1)";
    requestAnimationFrame(() => { wheel.style.transform = `rotate(${rotation}deg)`; });
    wheel.addEventListener("transitionend", done, { once: true });
  }

  function renderTable() {
    const box = byId("lunch-table");
    if (!candidates.length && !byId("lunch-category").value && !byId("lunch-price").value) {
      box.replaceChildren(el("p", "還沒有任何餐廳，上面填一家吧。", "help-text eq-empty")); return;
    }
    api("/api/lunch").then(data => {
      const table = el("table", undefined, "admin-table"), head = el("tr");
      for (const label of ["店名", "類型", "價位", "備註", "新增者", ""]) head.append(el("th", label));
      const thead = el("thead"); thead.append(head); const tbody = el("tbody");
      for (const shop of data.restaurants) {
        const tr = el("tr");
        tr.append(el("td", shop.name), el("td", shop.category || "—"), el("td", shop.price || "—"), el("td", shop.note || ""), el("td", shop.created_by_name));
        const actions = el("td", undefined, "admin-actions-cell");
        if (shop.created_by === currentUser.id || currentUser.role === "admin") {
          const edit = el("button", "修改", "text-button"); edit.type = "button"; edit.onclick = () => startEdit(shop);
          const del = el("button", "刪除", "text-button danger"); del.type = "button";
          del.onclick = async () => {
            if (!confirm(`從清單刪除「${shop.name}」？`)) return;
            try { await api(`/api/lunch/${shop.id}`, "DELETE"); await load(); } catch (error) { byId("lunch-status").textContent = error.message; }
          };
          actions.append(edit, del);
        }
        tr.append(actions); tbody.append(tr);
      }
      table.append(thead, tbody); box.replaceChildren(table);
    }).catch(error => { byId("lunch-status").textContent = error.message; });
  }

  function startEdit(shop) {
    editing = shop;
    byId("lunch-name").value = shop.name; byId("lunch-new-category").value = shop.category;
    byId("lunch-new-price").value = shop.price; byId("lunch-note").value = shop.note;
    byId("lunch-form-title").textContent = `修改「${shop.name}」`; byId("lunch-submit").textContent = "儲存修改"; byId("lunch-cancel").hidden = false;
    byId("lunch-name").focus();
  }
  function stopEdit() {
    editing = null; byId("lunch-form").reset();
    byId("lunch-form-title").textContent = "新增餐廳"; byId("lunch-submit").textContent = "新增"; byId("lunch-cancel").hidden = true;
  }
  byId("lunch-cancel").onclick = stopEdit;
  byId("lunch-form").onsubmit = async event => {
    event.preventDefault(); byId("lunch-status").textContent = "";
    const body = { name: byId("lunch-name").value, category: byId("lunch-new-category").value, price: byId("lunch-new-price").value, note: byId("lunch-note").value };
    try {
      if (editing) await api(`/api/lunch/${editing.id}`, "POST", body); else await api("/api/lunch", "POST", body);
      byId("lunch-status").textContent = editing ? "已修改。" : `已新增「${body.name.trim()}」。`;
      stopEdit(); await load();
    } catch (error) { byId("lunch-status").textContent = error.message; }
  };

  function tab(name) {
    byId("lunch-wheel-view").hidden = name !== "wheel"; byId("lunch-list-view").hidden = name !== "list";
    byId("lunch-tab-wheel").classList.toggle("is-active", name === "wheel"); byId("lunch-tab-list").classList.toggle("is-active", name === "list");
    byId("lunch-status").textContent = "";
  }
  byId("lunch-tab-wheel").onclick = () => tab("wheel");
  byId("lunch-tab-list").onclick = () => tab("list");
  byId("lunch-category").onchange = load;
  byId("lunch-price").onchange = load;
  byId("lunch-spin").onclick = spin;
})();
