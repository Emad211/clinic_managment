/* Cut-off draft/approve (docs/05 §6, docs/06 §6). The form maps onto the §6 rule shape. */
(function () {
  "use strict";
  const { api, toFa, toLatin, toast } = window.Peygiri;
  const form = document.getElementById("c-form");
  const el = (id) => document.getElementById(id);
  const num = (name) => { const v = toLatin(form.elements[name].value); return v === "" ? null : Number(v); };
  let base = null;

  // Paths of the editable numbers inside the rules JSON.
  const FIELDS = {
    bp1_sys: ["bp", 0, "any", 0], bp1_dia: ["bp", 0, "any", 1],
    bp2_sys: ["bp", 1, "any", 0], bp2_dia: ["bp", 1, "any", 1],
    bs_fasting: ["bs", 0, "all", 1], bs_random: ["bs", 1, "all", 1],
  };
  const cond = (rules, [kind, i, mode, j]) => rules[kind][i].when[mode][j];

  function fill(rules) {
    for (const [name, path] of Object.entries(FIELDS)) form.elements[name].value = toFa(cond(rules, path).gte ?? "");
    form.elements.series_count.value = toFa(rules.series.count ?? "");
    form.elements.series_every.value = toFa(rules.series.every_days ?? "");
  }
  function collect() {
    const rules = JSON.parse(JSON.stringify(base));
    for (const [name, path] of Object.entries(FIELDS)) cond(rules, path).gte = num(name);
    rules.series = { count: num("series_count"), every_days: num("series_every") };
    return rules;
  }
  function problems(list) {
    const ul = el("c-problems");
    ul.hidden = !(list && list.length);
    ul.replaceChildren(...(list || []).map((t) => { const li = document.createElement("li"); li.textContent = t; return li; }));
  }

  function renderApproved(a) {
    const box = el("c-approved");
    box.replaceChildren();
    const p = document.createElement("p");
    if (!a) {
      p.className = "notice warn";
      p.textContent = "هنوز هیچ کات‌آفی تأیید نشده است. تا آن زمان ورود برگهٔ پرستار فقط عددها را ثبت می‌کند و دعوت یا اندازه‌گیری دوباره نمی‌سازد.";
      box.append(p);
      return;
    }
    const r = a.rules, c = (path) => toFa(cond(r, path).gte);
    p.className = "notice ok";
    p.textContent = `نسخهٔ ${toFa(a.version)}، تأییدشده در ${a.approved_at_fa}`;
    const ul = document.createElement("ul");
    for (const line of [
      `فشار: سیستول ≥ ${c(FIELDS.bp1_sys)} یا دیاستول ≥ ${c(FIELDS.bp1_dia)} ← دعوت به ویزیت و اندازه‌گیری فشار در درمانگاه`,
      `فشار: سیستول ≥ ${c(FIELDS.bp2_sys)} یا دیاستول ≥ ${c(FIELDS.bp2_dia)} ← اندازه‌گیری فشار در درمانگاه`,
      `قند ناشتا ≥ ${c(FIELDS.bs_fasting)} ← دعوت به ویزیت`,
      `قند غیرناشتا ≥ ${c(FIELDS.bs_random)} ← دعوت به ویزیت`,
      `اندازه‌گیری در درمانگاه: ${toFa(r.series.count)} نوبت، هر ${toFa(r.series.every_days)} روز`,
    ]) { const li = document.createElement("li"); li.textContent = line; ul.append(li); }
    box.append(p, ul);
  }

  async function load() {
    const s = await api("/api/cutoffs");
    renderApproved(s.approved);
    base = s.draft ? s.draft.rules : s.blank;
    fill(base);
    problems(s.draft ? s.draft.problems : []);
    el("c-approve").hidden = !(s.can_approve && s.draft);
    el("c-approve").className = "primary";
    el("c-wait").hidden = s.can_approve || !s.draft;
  }

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      const res = await api("/api/cutoffs/draft", { method: "POST", body: JSON.stringify({ rules: collect() }) });
      toast(res.problems.length ? "پیش‌نویس ذخیره شد؛ برای تأیید، موارد قرمز را کامل کنید" : "پیش‌نویس ذخیره شد و آمادهٔ تأیید است");
      await load();
      problems(res.problems);
    } catch (e) { problems([e.message]); }
  });
  el("c-approve").addEventListener("click", async () => {
    if (!confirm("این کات‌آف تأیید شود؟ از همین لحظه روی ورودهای تازهٔ برگهٔ پرستار اجرا می‌شود.")) return;
    try {
      const res = await api("/api/cutoffs/approve", { method: "POST", body: "{}" });
      toast(res.message);
      await load();
    } catch (e) { problems(e.details?.problems?.length ? e.details.problems : [e.message]); }
  });
  load().catch((e) => problems([e.message]));
})();
