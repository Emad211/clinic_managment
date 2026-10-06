/* Shared: CSRF-aware fetch, header refresh (shift + sync indicator), shift dialog. */
(function () {
  "use strict";
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";

  async function api(url, options = {}) {
    const opts = { credentials: "same-origin", ...options,
                   headers: { "Accept": "application/json", ...(options.headers || {}) } };
    if (opts.method && opts.method !== "GET") {
      opts.headers["X-CSRF-Token"] = csrf;
      opts.headers["Content-Type"] = "application/json";
    }
    const resp = await fetch(url, opts);
    if (resp.status === 401) { window.location.href = "/login"; throw new Error("unauthorized"); }
    const body = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      const error = new Error(body.error || "خطا در ارتباط با سرور");
      error.status = resp.status; error.details = body; throw error;
    }
    return body;
  }

  function toFa(n) { return String(n).replace(/\d/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[d]); }
  window.Peygiri = { api, toFa };

  const shiftLabel = document.getElementById("shift-label");
  if (!shiftLabel) return;                      // login page has no header

  const SYNC_TEXT = { green: "همگام", yellow: "تأخیر در همگام‌سازی", red: "قطع همگام‌سازی" };
  let state = null;

  function render(s) {
    state = s;
    shiftLabel.textContent = `شیفت ${s.shift.label} · ${s.shift.work_date_fa}` +
      (s.shift.source === "manual" ? " (دستی)" : "");
    const sync = document.getElementById("sync");
    sync.dataset.color = s.sync.color;
    const age = s.sync.age_seconds == null ? "" : ` (${toFa(s.sync.age_seconds)} ثانیه پیش)`;
    document.getElementById("sync-text").textContent = SYNC_TEXT[s.sync.color] + age;
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

  async function send(payload) {
    try {
      render(await api("/api/shift", { method: "POST", body: JSON.stringify(payload) }));
      dialog.close();
      document.dispatchEvent(new CustomEvent("peygiri:shift-changed"));
    } catch (e) { error.textContent = e.message; }
  }
  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const shift = form.querySelector("input[name=shift]:checked");
    if (!shift) { error.textContent = "شیفت را انتخاب کنید"; return; }
    send({ work_date_fa: form.work_date_fa.value, shift: shift.value });
  });
  document.getElementById("shift-auto").addEventListener("click", () => send({ clear: true }));
})();
