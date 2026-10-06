/* Identity compliance report: one Jalali range picker → /api/reports/identity?from=&to= */
(function () {
  "use strict";
  const { api, toFa, toLatin } = window.Peygiri;
  const form = document.getElementById("report-filter");
  const errorBox = document.getElementById("report-error");
  const shifts = { morning: "صبح", evening: "عصر", night: "شب", unknown: "نامشخص" };
  let revision = 0;

  function showError(text) { errorBox.hidden = !text; errorBox.textContent = text || ""; }

  async function load() {
    const current = ++revision;
    const parts = toLatin(form.elements.range.value).split(/\s*-\s*/).filter(Boolean);
    if (!parts.length) { showError("بازهٔ تاریخ را از تقویم انتخاب کنید"); return; }
    const [from, to] = [parts[0], parts[1] || parts[0]];
    try {
      const data = await api(`/api/reports/identity?${new URLSearchParams({ from, to })}`);
      if (current !== revision) return;
      const body = document.getElementById("report-rows");
      body.replaceChildren(...data.rows.map((r) => {
        const tr = document.createElement("tr"), denominator = r.total - r.foreign_excluded;
        [r.username, shifts[r.shift] || "نامشخص", r.total, r.first_complete, r.accounting_complete,
         r.panel_linked, r.foreign_excluded, r.effective_complete,
         denominator ? `${Math.round(r.effective_complete * 100 / denominator)}٪` : "—"].forEach((value) => {
          const td = document.createElement("td"); td.textContent = toFa(value); tr.append(td);
        });
        return tr;
      }));
      if (!data.rows.length) {
        const tr = body.insertRow(), td = tr.insertCell();
        td.colSpan = 9; td.className = "empty"; td.textContent = "در این بازه مراجعه‌ای ثبت نشده است.";
      }
      showError("");
    } catch (e) { showError(e.message); }
  }
  form.addEventListener("submit", (e) => { e.preventDefault(); load(); });
  form.elements.range.addEventListener("jdp:change", load);
  load();
})();
