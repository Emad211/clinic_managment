/* Reception calls, expected-today and match confirmation (docs/06 §5, §5-3). */
(function () {
  "use strict";
  const { api, toFa } = window.Peygiri;
  const el = (id) => document.getElementById(id);
  const node = (tag, text, cls) => { const e = document.createElement(tag); if (text != null) e.textContent = text; if (cls) e.className = cls; return e; };
  const btn = (text, fn, cls) => { const b = node("button", text, cls); b.type = "button"; b.addEventListener("click", fn); return b; };
  const toLatin = (v) => String(v || "").trim().replace(/[۰-۹]/g, (d) => "۰۱۲۳۴۵۶۷۸۹".indexOf(d));
  let data = null, booking = null, busy = false;

  function flash(text, isError) {
    const p = el("calls-message");
    p.textContent = text; p.hidden = !text;
    p.className = "flash " + (isError ? "error" : "ok");
  }

  async function send(url, body) {
    if (busy) return null;
    busy = true;
    try {
      const res = await api(url, { method: "POST", body: JSON.stringify(body) });
      flash(res.message);
      await refresh();
      return res;
    } catch (e) { flash(e.message, true); return null; }
    finally { busy = false; }
  }

  // ---------------------------------------------------------------- call cards
  function callCard(c) {
    const card = node("article", null, "call-card");
    const head = node("div", null, "call-head");
    head.append(node("strong", c.name), node("span", c.reason, "tag"));
    if (c.days_late > 0) head.append(node("span", `${toFa(c.days_late)} روز تأخیر`, "tag err"));
    if (c.attempts) head.append(node("span", `${toFa(c.attempts)} تلاش قبلی`, "tag warn"));
    card.append(head);

    const phone = node("div", null, "call-phone");
    const number = node("span", toFa(c.mobile), "mobile"); number.dir = "ltr";
    phone.append(number, btn("کپی شماره", async () => {
      try { await navigator.clipboard.writeText(c.mobile); flash("شماره کپی شد"); }
      catch (e) { flash("کپی ممکن نشد؛ شماره را دستی بردارید", true); }
    }, "link"));
    card.append(phone);
    if (c.text) card.append(node("p", c.text, "call-text"));
    const meta = [c.journey_title, c.doctor && `پزشک مبدأ: ${c.doctor}`, `موعد ${c.due_date_fa}`].filter(Boolean).join(" · ");
    card.append(node("p", meta, "muted"));
    if (c.last_note) card.append(node("p", `یادداشت قبلی: ${c.last_note}`, "muted"));

    const note = node("input"); note.maxLength = 200; note.placeholder = "یادداشت (اختیاری)"; note.setAttribute("aria-label", "یادداشت");
    const actions = node("div", null, "actions");
    const post = (outcome, extra = {}) => send(`/api/reception/calls/${c.step_id}`, { outcome, note: note.value, ...extra });
    actions.append(
      btn(c.template === "lab_order" ? "نوبت گرفت / جواب آماده است" : "نوبت گرفت", () => openBooking(c, note.value), "primary"),
      btn("جواب نداد", () => {
        if (c.attempts >= 2 && !confirm("این سومین تلاش بی‌پاسخ است؛ مسیر بسته می‌شود. ادامه؟")) return;
        post("no_answer");
      }),
      btn("نمی‌آید", () => {
        const closes = c.template !== "ear_wax_norx";
        if (!confirm(closes ? `مسیر «${c.journey_title}» بسته شود؟` : "سه روز دیگر دوباره تماس گرفته شود؟")) return;
        post("refused");
      }));
    if (c.outcomes.includes("lab_not_done")) actions.append(btn("هنوز آزمایش نداده", () => post("lab_not_done")));
    card.append(note, actions);
    return card;
  }

  function renderCalls(listId, rows, empty) {
    const box = el(listId);
    box.replaceChildren(...(rows.length ? rows.map(callCard) : [node("p", empty, "muted")]));
  }

  // ---------------------------------------------------------------- booking dialog
  async function openBooking(c, note) {
    booking = c;
    const form = el("book-form");
    form.reset();
    form.elements.note.value = note || "";
    el("book-error").textContent = "";
    el("book-who").textContent = `${c.name} — ${c.journey_title}`;
    const slots = el("book-slots");
    slots.replaceChildren(node("span", "در حال بارگذاری برنامهٔ پزشکان…", "muted"));
    el("book-dialog").showModal();
    try {
      const res = await api(`/api/reception/calls/${c.step_id}/slots`);
      slots.replaceChildren(...(res.slots.length ? res.slots.map((s) => btn(
        `${s.date_fa} ${s.shift_fa} — ${s.doctor}`, () => { form.elements.date.value = s.date_fa; }, s.origin ? "chip origin" : "chip"))
        : [node("span", "برنامهٔ معمولی برای پزشکان ثبت نشده؛ تاریخ را وارد کنید.", "muted")]));
    } catch (e) { slots.replaceChildren(node("span", e.message, "error")); }
  }
  el("book-cancel").addEventListener("click", () => el("book-dialog").close());
  el("book-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = el("book-form");
    const date = toLatin(form.elements.date.value);
    if (!date) { el("book-error").textContent = "تاریخ نوبت را وارد کنید"; return; }
    try {
      const res = await api(`/api/reception/calls/${booking.step_id}`, {
        method: "POST", body: JSON.stringify({ outcome: "booked", booked_date_fa: date, note: form.elements.note.value }) });
      el("book-dialog").close();
      flash(res.message);
      refresh();
    } catch (e) { el("book-error").textContent = e.message; }
  });

  // ---------------------------------------------------------------- expected today
  function renderExpected(rows, unlinked) {
    const body = el("expected-list");
    body.replaceChildren();
    if (!rows.length) {
      const tr = node("tr"); const td = node("td", "امروز انتظار مراجعهٔ کسی نیست.", "muted"); td.colSpan = 5;
      tr.append(td); body.append(tr); return;
    }
    for (const r of rows) {
      const tr = node("tr");
      const mobile = node("td", toFa(r.mobile)); mobile.dir = "ltr";
      tr.append(node("td", r.name + (r.booked ? " (نوبت)" : "")), mobile,
                node("td", `${r.title} · ${r.category}`), node("td", r.window_end_fa));
      const td = node("td", null, "row-actions");
      if (unlinked.length) {
        const select = node("select"); select.setAttribute("aria-label", "فاکتور امروز");
        select.append(node("option", "فاکتور بی‌هویت امروز…"));
        select.firstChild.value = "";
        for (const u of unlinked) {
          const o = node("option", `#${toFa(u.invoice_id)} — ${u.name || "بی‌نام"} ${u.categories.length ? "(" + u.categories.join("، ") + ")" : ""}`);
          o.value = u.invoice_id; select.append(o);
        }
        td.append(select, btn("اتصال", () => {
          if (!select.value) { flash("فاکتور را انتخاب کنید", true); return; }
          if (!confirm(`پروندهٔ فاکتور #${toFa(select.value)} به «${r.name}» وصل شود؟`)) return;
          send("/api/reception/link", { invoice_id: Number(select.value), person_id: r.person_id });
        }));
      } else td.append(node("span", "فاکتور بی‌هویتی امروز نیست", "muted"));
      tr.append(td); body.append(tr);
    }
  }

  // ---------------------------------------------------------------- suggestions
  function renderSuggestions(rows) {
    const body = el("suggest-list");
    body.replaceChildren();
    if (!rows.length) {
      const tr = node("tr"); const td = node("td", "پیشنهادی برای بررسی نیست.", "muted"); td.colSpan = 4;
      tr.append(td); body.append(tr); return;
    }
    for (const s of rows) {
      const tr = node("tr");
      const phone = node("td", toFa(s.phone || "")); phone.dir = "ltr";
      tr.append(node("td", `#${toFa(s.invoice_id)} ${s.invoice_name} — ${s.work_date_fa}`), phone,
                node("td", `${s.person_name} (کد ملی ${toFa(s.national_id_masked)})`));
      const td = node("td", null, "row-actions");
      td.append(btn("همین بیمار است", () => send(`/api/reception/suggestions/${s.id}`, { accept: true }), "primary"),
                btn("نه", () => send(`/api/reception/suggestions/${s.id}`, { accept: false })));
      tr.append(td); body.append(tr);
    }
  }

  async function refresh() {
    try {
      data = await api("/api/reception/followups");
      el("today-count").textContent = toFa(data.today.length);
      el("overdue-count").textContent = toFa(data.overdue.length);
      el("expected-count").textContent = toFa(data.expected.length);
      el("suggest-count").textContent = toFa(data.suggestions.length);
      renderCalls("today-list", data.today, "تماسی برای امروز نمانده است.");
      renderCalls("overdue-list", data.overdue, "تماس عقب‌افتاده‌ای نیست.");
      renderExpected(data.expected, data.unlinked_today);
      renderSuggestions(data.suggestions);
    } catch (e) { /* keep the last lists */ }
  }

  const typing = () => document.activeElement && document.activeElement.tagName === "INPUT"
    && document.activeElement.closest(".call-card");
  refresh();
  setInterval(() => { if (!el("book-dialog").open && !typing()) refresh(); }, 10000);
})();
