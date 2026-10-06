/* Reception tabs + nurse paper (docs/06 §5, §5-2). */
(function () {
  "use strict";
  const { api, toFa, toLatin, toast } = window.Peygiri;
  const el = (id) => document.getElementById(id);
  const node = (tag, text, cls) => { const e = document.createElement(tag); if (text != null) e.textContent = text; if (cls) e.className = cls; return e; };

  // ---------------------------------------------------------------- tabs (keyboard: ← →)
  const tabs = ["identity", "walkin", "today", "overdue", "expected", "suggest"];
  function show(name, focus = false) {
    for (const t of tabs) {
      const tab = el(`tab-${t}`);
      tab.setAttribute("aria-selected", String(t === name));
      tab.tabIndex = t === name ? 0 : -1;
      el(`pane-${t}`).hidden = t !== name;
      if (t === name && focus) tab.focus();
    }
    try { localStorage.setItem("peygiri:reception-tab", name); } catch (e) { /* storage may be blocked */ }
  }
  tabs.forEach((t, i) => {
    const tab = el(`tab-${t}`);
    tab.addEventListener("click", () => show(t));
    tab.addEventListener("keydown", (ev) => {
      if (ev.key === "ArrowLeft") show(tabs[(i + 1) % tabs.length], true);
      if (ev.key === "ArrowRight") show(tabs[(i - 1 + tabs.length) % tabs.length], true);
    });
  });
  try { const saved = localStorage.getItem("peygiri:reception-tab"); show(tabs.includes(saved) ? saved : "identity"); }
  catch (e) { show("identity"); }

  // ---------------------------------------------------------------- nurse paper
  const dialog = el("walkin-dialog");
  const form = el("walkin-form");
  let current = null, busy = false;
  const num = (name) => { const v = toLatin(form.elements[name].value); return v === "" ? null : Number(v); };
  const radio = (name) => form.querySelector(`input[name=${name}]:checked`)?.value ?? null;

  async function post(invoiceId, data) {
    const res = await api(`/api/reception/walkins/${invoiceId}`, { method: "POST", body: JSON.stringify(data) });
    toast(res.message);
    await refresh();
    return res;
  }

  function render(data) {
    const count = el("walkin-count");
    count.textContent = toFa(data.rows.length);
    count.classList.toggle("active", data.rows.length > 0);
    el("walkin-cutoff").hidden = data.cutoff_approved;
    const body = el("walkin-list");
    body.replaceChildren();
    if (!data.rows.length) {
      const tr = node("tr"), td = node("td", "برگهٔ ثبت‌نشده‌ای نمانده است.", "empty");
      td.colSpan = 4; tr.append(td); body.append(tr); return;
    }
    for (const r of data.rows) {
      const tr = node("tr");
      tr.append(node("td", r.work_date_fa));
      const who = node("td"); who.append(node("strong", r.name || "بدون نام"));
      if (!r.identity_ok) who.append(" ", node("span", "هویت ناقص", "tag warn"));
      tr.append(who, node("td", [r.bp && "کنترل فشار", r.bs && "تست قند"].filter(Boolean).join("، ")));
      const actions = node("td", null, "actions-cell");
      const enter = node("button", "ورود اطلاعات برگه", "primary small"); enter.type = "button";
      enter.addEventListener("click", () => open(r));
      const none = node("button", "برگه موجود نیست", "small"); none.type = "button";
      none.addEventListener("click", async () => {
        if (!confirm(`برای «${r.name}» برگه‌ای نیست و چیزی ثبت نمی‌شود. ادامه؟`)) return;
        try { await post(r.invoice_id, { status: "no_paper" }); } catch (e) { toast(e.message, true); }
      });
      actions.append(enter, " ", none);
      tr.append(actions);
      body.append(tr);
    }
  }

  function open(row) {
    current = row;
    form.reset();
    el("walkin-error").textContent = "";
    el("walkin-who").textContent = `${row.name} · ${row.work_date_fa}` + (row.identity_ok ? "" : " · هویت ناقص: پیگیری‌ها پس از تکمیل هویت فعال می‌شوند");
    el("walkin-bp").hidden = !row.bp;
    el("walkin-bs").hidden = !row.bs;
    el("walkin-renewal").hidden = true;
    dialog.showModal();
  }

  form.addEventListener("change", (ev) => {
    el("walkin-renewal").hidden = radio("on_medication") !== "yes";
    if (ev.target.name === "renewal_quick") form.elements.renewal_date.value = "";
  });
  form.elements.renewal_date.addEventListener("change", () => {
    form.querySelectorAll("input[name=renewal_quick]").forEach((x) => { x.checked = false; });
  });
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
      const typed = toLatin(form.elements.renewal_date.value);
      const quick = radio("renewal_quick");
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
    try { render(await api("/api/reception/walkins")); } catch (e) { /* keep the last list */ }
  }
  refresh();
  setInterval(() => { if (!dialog.open) refresh(); }, 5000);
})();
