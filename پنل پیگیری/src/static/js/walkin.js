/* Reception tabs + nurse paper (docs/06 §5, §5-2). */
(function () {
  "use strict";
  const { api, toFa } = window.Peygiri;
  const el = (id) => document.getElementById(id);

  // ---------------------------------------------------------------- tabs
  const tabs = [["tab-identity", "pane-identity"], ["tab-walkin", "pane-walkin"], ["tab-today", "pane-today"],
                ["tab-overdue", "pane-overdue"], ["tab-expected", "pane-expected"], ["tab-suggest", "pane-suggest"]];
  function show(tabId) {
    for (const [t, p] of tabs) {
      el(t).setAttribute("aria-selected", String(t === tabId));
      el(p).hidden = t !== tabId;
    }
    try { localStorage.setItem("peygiri:reception-tab", tabId); } catch (e) { /* storage may be blocked */ }
  }
  tabs.forEach(([t]) => el(t).addEventListener("click", () => show(t)));
  try { const saved = localStorage.getItem("peygiri:reception-tab"); if (saved && el(saved)) show(saved); } catch (e) { }
  // mirror the identity count onto its tab
  new MutationObserver(() => { el("identity-count-tab").textContent = el("identity-count").textContent; })
    .observe(el("identity-count"), { childList: true, characterData: true, subtree: true });

  // ---------------------------------------------------------------- nurse paper
  const dialog = el("walkin-dialog");
  const form = el("walkin-form");
  let current = null, busy = false;
  const toLatin = (v) => v.trim().replace(/[۰-۹]/g, (d) => "۰۱۲۳۴۵۶۷۸۹".indexOf(d));
  const num = (name) => { const v = toLatin(form.elements[name].value); return v === "" ? null : Number(v); };
  const radio = (name) => form.querySelector(`input[name=${name}]:checked`)?.value ?? null;

  function flash(text) { const p = el("walkin-message"); p.textContent = text; p.hidden = !text; }

  function button(text, onClick, cls) {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = text; if (cls) b.className = cls;
    b.addEventListener("click", onClick);
    return b;
  }

  async function post(invoiceId, data) {
    const res = await api(`/api/reception/walkins/${invoiceId}`, { method: "POST", body: JSON.stringify(data) });
    flash(res.message);
    await refresh();
    return res;
  }

  function render(data) {
    el("walkin-count").textContent = toFa(data.rows.length);
    el("walkin-cutoff").hidden = data.cutoff_approved;
    const body = el("walkin-list");
    body.replaceChildren();
    if (!data.rows.length) {
      const tr = document.createElement("tr"), td = document.createElement("td");
      td.colSpan = 4; td.className = "muted"; td.textContent = "مراجعهٔ پرستاریِ ثبت‌نشده‌ای نیست.";
      tr.appendChild(td); body.appendChild(tr); return;
    }
    for (const r of data.rows) {
      const tr = document.createElement("tr");
      const cells = [r.work_date_fa, r.name + (r.identity_ok ? "" : " ⚠"), [r.bp && "کنترل فشار", r.bs && "تست قند"].filter(Boolean).join("، ")];
      for (const text of cells) { const td = document.createElement("td"); td.textContent = text; tr.appendChild(td); }
      const actions = document.createElement("td");
      actions.className = "row-actions";
      actions.append(
        button("ورود اطلاعات", () => open(r), "primary"),
        button("کاغذ موجود نیست", async () => {
          if (!confirm(`برای «${r.name}» کاغذی ثبت نمی‌شود؟`)) return;
          try { await post(r.invoice_id, { status: "no_paper" }); } catch (e) { flash(e.message); }
        }));
      tr.appendChild(actions);
      body.appendChild(tr);
    }
  }

  function open(row) {
    current = row;
    form.reset();
    el("walkin-error").textContent = "";
    el("walkin-who").textContent = `${row.name} — ${row.work_date_fa}` + (row.identity_ok ? "" : " — هویت ناقص: پیگیری‌ها پس از تکمیل هویت فعال می‌شوند");
    el("walkin-bp").hidden = !row.bp;
    el("walkin-bs").hidden = !row.bs;
    el("walkin-renewal").hidden = true;
    dialog.showModal();
  }

  form.addEventListener("change", () => { el("walkin-renewal").hidden = radio("on_medication") !== "yes"; });
  el("walkin-cancel").addEventListener("click", () => dialog.close());
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (busy || !current) return;
    const data = { status: "entered" };
    if (current.bp && (num("systolic") !== null || num("diastolic") !== null))
      data.bp = { systolic: num("systolic"), diastolic: num("diastolic") };
    if (current.bs && num("glucose") !== null) data.bs = { glucose: num("glucose"), glucose_type: radio("glucose_type") };
    const med = radio("on_medication");
    data.on_medication = med === null ? null : med === "yes";
    if (med === "yes") {
      const quick = radio("renewal_quick");
      const typed = toLatin(form.elements.renewal_date.value);
      data.renewal = typed || (quick ? Number(quick) : null);
    }
    const device = radio("has_device");
    if (device) data.has_device = device === "yes";
    busy = true;
    try { await post(current.invoice_id, data); dialog.close(); }
    catch (e) { el("walkin-error").textContent = e.message; }
    finally { busy = false; }
  });

  async function refresh() {
    try {
      render(await api("/api/reception/walkins"));
    } catch (e) { /* keep the last list */ }
  }
  refresh();
  setInterval(() => { if (!dialog.open) refresh(); }, 5000);
})();
