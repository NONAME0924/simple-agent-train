/* 帳號對話框、管理後台、專案分享。 */
(() => {
  const byId = id => document.getElementById(id);
  const open = id => byId(id).classList.remove("hidden");
  const close = id => byId(id).classList.add("hidden");
  document.querySelectorAll("[data-close]").forEach(button => button.onclick = () => close(button.dataset.close));
  const text = (tag, value, className) => { const el = document.createElement(tag); el.textContent = value; if (className) el.className = className; return el; };
  const button = (label, action, className = "text-button") => { const el = text("button", label, className); el.type = "button"; el.onclick = action; return el; };
  const guard = async (status, work) => { try { await work(); } catch (error) { status.textContent = error.message; } };

  // ---------- 個人帳號 ----------
  byId("btn-account").onclick = () => { byId("pw-status").textContent = ""; open("account-modal"); };
  byId("btn-logout").onclick = async () => { try { await nativeFetch("/api/auth/logout", { method: "POST" }); } finally { location.reload(); } };
  byId("password-form").onsubmit = async event => {
    event.preventDefault();
    const status = byId("pw-status");
    await guard(status, async () => {
      await api("/api/auth/password", "POST", { old_password: byId("pw-old").value, new_password: byId("pw-new").value });
      byId("pw-old").value = byId("pw-new").value = "";
      status.textContent = "密碼已更改，其他裝置上的登入已登出。";
    });
  };

  // ---------- 管理後台 ----------
  const statusLabel = { pending: "待核准", active: "使用中", disabled: "已停用" };
  const chip = (label, tone) => text("span", label, `chip chip-${tone}`);
  async function loadUsers() {
    const status = byId("admin-status"), list = byId("admin-user-list");
    await guard(status, async () => {
      const { users } = await api("/api/admin/users");
      const pending = users.filter(u => u.status === "pending"), others = users.filter(u => u.status !== "pending");
      status.textContent = `${users.length} 個帳號，${pending.length} 個待核准。`;
      const act = (label, path, method = "POST", body, confirmText, tone = "text-button") => button(label, () => guard(status, async () => {
        if (confirmText && !confirm(confirmText)) return;
        await api(path, method, body); await loadUsers();
      }), tone);
      const base = user => `/api/admin/users/${encodeURIComponent(user.id)}`;
      const who = user => {
        const box = document.createElement("div"); box.className = "admin-who";
        const avatar = text("span", Array.from(user.real_name || user.username).slice(0, 2).join("").toUpperCase(), "admin-avatar"); avatar.setAttribute("aria-hidden", "true");
        const names = document.createElement("div");
        names.append(text("strong", user.real_name || user.username),
          text("span", user.real_name ? `${user.username}${user.id === currentUser.id ? "・你" : ""}` : `${user.username}・未填實名${user.id === currentUser.id ? "・你" : ""}`, "help-text"));
        box.append(avatar, names); return box;
      };

      // 待核准：放在最上面，核准前先看實名
      byId("admin-pending").hidden = !pending.length;
      byId("admin-pending-list").replaceChildren(...pending.map(user => {
        const row = document.createElement("div"); row.className = "admin-pending-row";
        const actions = document.createElement("span"); actions.className = "button-row";
        actions.append(act("拒絕", base(user), "DELETE", undefined, `拒絕並刪除 ${user.real_name || user.username} 的申請？`, "secondary-button danger"),
          act("核准", `${base(user)}/status/active`, "POST", undefined, undefined, "primary-button"));
        row.append(who(user), text("span", `申請於 ${user.created_at}`, "help-text"), actions); return row;
      }));

      // 其餘帳號：表格
      const table = document.createElement("table"); table.className = "admin-table";
      const head = document.createElement("tr");
      for (const label of ["使用者", "角色", "狀態", "會計", "設備管理", "對話／專案", "操作"]) head.append(text("th", label));
      const thead = document.createElement("thead"); thead.append(head);
      const tbody = document.createElement("tbody");
      for (const user of others) {
        const tr = document.createElement("tr"), self = user.id === currentUser.id;
        const cell = (...nodes) => { const td = document.createElement("td"); td.append(...nodes); tr.append(td); return td; };
        cell(who(user));
        cell(chip(user.role === "admin" ? "管理員" : "成員", user.role === "admin" ? "blue" : "gray"));
        cell(user.status === "active" ? chip("使用中", "green") : chip("已停用", "red"));
        const toggle = (field, path, label, after) => {
          const node = button("", () => guard(status, async () => {
            await api(`${base(user)}/${path}`, "POST", { value: !user[field] }); await loadUsers(); after?.();
          }), "switch");
          node.setAttribute("role", "switch"); node.setAttribute("aria-checked", String(Boolean(user[field])));
          node.setAttribute("aria-label", `${user.real_name || user.username} 是否為${label}`); node.dataset.role = path;
          node.disabled = user.status !== "active"; node.title = node.disabled ? "只能指派使用中的帳號" : `切換${label}身分`;
          return node;
        };
        cell(toggle("is_treasurer", "treasurer", "會計", () => window.refreshFinanceBadge?.()));
        cell(toggle("is_equipment_manager", "equipment_manager", "設備管理", () => window.refreshEquipmentRole?.()));
        cell(text("span", `${user.session_count}／${user.project_count}`, "help-text"));
        const actions = document.createElement("span"); actions.className = "button-row admin-actions";
        if (user.status === "active" && !self) {
          actions.append(act(user.role === "admin" ? "降為一般" : "設為管理員", `${base(user)}/role`, "POST", { role: user.role === "admin" ? "user" : "admin" }),
            act("停用", `${base(user)}/status/disabled`, "POST", undefined, `停用 ${user.username}？對方會立即登出，資料保留。`, "text-button danger"));
        }
        if (user.status === "disabled") actions.append(act("啟用", `${base(user)}/status/active`),
          act("刪除", base(user), "DELETE", undefined, `永久刪除帳號 ${user.username}？（有對話、專案或請款的帳號無法刪除）`, "text-button danger"));
        actions.append(button("重設密碼", () => guard(status, async () => {
          const password = prompt(`輸入 ${user.username} 的新密碼（8 字以上）；對方的登入會全部失效：`);
          if (!password) return;
          await api(`${base(user)}/password`, "POST", { password }); status.textContent = `已重設 ${user.username} 的密碼。`;
        })));
        cell(actions).className = "admin-actions-cell";
        tbody.append(tr);
      }
      table.append(thead, tbody);
      list.replaceChildren(table);
    });
  }
  async function loadAllSessions() {
    const status = byId("admin-status"), list = byId("admin-session-list");
    byId("admin-session-view").classList.add("hidden");
    await guard(status, async () => {
      const { sessions } = await api("/api/admin/sessions");
      status.textContent = `${sessions.length} 筆對話。`;
      list.replaceChildren(...sessions.map(s => {
        const row = document.createElement("div"); row.className = "admin-row";
        row.append(text("strong", s.title || "新對話"), text("span", `${s.owner_name || "（無擁有者）"}・${s.updated_at}`, "help-text"));
        const actions = document.createElement("span"); actions.className = "button-row";
        actions.append(button("檢視", () => viewSession(s)), button("刪除", () => guard(status, async () => {
          if (!confirm(`刪除 ${s.owner_name || ""} 的對話「${s.title}」？`)) return;
          await api(`/api/sessions/${encodeURIComponent(s.id)}`, "DELETE"); await loadAllSessions();
        }), "text-button danger"));
        row.append(actions); return row;
      }));
    });
  }
  async function viewSession(session) {
    const view = byId("admin-session-view");
    await guard(byId("admin-status"), async () => {
      const { messages } = await api(`/api/sessions/${encodeURIComponent(session.id)}/messages`);
      view.replaceChildren(text("h3", `${session.owner_name || ""}：${session.title}`),
        ...messages.map(m => { const box = document.createElement("div"); box.className = "admin-message";
          box.append(text("strong", m.role === "user" ? "使用者" : "助理"), text("pre", m.content)); return box; }));
      if (!messages.length) view.append(text("p", "這個對話還沒有訊息。", "help-text"));
      view.classList.remove("hidden"); view.scrollIntoView({ block: "nearest" });
    });
  }
  function adminTab(name) {
    for (const key of ["users", "sessions", "announce"]) {
      byId(`admin-${key}`).hidden = name !== key; byId(`admin-tab-${key}`).classList.toggle("is-active", name === key);
    }
    byId("admin-status").textContent = "";
    if (name === "users") loadUsers(); else if (name === "sessions") loadAllSessions();
  }
  byId("admin-tab-announce").onclick = () => adminTab("announce");
  byId("announce-form").onsubmit = async event => {
    event.preventDefault();
    const status = byId("admin-status");
    await guard(status, async () => {
      const to = byId("announce-to");
      if (!confirm(`發送公告給「${to.selectedOptions[0].textContent}」？`)) return;
      const { sent } = await api("/api/admin/announce", "POST", { to: to.value, title: byId("announce-title").value, body: byId("announce-body").value });
      byId("announce-form").reset(); status.textContent = `已送出給 ${sent} 人。`;
    });
  };
  byId("btn-admin").onclick = () => { close("account-modal"); open("admin-modal"); adminTab("users"); };
  byId("admin-tab-users").onclick = () => adminTab("users");
  byId("admin-tab-sessions").onclick = () => adminTab("sessions");
  byId("admin-create").onsubmit = async event => {
    event.preventDefault();
    await guard(byId("admin-status"), async () => {
      await api("/api/admin/users", "POST", { username: byId("admin-new-name").value.trim(), real_name: byId("admin-new-realname").value.trim(), password: byId("admin-new-password").value, role: byId("admin-new-role").value });
      byId("admin-new-name").value = byId("admin-new-realname").value = byId("admin-new-password").value = ""; await loadUsers();
    });
  };

  // ---------- 專案分享 ----------
  let sharing = null;
  async function loadMembers() {
    const status = byId("members-status"), list = byId("members-list");
    await guard(status, async () => {
      const data = await api(`/api/projects/${encodeURIComponent(sharing.id)}/members`);
      const owner = sharing.role === "owner" || currentUser.role === "admin";
      byId("members-title").textContent = `分享專案「${sharing.name}」`;
      byId("members-add").hidden = !owner;
      const remove = member => button(member.id === currentUser.id ? "退出專案" : "移除", () => guard(status, async () => {
        if (!confirm(member.id === currentUser.id ? "退出後就看不到這個專案了，確定？" : `移除 ${member.username}？`)) return;
        await api(`/api/projects/${encodeURIComponent(sharing.id)}/members/${encodeURIComponent(member.id)}`, "DELETE");
        if (member.id === currentUser.id) { close("members-modal"); await loadSessionsSidebarOnly(); } else await loadMembers();
      }), "text-button danger");
      const rows = [Object.assign(document.createElement("div"), { className: "admin-row" })];
      rows[0].append(text("strong", data.owner || "（無擁有者）"), text("span", "擁有者", "help-text"));
      for (const member of data.members) {
        const row = document.createElement("div"); row.className = "admin-row";
        row.append(text("strong", member.username), text("span", "成員", "help-text"));
        if (owner || member.id === currentUser.id) row.append(remove(member));
        rows.push(row);
      }
      list.replaceChildren(...rows);
    });
  }
  window.openMembers = project => { sharing = project; byId("members-status").textContent = ""; open("members-modal"); loadMembers(); };
  byId("members-add").onsubmit = async event => {
    event.preventDefault();
    await guard(byId("members-status"), async () => {
      await api(`/api/projects/${encodeURIComponent(sharing.id)}/members`, "POST", { username: byId("members-username").value.trim() });
      byId("members-username").value = ""; byId("members-status").textContent = ""; await loadMembers();
    });
  };
})();
