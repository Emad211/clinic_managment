/* Follow-ups whose origin visit accounting deleted (docs/05 G12): «ادامه» or «لغو». */
(function () {
  "use strict";
  const { api, toFa, toast } = window.Peygiri;
  const box = document.getElementById("review-box");
  const list = document.getElementById("review-list");
  if (!box || !list) return;
  const node = (tag, text, cls) => { const e = document.createElement(tag); if (text != null) e.textContent = text; if (cls) e.className = cls; return e; };
  let busy = false;

  async function decide(row, keep) {
    if (busy) return;
    if (!keep && !confirm(`پیگیری «${row.title}» برای «${row.name}» لغو شود؟`)) return;
    busy = true;
    try {
      const res = await api(`/api/journeys/${row.id}/review`, { method: "POST", body: JSON.stringify({ keep }) });
      toast(res.message);
      await refresh();
    } catch (e) { toast(e.message, true); }
    finally { busy = false; }
  }

  function render(rows) {
    box.hidden = !rows.length && !box.dataset.alwaysShow;
    list.replaceChildren(...(rows.length ? rows.map((r) => {
      const card = node("article", null, "item-card");
      const head = node("div", null, "item-head");
      head.append(node("strong", r.name), node("span", r.title, "tag info"));
      card.append(head, node("p", [`ثبت‌شده برای ویزیت ${r.start_date_fa}`, r.invoice_id && `فاکتور ${toFa(r.invoice_id)}`,
                                    r.doctor && `پزشک: ${r.doctor}`].filter(Boolean).join(" · "), "muted"));
      const keep = node("button", "ادامهٔ پیگیری", "primary small"); keep.type = "button";
      keep.addEventListener("click", () => decide(r, true));
      const cancel = node("button", "لغو پیگیری", "danger small"); cancel.type = "button";
      cancel.addEventListener("click", () => decide(r, false));
      const actions = node("div", null, "actions"); actions.append(keep, cancel);
      card.append(actions);
      return card;
    }) : [node("p", "پیگیریِ نیازمند بررسی وجود ندارد.", "empty")]));
  }

  async function refresh() {
    try { render((await api("/api/journeys/review")).rows); } catch (e) { /* keep the last list */ }
  }
  refresh();
  setInterval(() => { if (!busy) refresh(); }, 15000);
})();
