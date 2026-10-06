/* Doctor queue: refresh every 5 s without reloading the page (docs/06 §4-1). */
(function () {
  "use strict";
  const { api, toFa } = window.Peygiri;
  const body = document.getElementById("q-body");
  const ICON = { pending: "●", done: "✓", no_followup: "–" };

  function cell(text, cls) {
    const td = document.createElement("td");
    if (cls) td.className = cls;
    td.textContent = text;
    return td;
  }

  function tag(text, cls) {
    const span = document.createElement("span");
    span.className = "tag" + (cls ? " " + cls : "");
    span.textContent = text;
    return span;
  }

  function render(data) {
    document.getElementById("q-shift").textContent = `شیفت ${data.shift.label} · ${data.shift.work_date_fa}`;
    document.getElementById("q-counts").textContent =
      `${toFa(data.total)} بیمار · ${toFa(data.pending)} در انتظار`;
    body.replaceChildren();
    if (!data.rows.length) {
      const tr = document.createElement("tr");
      const td = cell("بیماری با ویزیت شما در این شیفت ثبت نشده است.", "muted");
      td.colSpan = 4;
      tr.appendChild(td);
      body.appendChild(tr);
      return;
    }
    for (const r of data.rows) {
      const tr = document.createElement("tr");
      tr.className = "status-" + r.status;
      tr.appendChild(cell(`${ICON[r.status]} ${r.status_label}`));
      tr.appendChild(cell(r.name));
      const tags = document.createElement("td");
      if (!r.identity_ok) tags.appendChild(tag("⚠ هویت ناقص", "warn"));
      for (const s of r.services) tags.appendChild(tag(s));
      tr.appendChild(tags);
      tr.appendChild(cell(r.time ? toFa(r.time) : ""));
      body.appendChild(tr);
    }
  }

  async function refresh() {
    try { render(await api("/api/doctor/queue")); } catch (e) { /* keep the last list */ }
  }
  refresh();
  setInterval(refresh, 5000);
  document.addEventListener("peygiri:shift-changed", refresh);
})();
