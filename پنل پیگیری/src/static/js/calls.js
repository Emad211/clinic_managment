/* Reception calls, today's expected visits and file matching (docs/06 §5, §5-3). */
(function () {
  "use strict";
  const { api, toFa, toLatin, toast } = window.Peygiri;
  const el = (id) => document.getElementById(id);
  const node = (tag, text, cls) => { const e = document.createElement(tag); if (text != null) e.textContent = text; if (cls) e.className = cls; return e; };
  const btn = (text, fn, cls) => { const b = node("button", text, cls); b.type = "button"; b.addEventListener("click", fn); return b; };
  let booking = null, busy = false;

  async function send(url, body) {
    if (busy) return null;
    busy = true;
    try {
      const res = await api(url, { method: "POST", body: JSON.stringify(body) });
      toast(res.message);
      await refresh();
      return res;
    } catch (e) { toast(e.message, true); return null; }
    finally { busy = false; }
  }

  function setCount(id, n, cls = "active") {
    const c = el(id);
    c.textContent = toFa(n);
    c.classList.toggle(cls, n > 0);
  }

  // ---------------------------------------------------------------- call cards
  function callCard(c) {
    const card = node("article", null, "item-card");
    const head = node("div", null, "item-head");
    head.append(node("strong", c.name), node("span", c.reason, "tag info"));
    if (c.days_late > 0) head.append(node("span", `${toFa(c.days_late)} روز عقب‌افتاده`, "tag err"));
    if (c.attempts) head.append(node("span", `${toFa(c.attempts)} تماس بی‌نتیجهٔ قبلی`, "tag warn"));
    card.append(head);

    const phone = node("div", null, "row");
    phone.append(node("span", toFa(c.mobile), "phone"), btn("کپی شماره", async () => {
      try { await navigator.clipboard.writeText(c.mobile); toast("شماره کپی شد"); }
      catch (e) { toast("کپی انجام نشد؛ شماره را از روی صفحه بردارید", true); }
    }, "quiet small"));
    card.append(phone);
    if (c.text) card.append(node("p", c.text, "script"));
    card.append(node("p", [c.journey_title, c.doctor && `پزشک: ${c.doctor}`, `موعد تماس: ${c.due_date_fa}`].filter(Boolean).join(" · "), "muted"));
    if (c.last_note) card.append(node("p", `یادداشت تماس قبلی: ${c.last_note}`, "muted"));

    const note = node("input", null, "note");
    note.maxLength = 200; note.placeholder = "یادداشت (اختیاری)"; note.setAttribute("aria-label", "یادداشت تماس");
    const post = (outcome, extra = {}) => send(`/api/reception/calls/${c.step_id}`, { outcome, note: note.value, ...extra });
    const actions = node("div", null, "actions");
    actions.append(
      btn(c.template === "lab_order" ? "نوبت داده شد (جواب آماده است)" : "نوبت داده شد", () => openBooking(c, note.value), "primary"),
      btn("پاسخ نداد", () => {
        if (c.attempts >= 2 && !confirm("این سومین تماس بی‌پاسخ است و پیگیری بسته می‌شود. ادامه؟")) return;
        post("no_answer");
      }),
      btn("مراجعه نمی‌کند", () => {
        const retry = c.template === "ear_wax_norx";
        if (!confirm(retry ? "سه روز دیگر دوباره تماس گرفته شود؟" : `پیگیری «${c.journey_title}» بسته شود؟`)) return;
        post("refused");
      }, "danger"));
    if (c.outcomes.includes("lab_not_done")) actions.append(btn("هنوز آزمایش نداده", () => post("lab_not_done")));
    card.append(note, actions);
    return card;
  }

  function renderCalls(listId, rows, empty) {
    el(listId).replaceChildren(...(rows.length ? rows.map(callCard) : [node("p", empty, "empty")]));
  }

  // ---------------------------------------------------------------- booking dialog
  const bookForm = el("book-form");
  async function openBooking(c, note) {
    booking = c;
    bookForm.reset();
    bookForm.elements.note.value = note || "";
    el("book-error").textContent = "";
    el("book-who").textContent = `${c.name} · ${c.journey_title}`;
    const slots = el("book-slots");
    slots.replaceChildren(node("span", "در حال خواندن برنامهٔ پزشکان…", "muted"));
    bookForm.elements.date.dataset.suggested = "";
    el("book-dialog").showModal();
    try {
      const res = await api(`/api/reception/calls/${c.step_id}/slots`);
      bookForm.elements.date.dataset.suggested = res.slots.map((s) => toLatin(s.date_fa)).join(",");
      slots.replaceChildren(...(res.slots.length
        ? res.slots.map((s) => btn(`${s.date_long} · ${s.shift_fa} · ${s.doctor}`,
            () => { bookForm.elements.date.value = s.date_fa; }, "chip" + (s.origin ? " origin" : "")))
        : [node("span", "برنامهٔ ثابتی برای این پزشکان پیدا نشد؛ تاریخ را از تقویم انتخاب کنید.", "muted")]));
    } catch (e) { slots.replaceChildren(node("span", e.message, "error")); }
  }
  el("book-cancel").addEventListener("click", () => el("book-dialog").close());
  bookForm.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const date = toLatin(bookForm.elements.date.value);
    if (!date) { el("book-error").textContent = "تاریخ نوبت را انتخاب کنید"; return; }
    try {
      const res = await api(`/api/reception/calls/${booking.step_id}`, {
        method: "POST", body: JSON.stringify({ outcome: "booked", booked_date_fa: date, note: bookForm.elements.note.value }) });
      el("book-dialog").close();
      toast(res.message);
      refresh();
    } catch (e) { el("book-error").textContent = e.message; }
  });

  // ---------------------------------------------------------------- expected today
  function renderExpected(rows, unlinked) {
    const body = el("expected-list");
    body.replaceChildren();
    if (!rows.length) {
      const tr = node("tr"), td = node("td", "امروز موعد مراجعهٔ کسی نیست.", "empty");
      td.colSpan = 5; tr.append(td); body.append(tr); return;
    }
    for (const r of rows) {
      const tr = node("tr");
      const who = node("td"); who.append(node("strong", r.name));
      if (r.booked) who.append(" ", node("span", "نوبت دارد", "tag ok"));
      tr.append(who, node("td", toFa(r.mobile), "phone-cell"), node("td", `${r.title} · ${r.category}`), node("td", r.window_end_fa));
      const td = node("td", null, "actions-cell");
      if (unlinked.length) {
        const select = node("select");
        select.setAttribute("aria-label", `فاکتور امروزِ ${r.name}`);
        const first = node("option", "انتخاب فاکتور…"); first.value = ""; select.append(first);
        for (const u of unlinked) {
          const label = `فاکتور ${toFa(u.invoice_id)} · ${u.name || "بدون نام"}` + (u.categories.length ? ` · ${u.categories.join("، ")}` : "");
          const o = node("option", label); o.value = u.invoice_id; select.append(o);
        }
        td.append(select, " ", btn("وصل کن", () => {
          if (!select.value) { toast("اول فاکتور را انتخاب کنید", true); return; }
          if (!confirm(`پروندهٔ فاکتور ${toFa(select.value)} به «${r.name}» وصل شود؟`)) return;
          send("/api/reception/link", { invoice_id: Number(select.value), person_id: r.person_id });
        }, "small"));
      } else td.append(node("span", "فاکتورِ بدون هویتی امروز ثبت نشده", "faint"));
      tr.append(td);
      body.append(tr);
    }
  }

  // ---------------------------------------------------------------- file matching
  function renderSuggestions(rows) {
    const body = el("suggest-list");
    body.replaceChildren();
    if (!rows.length) {
      const tr = node("tr"), td = node("td", "موردی برای بررسی نیست.", "empty");
      td.colSpan = 4; tr.append(td); body.append(tr); return;
    }
    for (const s of rows) {
      const tr = node("tr");
      tr.append(node("td", `فاکتور ${toFa(s.invoice_id)} · ${s.invoice_name || "بدون نام"} · ${s.work_date_fa}`),
                node("td", toFa(s.phone || "")),
                node("td", `${s.person_name} · کد ملی ${toFa(s.national_id_masked)}`));
      const td = node("td", null, "actions-cell");
      td.append(btn("همین بیمار است", () => send(`/api/reception/suggestions/${s.id}`, { accept: true }), "primary small"), " ",
                btn("نه، بیمار دیگری است", () => send(`/api/reception/suggestions/${s.id}`, { accept: false }), "small"));
      tr.append(td);
      body.append(tr);
    }
  }

  async function refresh() {
    try {
      const data = await api("/api/reception/followups");
      setCount("today-count", data.today.length);
      setCount("overdue-count", data.overdue.length, "alert");
      setCount("expected-count", data.expected.length);
      setCount("suggest-count", data.suggestions.length);
      renderCalls("today-list", data.today, "تماسی برای امروز نمانده است.");
      renderCalls("overdue-list", data.overdue, "تماس عقب‌افتاده‌ای نیست.");
      renderExpected(data.expected, data.unlinked_today);
      renderSuggestions(data.suggestions);
    } catch (e) { /* keep the last lists */ }
  }

  const typing = () => document.activeElement?.closest?.(".item-card, #pane-expected") && document.activeElement.matches("input, select");
  refresh();
  setInterval(() => { if (!el("book-dialog").open && !typing()) refresh(); }, 10000);
})();
