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

  const toFa = (v) => String(v ?? "").replace(/(\d)\.(?=\d)/g, "$1٫").replace(/\d/g, (d) => FA[d]);
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

  /** Today in Tehran (fixed UTC+3:30, like the server — never the PC's clock zone) as Jalali "1405/07/14". */
  function jalaliToday(offsetDays = 0) {
    const d = new Date(Date.now() + offsetDays * 86400000 + 12600000);
    const parts = new Intl.DateTimeFormat("en-US-u-ca-persian", { year: "numeric", month: "2-digit", day: "2-digit",
                                                                   timeZone: "UTC", numberingSystem: "latn" })
      .formatToParts(d).reduce((o, p) => ({ ...o, [p.type]: p.value }), {});
    return `${parts.year.replace(/\D/g, "")}/${parts.month}/${parts.day}`;
  }

  // ---------------------------------------------------------------- Jalali date picker
  // Per-input limits: data-jdp-min-date / data-jdp-max-date = "1405/07/14", "today", "today+N" or "today-N".
  // (The library's "attr" mode did not apply the limits in v1.0.0, so they are passed as options on focus.)
  //
  // Digits: the library parses the input's value with parseInt, so it only understands Latin digits
  // ("۱۴۰۵" → NaN: no selected day, wrong month, broken range). The field therefore holds Latin digits
  // while the calendar is open and is shown with Persian digits again once it closes.
  function parseLimit(value) {
    if (!value) return undefined;
    const m = /^today([+-]\d+)?$/.exec(value);
    const text = m ? jalaliToday(Number(m[1] || 0)) : toLatin(value);
    const [year, month, day] = text.split("/").map(Number);
    return year && month && day ? { year, month, day } : undefined;
  }
  const isDateInput = (t) => t instanceof HTMLInputElement && t.matches("input[data-jdp]");
  // Digit swaps keep the length, so the caret/selection is restored: a field entered with Tab
  // has all its text selected, and typing must still replace it.
  const swapDigits = (input, convert) => {
    const value = convert(input.value);
    if (value === input.value || value.length !== input.value.length) { if (value !== input.value) input.value = value; return; }
    const focused = document.activeElement === input;
    const [start, end, dir] = [input.selectionStart, input.selectionEnd, input.selectionDirection];
    input.value = value;
    if (focused) input.setSelectionRange(start, end, dir);
  };
  const toLatinInPlace = (input) => swapDigits(input, (v) => v.replace(/[۰-۹]/g, (d) => FA.indexOf(d)));
  const toFaInPlace = (input) => swapDigits(input, (v) => v.replace(/\d/g, (d) => FA[d]));
  let current = null;                                              // the date input the calendar belongs to
  function startPicker() {
    const jdp = window.jalaliDatepicker;
    if (!jdp) return;
    // Registered BEFORE startWatch so it runs before the library opens the picker: Latin digits,
    // the input's own limits, Tehran's today, and render inside its modal <dialog> (a modal dialog
    // is in the top layer; a picker appended to <body> would sit behind it).
    const prepare = (ev) => {
      const input = ev.target;
      if (!isDateInput(input)) return;
      toLatinInPlace(input);
      const dlg = input.closest("dialog");
      jdp.updateOptions({
        container: dlg ? `#${dlg.id}` : "body",
        // updateOptions freezes mode:"attr" to whatever the previous input had — pass it per input.
        mode: input.dataset.jdpMode === "range" ? "range" : "single",
        minDate: parseLimit(input.dataset.jdpMinDate),
        maxDate: parseLimit(input.dataset.jdpMaxDate),
        today: parseLimit("today"),
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
    jdp.startWatch({
      persianDigits: true, mode: "attr", autoReadOnlyInput: false, zIndex: 4000,
      showTodayBtn: true, showEmptyBtn: false, showCloseBtn: true, hideAfterChange: true,
      dayRendering(day, input) {
        const key = `${day.year}/${String(day.month).padStart(2, "0")}/${String(day.day).padStart(2, "0")}`;
        const suggested = (input?.dataset.suggested || "").split(",").includes(key);
        // The returned className REPLACES the library's (".selected", ".today", ".last-week"), so keep it.
        // Classes are joined with "." — the library builds elements from "div.a.b" strings.
        return { isValid: day.isValid, className: (day.className || "") + (suggested ? ".suggested" : "") };
      },
    });
    // Back to Persian digits whenever the calendar closes (pick, «بستن», Escape or click outside).
    // The library exposes no "closed" hook, so its container's visibility is watched.
    const isOpen = () => { const c = document.querySelector("jdp-container"); return !!c && c.style.visibility !== "hidden"; };
    let watched = null;
    const watch = () => {
      const c = document.querySelector("jdp-container");
      if (!c || c === watched) return;
      watched = c;
      new MutationObserver(() => { if (!isOpen() && current) toFaInPlace(current); })
        .observe(c, { attributes: true, attributeFilter: ["style"] });
    };
    document.addEventListener("focusin", (ev) => { if (isDateInput(ev.target)) { current = ev.target; setTimeout(watch, 0); } });
    // Escape with the calendar open closes only the calendar, not the dialog around it.
    let escapeForCalendar = false;
    window.addEventListener("keydown", (ev) => { if (ev.key === "Escape") escapeForCalendar = isOpen(); }, true);
    document.addEventListener("cancel", (ev) => {
      if (escapeForCalendar && ev.target instanceof HTMLDialogElement) ev.preventDefault();
      escapeForCalendar = false;
    }, true);
    // The library opens only on focus: a second click on the still-focused field must reopen it.
    document.addEventListener("click", (ev) => {
      const input = ev.target;
      if (isDateInput(input) && !isOpen()) { current = input; jdp.show(input); setTimeout(watch, 0); }
    });
    // Tabbing to another field while the calendar is open.
    document.addEventListener("focusout", (ev) => {
      const input = ev.target;
      if (isDateInput(input)) setTimeout(() => { if (document.activeElement !== input && !isOpen()) toFaInPlace(input); }, 0);
    });
    // A date typed by hand (Persian or Latin digits) moves the open calendar to it once complete.
    document.addEventListener("input", (ev) => {
      const input = ev.target;
      // isTrusted: the library fires a synthetic "input" right before it closes itself after a pick.
      if (!ev.isTrusted || !isDateInput(input) || input.dataset.jdpMode === "range") return;
      toLatinInPlace(input);
      if (/^\d{4}\/\d{2}\/\d{2}$/.test(input.value) && isOpen() && current === input) jdp.show(input);
    });
    // "1405/6/5" typed by hand → "1405/06/05" when the field is left.
    document.addEventListener("change", (ev) => {
      const input = ev.target;
      if (!ev.isTrusted || !isDateInput(input) || input.dataset.jdpMode === "range") return;
      const m = /^(\d{4})\/(\d{1,2})\/(\d{1,2})$/.exec(toLatin(input.value));
      if (!m) return;
      const padded = `${m[1]}/${m[2].padStart(2, "0")}/${m[3].padStart(2, "0")}`;
      input.value = isOpen() ? padded : toFa(padded);          // the open calendar still reads Latin digits
    });
  }
  startPicker();

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
