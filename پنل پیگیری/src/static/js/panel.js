/* Doctor panel (docs/06 §4-2): common cases need only clicks; save returns to the patient list. */
(function () {
  "use strict";
  const { api, toFa, toLatin } = window.Peygiri;
  const visit = document.getElementById("panel").dataset.visit;
  const form = document.getElementById("p-form");
  const el = (id) => document.getElementById(id);
  const node = (tag, text, cls) => { const e = document.createElement(tag); if (text != null) e.textContent = text; if (cls) e.className = cls; return e; };
  const CHECKBOX_FOR = { quarterly_lab: "quarterly_lab", control_series_bs: "series_bs", control_series_bp: "series_bp",
                         lab_order: "lab_order", wound_care: "wound" };

  const num = (name) => { const v = toLatin(form.elements[name].value); return v === "" ? null : Number(v); };
  const checked = (name) => form.elements[name].checked;
  const radio = (name) => form.querySelector(`input[name=${name}]:checked`)?.value ?? null;

  function syncQuarterly() {
    el("row-quarterly").hidden = !checked("diabetes");
    if (!checked("diabetes")) form.elements.quarterly_lab.checked = false;
  }

  function collect() {
    const data = { decision: "followup", note: form.elements.note.value,
                   tags: { diabetes: checked("diabetes"), hypertension: checked("hypertension") } };
    const renewal = radio("renewal");
    if (renewal) data.renewal_months = Number(renewal);
    if (checked("quarterly_lab")) data.quarterly_lab = true;
    if (checked("series_bs")) data.series_bs = { count: num("bs_count"), every_days: num("bs_every") };
    if (checked("series_bp")) data.series_bp = { count: num("bp_count"), every_days: num("bp_every") };
    if (checked("lab_order")) data.lab_order = true;
    if (checked("wound")) {
      const s = radio("suture_day"), d = radio("dressing_every"), custom = toLatin(form.elements.suture_date.value);
      data.wound = { suture_day: s ? Number(s) : null, dressing_every: d === null ? null : Number(d) };
      if (!s && custom) data.wound.suture_date_fa = custom;
    }
    const ear = radio("ear_wax");
    if (ear) data.ear_wax = ear;
    if (num("systolic") !== null || num("diastolic") !== null) data.bp = { systolic: num("systolic"), diastolic: num("diastolic") };
    if (num("glucose") !== null) data.bs = { glucose: num("glucose"), glucose_type: radio("glucose_type") };
    return data;
  }

  function renderOpen(list) {
    const box = el("p-open");
    box.replaceChildren();
    if (!list.length) return;
    box.append(node("strong", "پیگیری‌های باز:"));
    for (const j of list) {
      const tag = node("span", j.title + (j.next_due_fa ? ` · موعد بعدی ${j.next_due_fa}` : ""), "tag info");
      if (j.own) {
        const b = node("button", "لغو", "small");
        b.type = "button";
        b.addEventListener("click", async () => {
          if (!confirm(`پیگیری «${j.title}» لغو شود؟`)) return;
          try { await api(`/api/journeys/${j.id}/cancel`, { method: "POST", body: "{}" }); window.Peygiri.toast("پیگیری لغو شد"); load(); }
          catch (e) { el("p-error").textContent = e.message; }
        });
        tag.append(" ", b);
      }
      box.append(tag);
    }
  }

  function prefill(d) {
    el("p-name").textContent = d.name;
    const meta = el("p-meta");
    meta.replaceChildren();
    if (d.mobile) { const m = node("span", `موبایل: ${toFa(d.mobile)}`); meta.append(m); }
    if (d.national_id_masked) meta.append(node("span", `کد ملی: ${toFa(d.national_id_masked)}`));
    meta.append(node("span", `ویزیت: ${d.work_date_long}`));
    if (d.invoice_services.length) meta.append(node("span", `خدمات همین فاکتور: ${d.invoice_services.join("، ")}`));
    el("p-identity").hidden = d.identity_ok;
    el("p-ear").hidden = !d.ear_drop_return;
    form.elements.diabetes.checked = d.tags.diabetes;
    form.elements.hypertension.checked = d.tags.hypertension;
    syncQuarterly();
    const hint = d.has_bs_test ? "تست قند روی همین فاکتور ثبت شده است؛ اگر عدد را دارید وارد کنید."
      : d.has_bp_check ? "کنترل فشار روی همین فاکتور ثبت شده است؛ اگر عدد را دارید وارد کنید." : "";
    el("p-hint").hidden = !hint;
    el("p-hint").textContent = hint;
    renderOpen(d.open_journeys);
    const saved = el("p-saved");
    saved.hidden = !d.encounter;
    if (d.encounter) {
      saved.textContent = d.encounter.decision === "no_followup" ? "برای این ویزیت قبلاً «بدون پیگیری» ثبت شده است."
        : `برای این ویزیت قبلاً ${toFa(d.encounter.journeys.length)} پیگیری ثبت شده است.`;
      if (!d.encounter.editable) {
        saved.textContent += " ویرایش فقط تا پایان روز ویزیت ممکن بود.";
        form.querySelectorAll("input, button").forEach((x) => { x.disabled = true; });
      } else {
        saved.textContent += " انتخاب‌های قبلی در فرم آمده است؛ با ثبت دوباره جایگزین می‌شوند.";
        restore(d.encounter);
      }
    }
  }

  /** Put a saved encounter back into the form: every journey with its parameters, numbers and note. */
  function restore(enc) {
    const setRadio = (name, value) => {
      const r = form.querySelector(`input[name=${name}][value="${value}"]`);
      if (r) r.checked = true;
    };
    form.elements.note.value = enc.note || "";
    for (const { code, params, suture_date_fa } of enc.choices) {
      const f = CHECKBOX_FOR[code];
      if (f && form.elements[f]) form.elements[f].checked = true;
      if (code === "renewal" && params.interval_months) setRadio("renewal", params.interval_months);
      if (code === "control_series_bs" || code === "control_series_bp") {
        const p = code.endsWith("bs") ? "bs" : "bp";
        form.elements[`${p}_count`].value = toFa(params.count);
        form.elements[`${p}_every`].value = toFa(params.every_days);
      }
      if (code === "wound_care") {
        if ([5, 7, 10, 14].includes(params.suture_day)) setRadio("suture_day", params.suture_day);
        else form.elements.suture_date.value = suture_date_fa || "";
        setRadio("dressing_every", params.dressing_every);
      }
      if (code === "ear_wax_rx") setRadio("ear_wax", "rx");
      if (code === "ear_wax_norx") setRadio("ear_wax", "norx");
    }
    for (const m of enc.measurements) {
      if (m.kind === "bp") { form.elements.systolic.value = toFa(m.systolic); form.elements.diastolic.value = toFa(m.diastolic); }
      if (m.kind === "bs") { form.elements.glucose.value = toFa(m.glucose); setRadio("glucose_type", m.glucose_type); }
    }
    syncQuarterly();
  }

  async function load() {
    try { prefill(await api(`/api/doctor/visit/${visit}`)); }
    catch (e) { el("p-error").textContent = e.message; }
  }

  async function save(data) {
    el("p-error").textContent = "";
    try {
      const res = await api(`/api/doctor/visit/${visit}`, { method: "POST", body: JSON.stringify(data) });
      sessionStorage.setItem("peygiri:flash", res.message);
      window.location.href = "/doctor";
    } catch (e) { el("p-error").textContent = e.message; }
  }

  form.elements.diabetes.addEventListener("change", syncQuarterly);
  // Picking a sub-option also ticks its row, so the common case is one click per row.
  form.querySelectorAll("input[name=suture_day], input[name=dressing_every], input[name=suture_date]").forEach((x) =>
    x.addEventListener("change", () => { form.elements.wound.checked = true; }));
  // A suture day is either one of the chips or a calendar date, never both.
  form.elements.suture_date.addEventListener("change", () => {
    if (form.elements.suture_date.value) form.querySelectorAll("input[name=suture_day]").forEach((x) => { x.checked = false; });
  });
  form.querySelectorAll("input[name=suture_day]").forEach((x) =>
    x.addEventListener("change", () => { form.elements.suture_date.value = ""; }));
  ["bs_count", "bs_every"].forEach((n) => form.elements[n].addEventListener("input", () => { form.elements.series_bs.checked = true; }));
  ["bp_count", "bp_every"].forEach((n) => form.elements[n].addEventListener("input", () => { form.elements.series_bp.checked = true; }));
  form.querySelectorAll("[data-clear]").forEach((b) => b.addEventListener("click", () =>
    form.querySelectorAll(`input[name=${b.dataset.clear}]`).forEach((x) => { x.checked = false; })));
  form.addEventListener("submit", (ev) => { ev.preventDefault(); save(collect()); });
  el("p-none").addEventListener("click", () => save({ decision: "no_followup", note: form.elements.note.value }));
  load();
})();
