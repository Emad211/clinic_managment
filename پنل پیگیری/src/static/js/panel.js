/* Doctor panel (docs/06 §4-2): defaults need no typing; save → back to the queue. */
(function () {
  "use strict";
  const { api, toFa } = window.Peygiri;
  const root = document.getElementById("panel");
  const visit = root.dataset.visit;
  const form = document.getElementById("p-form");
  const el = (id) => document.getElementById(id);
  const TEMPLATE_FIELD = {
    renewal: "renewal", quarterly_lab: "quarterly_lab", control_series_bs: "series_bs",
    control_series_bp: "series_bp", lab_order: "lab_order", wound_care: "wound",
  };

  const num = (name) => {
    const v = form.elements[name].value.trim();
    return v === "" ? null : Number(v.replace(/[۰-۹]/g, (d) => "۰۱۲۳۴۵۶۷۸۹".indexOf(d)));
  };
  const checked = (name) => form.elements[name].checked;
  const radio = (name) => form.querySelector(`input[name=${name}]:checked`)?.value ?? null;

  function syncQuarterly() {
    el("row-quarterly").hidden = !checked("diabetes");
    if (!checked("diabetes")) form.elements.quarterly_lab.checked = false;
  }

  function collect() {
    const data = {
      decision: "followup",
      tags: { diabetes: checked("diabetes"), hypertension: checked("hypertension") },
      note: form.elements.note.value,
    };
    const renewal = radio("renewal");
    if (renewal) data.renewal_months = Number(renewal);
    if (checked("quarterly_lab")) data.quarterly_lab = true;
    if (checked("series_bs")) data.series_bs = { count: num("bs_count"), every_days: num("bs_every") };
    if (checked("series_bp")) data.series_bp = { count: num("bp_count"), every_days: num("bp_every") };
    if (checked("lab_order")) data.lab_order = true;
    if (checked("wound")) {
      const s = radio("suture_day"), d = radio("dressing_every");
      data.wound = { suture_day: s && Number(s), dressing_every: d === null ? null : Number(d) };
    }
    const ear = radio("ear_wax");
    if (ear) data.ear_wax = ear;
    if (num("systolic") !== null || num("diastolic") !== null)
      data.bp = { systolic: num("systolic"), diastolic: num("diastolic") };
    if (num("glucose") !== null) data.bs = { glucose: num("glucose"), glucose_type: radio("glucose_type") };
    return data;
  }

  function renderOpen(list) {
    const box = el("p-open");
    box.replaceChildren();
    if (!list.length) return;
    const title = document.createElement("strong");
    title.textContent = "مسیرهای باز: ";
    box.appendChild(title);
    for (const j of list) {
      const span = document.createElement("span");
      span.className = "tag";
      span.textContent = j.title + (j.next_due ? ` — موعد ${j.next_due_fa}` : "");
      if (j.own) {
        const b = document.createElement("button");
        b.type = "button"; b.className = "link"; b.textContent = "لغو";
        b.addEventListener("click", async () => {
          if (!confirm(`مسیر «${j.title}» لغو شود؟`)) return;
          try { await api(`/api/journeys/${j.id}/cancel`, { method: "POST", body: "{}" }); load(); }
          catch (e) { el("p-error").textContent = e.message; }
        });
        span.appendChild(b);
      }
      box.appendChild(span);
    }
  }

  function prefill(d) {
    el("p-name").textContent = d.name;
    el("p-meta").textContent = [d.mobile && toFa(d.mobile), d.national_id_masked && `کد ملی ${toFa(d.national_id_masked)}`,
      d.invoice_services.length && `خدمات این فاکتور: ${d.invoice_services.join("، ")}`].filter(Boolean).join(" · ");
    el("p-identity").hidden = d.identity_ok;
    form.elements.diabetes.checked = d.tags.diabetes;
    form.elements.hypertension.checked = d.tags.hypertension;
    syncQuarterly();
    const hint = d.has_bs_test ? "تست قند روی همین فاکتور ثبت شده؛ عدد را وارد کنید."
      : d.has_bp_check ? "کنترل فشار روی همین فاکتور ثبت شده؛ عدد را وارد کنید." : "";
    el("p-hint").hidden = !hint; el("p-hint").textContent = hint ? "ⓘ " + hint : "";
    renderOpen(d.open_journeys);
    if (d.encounter) {
      const saved = el("p-saved");
      saved.hidden = false;
      saved.textContent = d.encounter.decision === "no_followup" ? "قبلاً «بدون پیگیری» ثبت شده است."
        : `قبلاً ثبت شده است (${d.encounter.journeys.length ? toFa(d.encounter.journeys.length) + " پیگیری" : "بدون مسیر باز"}).`;
      if (!d.encounter.editable) {
        saved.textContent += " ویرایش فقط تا پایان همان روز ممکن بود.";
        form.querySelectorAll("input, button").forEach((x) => { x.disabled = true; });
      } else {
        for (const code of d.encounter.journeys) {
          const f = TEMPLATE_FIELD[code];
          if (f && form.elements[f] && form.elements[f].type === "checkbox") form.elements[f].checked = true;
        }
      }
    }
  }

  async function load() {
    try {
      const d = await api(`/api/doctor/visit/${visit}`);
      prefill(d);
    } catch (e) { el("p-error").textContent = e.message; }
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
  // Choosing a sub-option ticks its row, so the common case is one click per row.
  form.querySelectorAll("input[name=suture_day], input[name=dressing_every]").forEach((x) =>
    x.addEventListener("change", () => { form.elements.wound.checked = true; }));
  ["bs_count", "bs_every"].forEach((n) => form.elements[n].addEventListener("input", () => { form.elements.series_bs.checked = true; }));
  ["bp_count", "bp_every"].forEach((n) => form.elements[n].addEventListener("input", () => { form.elements.series_bp.checked = true; }));
  el("ear-clear").addEventListener("click", () => form.querySelectorAll("input[name=ear_wax]").forEach((x) => { x.checked = false; }));
  form.addEventListener("submit", (ev) => { ev.preventDefault(); save(collect()); });
  el("p-none").addEventListener("click", () => save({ decision: "no_followup", note: form.elements.note.value }));
  load();
})();
