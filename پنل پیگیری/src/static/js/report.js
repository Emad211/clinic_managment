/* Follow-up report (docs/06 §6). */
(function () {
  "use strict";
  const { api, toFa, toLatin } = window.Peygiri;
  const form = document.getElementById("r-filter");
  const errorBox = document.getElementById("r-error");
  const pct = (v) => (v == null ? "—" : `${toFa(v)}٪`);

  function fill(id, rows, cols, empty) {
    const body = document.getElementById(id);
    body.replaceChildren();
    if (!rows.length) {
      const tr = body.insertRow(), td = tr.insertCell();
      td.colSpan = cols; td.className = "empty"; td.textContent = empty;
      return;
    }
    for (const values of rows) {
      const tr = body.insertRow();
      values.forEach((v) => { tr.insertCell().textContent = typeof v === "number" ? toFa(v) : v; });
    }
  }

  async function load() {
    try {
      const d = await api(`/api/reports/followup?${new URLSearchParams({ range: toLatin(form.elements.range.value) })}`);
      errorBox.hidden = true;
      fill("r-templates", d.templates.map((t) => [t.title, t.total, t.active, t.awaiting_identity, t.succeeded, t.partial,
        t.failed, t.cancelled, pct(t.success_rate)]), 9, "در این بازه پیگیری‌ای ساخته نشده است.");
      document.getElementById("r-baseline").textContent =
        `برای مقایسه: پیش از پنل، پس از حدود ${toFa(d.baseline_rate)}٪ ویزیت‌ها بیمار برای ویزیت دوباره برگشته بود. «نزد همان پزشک» یعنی ویزیت بازگشت را همان پزشکی انجام داده که پیگیری را ثبت کرده بود.`;
      fill("r-doctors", d.doctors.map((x) => [x.doctor, x.succeeded, x.partial, x.failed, pct(x.success_rate),
        x.return_visits, x.same_doctor_visits]), 7, "در این بازه پزشکی پیگیری ثبت نکرده است.");
      fill("r-calls", d.calls.map((c) => [c.user, c.total, c.booked, c.no_answer, c.refused, c.lab_not_done]), 6,
        "در این بازه تماسی ثبت نشده است.");
    } catch (e) { errorBox.hidden = false; errorBox.textContent = e.message; }
  }
  form.addEventListener("submit", (e) => { e.preventDefault(); load(); });
  form.elements.range.addEventListener("jdp:change", load);
  load();
})();
