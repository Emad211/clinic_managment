/* Shared: CSRF-aware fetch, toasts, Jalali date picker, header (shift + sync) and the shift dialog. */
(function () {
  "use strict";
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const FA = "۰۱۲۳۴۵۶۷۸۹";

  async function api(url, options = {}) {
    const opts = { credentials: "same-origin", ...options,
                   headers: { "Accept": "application/json", ...(options.headers || {}) } };
    if (opts.method && opts.method !== "GET") {
      opts.headers["X-CSRF-Token"] = csrf;
      opts.headers["Content-Type"] = "application/json";
    }
    const resp = await fetch(url, opts);
    if (resp.status === 401) { window.location.href = "/login"; throw new Error("ابتدا وارد شوید"); }
    const body = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      const error = new Error(body.error || "ارتباط با سرور برقرار نشد؛ دوباره تلاش کنید");
      error.status = resp.status; error.details = body; throw error;
    }
    return body;
  }

  const toFa = (v) => String(v ?? "").replace(/\d/g, (d) => FA[d]);
  const toLatin = (v) => String(v ?? "").trim().replace(/[۰-۹]/g, (d) => FA.indexOf(d)).replace(/[٠-٩]/g, (d) => "٠١٢٣٤٥٦٧٨٩".indexOf(d));

  function toast(text, isError = false) {
    if (!text) return;
    const box = document.getElementById("toasts");
    const t = document.createElement("div");
    t.className = "toast" + (isError ? " err" : "");
    t.setAttribute("role", isError ? "alert" : "status");
    t.textContent = text;
    box.appendChild(t);
    setTimeout(() => t.remove(), isError ? 7000 : 4000);
  }
  document.querySelectorAll("#toasts .toast").forEach((t) => setTimeout(() => t.remove(), 5000));

  /** Today in Jalali as "1405/07/14" (Latin digits, what the picker expects in attributes). */
  function jalaliToday(offsetDays = 0) {
    const d = new Date(Date.now() + offsetDays * 86400000);
    const parts = new Intl.DateTimeFormat("en-US-u-ca-persian", { year: "numeric", month: "2-digit", day: "2-digit" })
      .formatToParts(d).reduce((o, p) => ({ ...o, [p.type]: p.value }), {});
    return `${parts.year.replace(/\D/g, "")}/${parts.month}/${parts.day}`;
  }

  // ---------------------------------------------------------------- Jalali date picker
  // Per-input limits: data-jdp-min-date / data-jdp-max-date = "1405/07/14", "today", "today+N" or "today-N".
  // (The library's "attr" mode did not apply the limits in v1.0.0, so they are passed as options on focus.)
  function parseLimit(value) {
    if (!value) return undefined;
    const m = /^today([+-]\d+)?$/.exec(value);
    const text = m ? jalaliToday(Number(m[1] || 0)) : toLatin(value);
    const [year, month, day] = text.split("/").map(Number);
    return year && month && day ? { year, month, day } : undefined;
  }
  function startPicker() {
    if (!window.jalaliDatepicker) return;
    // Registered BEFORE startWatch so it runs before the library opens the picker: the input's own
    // limits, and render inside its modal <dialog> (a modal dialog is in the top layer; a picker
    // appended to <body> would sit behind it).
    const prepare = (ev) => {
      const input = ev.target;
      if (!(input instanceof HTMLInputElement) || !input.matches("input[data-jdp]")) return;
      const dlg = input.closest("dialog");
      window.jalaliDatepicker.updateOptions({
        container: dlg ? `#${dlg.id}` : "body",
        minDate: parseLimit(input.dataset.jdpMinDate),
        maxDate: parseLimit(input.dataset.jdpMaxDate),
      });
      // The library builds its elements once; move them next to this input's layer.
      const target = dlg || document.body;
      for (const tag of ["jdp-overlay", "jdp-container"]) {
        const e = document.querySelector(tag);
        if (e && e.parentElement !== target) target.appendChild(e);
      }
    };
    document.addEventListener("pointerdown", prepare, true);
    document.addEventListener("focusin", prepare, true);
    window.jalaliDatepicker.startWatch({
      persianDigits: true, mode: "attr", autoReadOnlyInput: false, zIndex: 4000,
      showTodayBtn: true, showEmptyBtn: false, showCloseBtn: true, hideAfterChange: true,
      dayRendering(day, input) {
        const key = `${day.year}/${String(day.month).padStart(2, "0")}/${String(day.day).padStart(2, "0")}`;
        const suggested = (input?.dataset.suggested || "").split(",").includes(key);
        return { isValid: day.isValid, isHoliday: day.weekDay === 6, className: suggested ? " suggested" : "" };   // the library appends this without a space
      },
    });
  }
  startPicker();

  // A date picked from the calendar is shown with Persian digits too.
  document.addEventListener("jdp:change", (ev) => {
    const t = ev.target;
    if (t instanceof HTMLInputElement) t.value = toFa(t.value);
  });

  // Numeric fields show Persian digits as the user types (values are converted back with toLatin).
  document.addEventListener("input", (ev) => {
    const t = ev.target;
    if (!(t instanceof HTMLInputElement) || t.inputMode !== "numeric" || t.matches("[data-jdp], [dir=ltr]")) return;
    const fa = toFa(t.value);
    if (fa !== t.value) t.value = fa;
  });

  window.Peygiri = { api, toFa, toLatin, toast, jalaliToday };

  // ---------------------------------------------------------------- header
  const shiftLabel = document.getElementById("shift-label");
  if (!shiftLabel) return;                                         // login page

  const SYNC_TEXT = { green: "متصل به حسابداری", yellow: "تأخیر در دریافت از حسابداری", red: "قطع ارتباط با حسابداری" };
  let state = null;

  function render(s) {
    state = s;
    shiftLabel.textContent = `شیفت ${s.shift.label} · ${s.shift.work_date_long}` + (s.shift.source === "manual" ? " (تنظیم دستی)" : "");
    const sync = document.getElementById("sync");
    sync.dataset.color = s.sync.color;
    const age = s.sync.age_seconds == null ? "" : ` · ${toFa(s.sync.age_seconds)} ثانیه پیش`;
    document.getElementById("sync-text").textContent = SYNC_TEXT[s.sync.color] + (s.sync.color === "red" ? "" : age);
    const banner = document.getElementById("sync-banner");
    banner.hidden = !s.sync.message;
    banner.textContent = s.sync.message;
  }
  async function refresh() {
    try { render(await api("/api/status")); } catch (e) { /* keep the last state */ }
  }
  refresh();
  setInterval(refresh, 5000);

  const dialog = document.getElementById("shift-dialog");
  const form = document.getElementById("shift-form");
  const error = document.getElementById("shift-error");
  document.getElementById("shift-change").addEventListener("click", () => {
    if (!state) return;
    error.textContent = "";
    form.work_date_fa.value = state.shift.work_date_fa;
    const radio = form.querySelector(`input[name=shift][value=${state.shift.shift}]`);
    if (radio) radio.checked = true;
    dialog.showModal();
  });
  document.getElementById("shift-cancel").addEventListener("click", () => dialog.close());

  async function send(payload, message) {
    try {
      render(await api("/api/shift", { method: "POST", body: JSON.stringify(payload) }));
      dialog.close();
      toast(message);
      document.dispatchEvent(new CustomEvent("peygiri:shift-changed"));
    } catch (e) { error.textContent = e.message; }
  }
  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const shift = form.querySelector("input[name=shift]:checked");
    if (!form.work_date_fa.value.trim()) { error.textContent = "تاریخ را انتخاب کنید"; return; }
    if (!shift) { error.textContent = "شیفت را انتخاب کنید"; return; }
    send({ work_date_fa: toLatin(form.work_date_fa.value), shift: shift.value }, "شیفت جاری تغییر کرد");
  });
  document.getElementById("shift-auto").addEventListener("click",
    () => send({ clear: true }, "شیفت جاری دوباره از حسابداری خوانده می‌شود"));
})();
