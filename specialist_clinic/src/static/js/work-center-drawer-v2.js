(() => {
  'use strict';

  const list = document.querySelector('#work-center-list');
  if (!list) return;

  const parse = (html) => new DOMParser().parseFromString(html, 'text/html');
  const sameOrigin = (value) => {
    const url = new URL(value, window.location.href);
    return url.origin === window.location.origin ? url : null;
  };

  let opener = null;
  let requestController = null;

  const overlay = document.createElement('div');
  overlay.className = 'work-drawer-overlay';
  overlay.hidden = true;
  overlay.innerHTML = `
    <button class="work-drawer-backdrop" type="button" aria-label="بستن پنل رسیدگی"></button>
    <section class="work-drawer-panel" role="dialog" aria-modal="true" aria-label="رسیدگی به کار" tabindex="-1">
      <header class="work-drawer-panel__bar">
        <span data-work-drawer-status aria-live="polite">در حال آماده‌سازی…</span>
        <button class="btn btn-sm btn-ghost" type="button" data-work-drawer-close>بستن</button>
      </header>
      <div class="work-drawer-panel__body" data-work-drawer-body></div>
    </section>`;
  document.body.appendChild(overlay);

  const panel = overlay.querySelector('.work-drawer-panel');
  const body = overlay.querySelector('[data-work-drawer-body]');
  const status = overlay.querySelector('[data-work-drawer-status]');
  const closeButtons = overlay.querySelectorAll(
    '[data-work-drawer-close],.work-drawer-backdrop'
  );

  function notify(message, error = false) {
    if (window.ClinicAutomation?.toast) {
      window.ClinicAutomation.toast(message, { error });
      return;
    }
    status.textContent = message;
  }

  function setBusy(busy, message = '') {
    overlay.toggleAttribute('data-busy', busy);
    panel.setAttribute('aria-busy', busy ? 'true' : 'false');
    if (message) status.textContent = message;
  }

  function openShell(trigger) {
    opener = trigger || document.activeElement;
    overlay.hidden = false;
    document.body.classList.add('work-drawer-open');
    body.innerHTML = '<div class="work-drawer-loading" role="status">در حال بازکردن فضای رسیدگی…</div>';
    setBusy(true, 'در حال دریافت اطلاعات کار…');
    panel.focus();
  }

  function closeDrawer() {
    requestController?.abort();
    requestController = null;
    overlay.hidden = true;
    body.replaceChildren();
    document.body.classList.remove('work-drawer-open');
    setBusy(false, '');
    if (opener && document.contains(opener)) opener.focus();
    opener = null;
  }

  closeButtons.forEach((button) => button.addEventListener('click', closeDrawer));

  function focusables() {
    return Array.from(
      panel.querySelectorAll(
        'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'
      )
    ).filter((element) => !element.hidden && element.offsetParent !== null);
  }

  document.addEventListener('keydown', (event) => {
    if (overlay.hidden) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      closeDrawer();
      return;
    }
    if (event.key !== 'Tab') return;
    const items = focusables();
    if (!items.length) {
      event.preventDefault();
      panel.focus();
      return;
    }
    const first = items[0];
    const last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });

  function initializeDates(root) {
    if (!window.jQuery || typeof window.jQuery.fn?.persianDatepicker !== 'function') return;
    window.jQuery('.jdate', root).each(function initialize() {
      const field = window.jQuery(this);
      if (field.data('work-drawer-datepicker')) return;
      field.data('work-drawer-datepicker', true);
      field.persianDatepicker({
        format: 'YYYY/MM/DD',
        autoClose: true,
        initialValue: false,
        observer: true,
      });
    });
  }

  function initializeContactQuickActions(root) {
    root.querySelectorAll('form[data-contact-form]').forEach((form) => {
      if (form.dataset.drawerContactReady === 'true') return;
      form.dataset.drawerContactReady = 'true';
      const outcome = form.querySelector('[name="structured_outcome"]');
      const callback = form.querySelector('[data-callback-fields]');
      const help = form.querySelector('[data-contact-help]');
      if (!outcome) return;

      const sync = () => {
        const required = outcome.value === 'CALLBACK_REQUESTED';
        if (callback) callback.hidden = !required;
        callback?.querySelectorAll('input').forEach((input) => {
          input.required = required;
        });
      };
      outcome.addEventListener('change', sync);
      sync();

      form.querySelectorAll('[data-contact-outcome]').forEach((button) => {
        button.addEventListener('click', () => {
          if (form.getAttribute('aria-busy') === 'true') return;
          outcome.value = button.dataset.contactOutcome || '';
          sync();
          if (help) help.textContent = `${button.textContent.trim()} انتخاب شد؛ در حال ثبت…`;
          form.requestSubmit();
        });
      });
    });
  }

  function extractFlashes(documentNode) {
    return Array.from(documentNode.querySelectorAll('.flash')).map((element) => ({
      text: element.textContent.trim(),
      error: !element.classList.contains('flash-success') &&
        !element.classList.contains('flash-info') &&
        !element.classList.contains('flash-warning'),
    }));
  }

  function installWorkspace(documentNode, responseUrl) {
    const workspace = documentNode.querySelector('.work-item-drawer');
    if (!workspace) return false;

    workspace.querySelector('.work-item-back')?.setAttribute('data-work-drawer-close-link', 'true');
    body.replaceChildren(document.importNode(workspace, true));
    status.textContent = 'فضای رسیدگی آماده است.';
    setBusy(false);
    initializeDates(body);
    initializeContactQuickActions(body);

    body.querySelector('[data-work-drawer-close-link]')?.addEventListener('click', (event) => {
      event.preventDefault();
      closeDrawer();
    });
    body.querySelector('input:not([type="hidden"]),select,textarea,button,a[href]')?.focus();
    overlay.dataset.currentUrl = responseUrl;
    return true;
  }

  async function requestWorkspace(url, options = {}) {
    const target = sameOrigin(url);
    if (!target || !target.pathname.startsWith('/followups/')) {
      window.location.assign(url);
      return;
    }

    requestController?.abort();
    requestController = new AbortController();
    setBusy(true, options.message || 'در حال ثبت و بازخوانی کار…');

    let response;
    try {
      response = await fetch(target, {
        method: options.method || 'GET',
        body: options.body,
        credentials: 'same-origin',
        redirect: 'follow',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        signal: requestController.signal,
      });
    } catch (error) {
      if (error.name === 'AbortError') return;
      setBusy(false, 'ارتباط برقرار نشد.');
      notify('ارتباط با سرور برقرار نشد؛ دوباره تلاش کنید.', true);
      return;
    }

    const html = await response.text();
    const documentNode = parse(html);
    extractFlashes(documentNode).forEach((flash) => notify(flash.text, flash.error));

    if (response.ok && installWorkspace(documentNode, response.url)) return;

    const returnedUrl = sameOrigin(response.url);
    if (response.ok && returnedUrl?.pathname.startsWith('/followups/unified')) {
      window.location.assign(returnedUrl.href);
      return;
    }

    setBusy(false, `پاسخ نامعتبر از سرور (${response.status})`);
    notify('فضای رسیدگی باز نشد؛ صفحهٔ کامل را باز کنید.', true);
  }

  list.addEventListener('submit', (event) => {
    const form = event.target.closest('form');
    if (!form || !/\/followups\/unified\/.+\/handle$/.test(form.action)) return;
    event.preventDefault();
    openShell(event.submitter || form);
    requestWorkspace(form.action, {
      method: 'POST',
      body: new FormData(form),
      message: 'در حال شروع رسیدگی…',
    });
  });

  body.addEventListener('submit', (event) => {
    const form = event.target.closest('form');
    if (!form) return;
    const target = sameOrigin(form.action);
    if (!target || !target.pathname.startsWith('/followups/')) return;
    event.preventDefault();
    form.setAttribute('aria-busy', 'true');
    form.querySelectorAll('button[type="submit"]').forEach((button) => {
      button.disabled = true;
    });
    requestWorkspace(form.action, {
      method: (form.method || 'POST').toUpperCase(),
      body: new FormData(form),
      message: 'در حال ثبت اقدام…',
    }).finally(() => {
      if (!document.contains(form)) return;
      form.removeAttribute('aria-busy');
      form.querySelectorAll('button[type="submit"]').forEach((button) => {
        button.disabled = false;
      });
    });
  });
})();
