/* Doctor queue: refreshes every 5 s without reloading (docs/06 §4-1). */
(function () {
  "use strict";
  const { api, toFa, toast } = window.Peygiri;
  const body = document.getElementById("q-body");
  const ICON = { pending: "●", done: "✓", no_followup: "–" };

  const el = (tag, text, cls) => {
    const e = document.createElement(tag);
    if (text != null) e.textContent = text;
    if (cls) e.className = cls;
    return e;
  };

  function render(data) {
    document.getElementById("q-counts").textContent = data.total
      ? `${toFa(data.total)} بیمار · ${toFa(data.pending)} پیگیریِ ثبت‌نشده` : "";
    body.replaceChildren();
    if (!data.rows.length) {
      const tr = el("tr"), td = el("td", "هنوز ویزیتی در این شیفت به نام شما ثبت نشده است.", "empty");
      td.colSpan = 4; tr.append(td); body.append(tr);
      return;
    }
    for (const r of data.rows) {
      const href = `/doctor/visit/${r.visit_id}`;
      const tr = el("tr", null, r.status === "pending" ? "" : "is-done");
      tr.dataset.href = href;
      tr.append(el("td", r.time ? toFa(r.time) : "—"));
      const name = el("td"), link = el("a", r.name, "patient-link");
      link.href = href;
      name.append(link);
      if (!r.identity_ok) name.append(" ", el("span", "هویت ناقص", "tag warn"));
      tr.append(name);
      const services = el("td", null, "hide-sm");
      r.services.forEach((s) => services.append(el("span", s, "tag"), " "));
      if (!r.services.length) services.textContent = "—";
      tr.append(services);
      const st = el("td"); st.append(el("span", `${ICON[r.status]} ${r.status_label}`, `status ${r.status}`));
      tr.append(st);
      tr.addEventListener("click", (ev) => { if (ev.target.tagName !== "A") window.location.href = href; });
      body.append(tr);
    }
  }

  async function refresh() {
    try { render(await api("/api/doctor/queue")); } catch (e) { /* keep the last list */ }
  }
  const flash = sessionStorage.getItem("peygiri:flash");
  if (flash) { sessionStorage.removeItem("peygiri:flash"); toast(flash); }
  refresh();
  setInterval(refresh, 5000);
  document.addEventListener("peygiri:shift-changed", refresh);
})();
