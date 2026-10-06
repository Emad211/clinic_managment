/* Audit log viewer (docs/06 §6). */
(function () {
  "use strict";
  const { api, toFa, toLatin } = window.Peygiri;
  const form = document.getElementById("a-filter");
  const errorBox = document.getElementById("a-error");
  let page = 0, actionsLoaded = false;

  async function load() {
    const q = new URLSearchParams({ range: toLatin(form.elements.range.value), actor: form.elements.actor.value,
                                    action: form.elements.action.value, page });
    try {
      const d = await api(`/api/manager/audit?${q}`);
      errorBox.hidden = true;
      if (!actionsLoaded) {
        for (const [value, label] of d.actions) {
          const o = document.createElement("option"); o.value = value; o.textContent = label; form.elements.action.append(o);
        }
        actionsLoaded = true;
      }
      const body = document.getElementById("a-rows");
      body.replaceChildren();
      if (!d.rows.length) {
        const td = body.insertRow().insertCell(); td.colSpan = 5; td.className = "empty"; td.textContent = "رویدادی پیدا نشد.";
      }
      for (const r of d.rows) {
        const tr = body.insertRow();
        tr.insertCell().textContent = r.at_fa;
        tr.insertCell().textContent = r.actor;
        tr.insertCell().textContent = r.action;
        tr.insertCell().textContent = r.entity_id ? toFa(r.entity_id) : "";
        const detail = tr.insertCell(); detail.className = "mono"; detail.textContent = r.detail;
      }
      document.getElementById("a-prev").disabled = page === 0;
      document.getElementById("a-next").disabled = !d.has_more;
    } catch (e) { errorBox.hidden = false; errorBox.textContent = e.message; }
  }
  form.addEventListener("submit", (e) => { e.preventDefault(); page = 0; load(); });
  document.getElementById("a-prev").addEventListener("click", () => { page = Math.max(0, page - 1); load(); });
  document.getElementById("a-next").addEventListener("click", () => { page += 1; load(); });
  load();
})();
