(function () {
  "use strict";
  const { api, toFa } = window.Peygiri, form = document.getElementById("report-filter");
  const shifts = { morning: "صبح", evening: "عصر", night: "شب", unknown: "نامشخص" };
  let revision = 0;
  async function load() {
    const current = ++revision;
    try {
      const data = await api(`/api/reports/identity?${new URLSearchParams(new FormData(form))}`);
      if (current !== revision) return;
      const rows = data.rows.map(r => {
        const tr = document.createElement("tr"), denominator = r.total - r.foreign_excluded;
        [r.username, shifts[r.shift] || "نامشخص", r.total, r.first_complete, r.accounting_complete,
          r.panel_linked, r.foreign_excluded, r.effective_complete,
          denominator ? `${Math.round(r.effective_complete * 100 / denominator)}٪` : "—"].forEach(value => {
          const td = document.createElement("td"); td.textContent = toFa(value); tr.append(td);
        }); return tr;
      });
      const body = document.getElementById("report-rows"); body.replaceChildren(...rows);
      if (!rows.length) { const tr = body.insertRow(), td = tr.insertCell(); td.colSpan = 9; td.textContent = "در این بازه فاکتوری مشاهده نشده است."; }
      document.getElementById("report-error").textContent = "";
    } catch (e) { document.getElementById("report-error").textContent = e.message; }
  }
  form.addEventListener("submit", e => { e.preventDefault(); load(); }); load();
})();
