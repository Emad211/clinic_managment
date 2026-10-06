/* Reception M2: local identity, explicit duplicate confirmation, no accounting writes. */
(function () {
  "use strict";
  const { api, toFa } = window.Peygiri;
  const fields = ["first_name", "last_name", "national_id", "mobile"];
  const labels = { first_name: "نام", last_name: "نام خانوادگی", mobile: "موبایل" };
  const categories = { visit: "ویزیت", bs_test: "تست قند", bp_check: "کنترل فشار" };
  const list = document.getElementById("identity-list");
  const dialog = document.getElementById("identity-dialog");
  const foreignDialog = document.getElementById("foreign-dialog");
  const form = document.getElementById("identity-form");
  const saveButton = document.getElementById("identity-save");
  const matchBox = document.getElementById("identity-match");
  let context = null, validation = null, revision = 0, timer, busy = false, foreignContext = null;

  function node(tag, text, className) {
    const el = document.createElement(tag);
    if (text != null) el.textContent = text;
    if (className) el.className = className;
    return el;
  }
  function button(text, action) {
    const el = node("button", text); el.type = "button";
    el.addEventListener("click", action); return el;
  }
  function values() { return Object.fromEntries(fields.map(k => [k, form.elements[k].value])); }
  function message(result) { window.Peygiri.toast(result.message); }
  function error(text) { document.getElementById("identity-error").textContent = text; }
  function ready() {
    const differences = validation?.match?.differences || [];
    saveButton.disabled = busy || !validation?.valid || (validation.match && (
      !document.getElementById("match-confirm")?.checked ||
      differences.some(k => !form.querySelector(`input[name="keep_${k}"]:checked`))));
  }
  function renderMatch(match) {
    matchBox.replaceChildren();
    if (!match) return;
    const person = match.person;
    matchBox.append(node("p", `این کد ملی قبلاً برای «${person.first_name} ${person.last_name}» ثبت شده است. این پرونده به همان شخص وصل می‌شود.`));
    (match.differences || []).forEach(k => {
      const group = node("fieldset"); group.append(node("legend", `${labels[k]} با اطلاعات قبلی فرق دارد؛ کدام ثبت شود؟`));
      [["existing", person[k], "قبلی"], ["entered", values()[k], "تازه واردشده"]].forEach(([choice, value, source]) => {
        const label = node("label");
        const radio = node("input"); radio.type = "radio"; radio.name = `keep_${k}`; radio.value = choice;
        radio.addEventListener("change", ready); label.append(radio, node("span", `${source}: ${toFa(value)}`)); group.append(label);
      });
      matchBox.append(group);
    });
    const label = node("label", null, "check"); const confirm = node("input");
    confirm.type = "checkbox"; confirm.id = "match-confirm"; confirm.addEventListener("change", ready);
    label.append(confirm, node("span", "کد ملی را با بیمار چک کردم؛ همین شخص است")); matchBox.append(label);
  }
  async function validate() {
    const version = ++revision, input = values();
    validation = null; ready();
    try {
      const result = await api("/api/reception/identity/validate", { method: "POST", body: JSON.stringify(input) });
      if (version !== revision || !dialog.open) return;
      validation = result;
      const problems = document.getElementById("identity-problems"); problems.replaceChildren();
      result.problems.forEach(text => problems.append(node("p", text)));
      renderMatch(result.match); ready();
    } catch (e) { if (version === revision) error(e.message); }
  }
  form.addEventListener("input", event => {
    if (!fields.includes(event.target.name)) return;
    revision++; validation = null; matchBox.replaceChildren(); error(""); ready();
    clearTimeout(timer); timer = setTimeout(validate, 250);
  });
  dialog.addEventListener("cancel", event => { if (busy) event.preventDefault(); });
  foreignDialog.addEventListener("cancel", event => { if (busy) event.preventDefault(); });
  dialog.addEventListener("close", () => { revision++; clearTimeout(timer); context = null; validation = null; });
  document.getElementById("identity-cancel").addEventListener("click", () => { if (!busy) dialog.close(); });

  async function decideSuggestion(personId, accept, match = null) {
    if (busy) return;
    busy = true; ready();
    const buttons = document.querySelectorAll("#identity-suggestions button"); buttons.forEach(b => { b.disabled = true; });
    try {
      const result = await api(`/api/reception/identity/${context.invoice_id}/suggestions/${personId}`, {
        method: "POST", body: JSON.stringify({ token: context.token, accept,
          confirm: Boolean(match), match_token: match?.token }) });
      message(result);
      if (accept) dialog.close();
      else document.querySelector(`[data-suggestion="${personId}"]`)?.remove();
      await refresh();
    } catch (e) {
      if (e.details?.match) {
        const box = document.querySelector(`[data-suggestion="${personId}"]`);
        const person = e.details.match.person;
        box.replaceChildren(node("p", `پیشنهاد فقط با موبایل و نام خانوادگی است؛ کد ملی را از بیمار بپرسید: ${toFa(person.national_id)}`),
          node("p", `${person.first_name} ${person.last_name} · ${toFa(person.mobile)}`),
          button("کد ملی بررسی شد؛ همین بیمار است", () => decideSuggestion(personId, true, e.details.match)),
          button("نه؛ پیشنهاد را رد کن", () => decideSuggestion(personId, false)));
      } else error(e.message);
    } finally { busy = false; ready(); document.querySelectorAll("#identity-suggestions button").forEach(b => { b.disabled = false; }); }
  }
  async function openIdentity(invoiceId) {
    try {
      const data = await api(`/api/reception/identity/${invoiceId}`);
      context = data; validation = null; error(""); matchBox.replaceChildren();
      document.getElementById("identity-problems").replaceChildren();
      fields.forEach(k => { form.elements[k].value = data.fields[k]; });
      document.getElementById("identity-title").textContent = `تکمیل هویت — فاکتور ${toFa(invoiceId)}`;
      const suggestions = document.getElementById("identity-suggestions"); suggestions.replaceChildren();
      data.suggestions.forEach(s => {
        const box = node("section", null, "item-card"); box.dataset.suggestion = s.person_id;
        box.append(node("p", `احتمالاً همان بیمارِ «${s.name}» (کد ملی ${toFa(s.national_id_masked)}) است`),
          button("بررسی و وصل کردن", () => decideSuggestion(s.person_id, true)),
          button("نه؛ پیشنهاد را رد کن", () => decideSuggestion(s.person_id, false))); suggestions.append(box);
      });
      ready(); dialog.showModal(); await validate();
    } catch (e) { document.getElementById("identity-list-error").textContent = e.message; }
  }
  form.addEventListener("submit", async event => {
    event.preventDefault(); if (saveButton.disabled || !context) return;
    const choices = Object.fromEntries((validation.match?.differences || []).map(k =>
      [k, form.querySelector(`input[name="keep_${k}"]:checked`).value]));
    const data = { ...values(), token: context.token, choices,
      confirm: Boolean(validation.match), match_token: validation.match?.token };
    busy = true; ready();
    form.querySelectorAll("input").forEach(i => { i.disabled = true; });
    try {
      const result = await api(`/api/reception/identity/${context.invoice_id}`, { method: "POST", body: JSON.stringify(data) });
      message(result); dialog.close(); await refresh();
    } catch (e) {
      error(e.message);
      if (e.details?.match) { validation.match = e.details.match; renderMatch(validation.match); }
    } finally { busy = false; form.querySelectorAll("input").forEach(i => { i.disabled = false; }); ready(); }
  });
  async function openForeign(invoiceId) {
    try {
      foreignContext = await api(`/api/reception/identity/${invoiceId}`);
      document.getElementById("foreign-name").textContent = `فاکتور ${toFa(invoiceId)} — ${foreignContext.fields.first_name} ${foreignContext.fields.last_name}`;
      document.getElementById("foreign-error").textContent = ""; foreignDialog.showModal();
    } catch (e) { document.getElementById("identity-list-error").textContent = e.message; }
  }
  document.getElementById("foreign-cancel").addEventListener("click", () => { if (!busy) foreignDialog.close(); });
  document.getElementById("foreign-confirm").addEventListener("click", async event => {
    if (busy) return; busy = true; event.target.disabled = true;
    try {
      const result = await api(`/api/reception/identity/${foreignContext.invoice_id}/foreign`, {
        method: "POST", body: JSON.stringify({ confirm: true, token: foreignContext.token }) });
      message(result); foreignDialog.close(); await refresh();
    } catch (e) { document.getElementById("foreign-error").textContent = e.message; }
    finally { busy = false; event.target.disabled = false; }
  });
  async function refresh() {
    try {
      const data = await api("/api/reception/identity");
      document.getElementById("identity-count").textContent = toFa(data.total);
      document.getElementById("identity-list-error").textContent = "";
      const rows = data.rows.map(r => {
        const row = node("article", null, "item-card");
        const head = node("div", null, "item-head");
        head.append(node("strong", r.name || `پرونده ${toFa(r.patient_id)}`));
        r.categories.forEach(c => { if (categories[c]) head.append(node("span", categories[c], "tag")); });
        row.append(head, node("p", `فاکتور ${toFa(r.invoice_id)} · ${r.work_date_fa} · کد ملی: ${r.national_id_masked ? toFa(r.national_id_masked) : "ثبت نشده"}`, "muted"));
        const actions = node("div", null, "actions");
        const complete = button("تکمیل هویت", () => openIdentity(r.invoice_id)); complete.className = "primary";
        actions.append(complete, button("تبعهٔ خارجی است", () => openForeign(r.invoice_id)));
        row.append(actions); return row;
      });
      list.replaceChildren(...(rows.length ? rows : [node("p", "بیماری با هویت ناقص نمانده است.", "empty")]));
      document.getElementById("identity-list-error").hidden = true;
    } catch (e) { const box = document.getElementById("identity-list-error"); box.hidden = false; box.textContent = `${e.message}؛ فهرست نمایش‌داده‌شده ممکن است قدیمی باشد.`; }
  }
  document.getElementById("identity-refresh").addEventListener("click", refresh);
  refresh(); setInterval(refresh, 5000);
})();
