(() => {
  'use strict';

  document.documentElement.classList.add('automation-ui');

  const qs = (selector, root = document) => root.querySelector(selector);
  const qsa = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  function humanizePrimaryNavigation() {
    const nav = qs('#clinic-sidebar nav');
    if (!nav) return;

    const replacements = [
      { match: 'داشبورد', label: 'خانه' },
      { match: 'اتاقِ کنترل', label: 'مرکز کارها', href: '/followups/unified/' },
      { match: 'هاب پیام', label: 'مرکز پیام‌ها' },
      { match: 'بازبینی وصول', label: 'امور مالی' },
      { match: 'تنظیمات سیستم', label: 'مدیریت' },
    ];

    qsa('a.nav-item', nav).forEach((link) => {
      const current = link.textContent.replace(/\s+/g, ' ').trim();
      const replacement = replacements.find((item) => current.includes(item.match));
      if (!replacement) return;
      const textNode = Array.from(link.childNodes).find((node) => node.nodeType === Node.TEXT_NODE);
      if (textNode) textNode.textContent = ` ${replacement.label}`;
      link.setAttribute('data-automation-nav', replacement.label);
      if (replacement.href) link.setAttribute('href', replacement.href);
    });

    qsa('.nav-section', nav).forEach((section) => {
      if (section.textContent.trim() === 'عملیات') section.textContent = 'کار روزانه';
      if (section.textContent.trim() === 'سیستم') section.textContent = 'مدیریت';
    });

    if (window.location.pathname.startsWith('/followups/unified')) {
      qsa('a.nav-item.active', nav).forEach((link) => {
        link.classList.remove('active');
        link.removeAttribute('aria-current');
      });
      const workCenter = qs('[data-automation-nav="مرکز کارها"]', nav);
      if (workCenter) {
        workCenter.classList.add('active');
        workCenter.setAttribute('aria-current', 'page');
      }
    }
  }

  function closeSiblingMenus(opened) {
    qsa('details[data-action-menu][open]').forEach((menu) => {
      if (menu !== opened) menu.removeAttribute('open');
    });
  }

  function setupActionMenus() {
    qsa('details[data-action-menu]').forEach((menu) => {
      menu.addEventListener('toggle', () => {
        if (menu.open) closeSiblingMenus(menu);
      });
    });

    document.addEventListener('click', (event) => {
      qsa('details[data-action-menu][open]').forEach((menu) => {
        if (!menu.contains(event.target)) menu.removeAttribute('open');
      });
    });

    document.addEventListener('keydown', (event) => {
      if (event.key !== 'Escape') return;
      const opened = qs('details[data-action-menu][open]');
      if (!opened) return;
      opened.removeAttribute('open');
      const summary = qs('summary', opened);
      if (summary) summary.focus();
    });
  }

  function setupAutomaticFilters() {
    qsa('form[data-auto-filter]').forEach((form) => {
      const status = qs('[data-filter-status]', form);
      let timer = null;
      let submitting = false;

      const submit = () => {
        if (submitting) return;
        submitting = true;
        if (status) status.textContent = 'در حال به‌روزرسانی فهرست…';
        if (typeof form.requestSubmit === 'function') form.requestSubmit();
        else form.submit();
      };

      qsa('select[data-auto-submit]', form).forEach((control) => {
        control.addEventListener('change', submit);
      });

      qsa('input[data-auto-submit="debounced"]', form).forEach((control) => {
        control.addEventListener('input', () => {
          window.clearTimeout(timer);
          if (status) status.textContent = 'جست‌وجو پس از پایان تایپ انجام می‌شود.';
          timer = window.setTimeout(submit, 650);
        });
        control.addEventListener('keydown', (event) => {
          if (event.key === 'Enter') {
            event.preventDefault();
            window.clearTimeout(timer);
            submit();
          }
        });
      });
    });
  }

  function setupOneClickContactOutcomes() {
    qsa('form[data-contact-form]').forEach((form) => {
      const outcome = qs('[name="structured_outcome"]', form);
      const callbackFields = qs('[data-callback-fields]', form);
      const help = qs('[data-contact-help]', form);
      const submitButton = qs('button[type="submit"]', form);
      if (!outcome) return;

      const syncConditionalFields = () => {
        const needsCallback = outcome.value === 'CALLBACK_REQUESTED';
        if (callbackFields) callbackFields.hidden = !needsCallback;
        qsa('input', callbackFields || document.createElement('div')).forEach((input) => {
          input.required = needsCallback;
        });
      };

      outcome.addEventListener('change', syncConditionalFields);
      syncConditionalFields();

      qsa('[data-contact-outcome]', form).forEach((button) => {
        button.addEventListener('click', () => {
          if (form.getAttribute('aria-busy') === 'true') return;
          outcome.value = button.dataset.contactOutcome || '';
          syncConditionalFields();
          if (help) help.textContent = `${button.textContent.trim()} انتخاب شد؛ در حال ثبت…`;
          qsa('[data-contact-outcome]', form).forEach((candidate) => {
            candidate.setAttribute('aria-pressed', candidate === button ? 'true' : 'false');
          });
          if (typeof form.requestSubmit === 'function') form.requestSubmit(submitButton || undefined);
          else form.submit();
        });
      });
    });
  }

  function toast(message, options = {}) {
    let region = qs('.auto-toast-region');
    if (!region) {
      region = document.createElement('div');
      region.className = 'auto-toast-region';
      region.setAttribute('aria-live', 'polite');
      region.setAttribute('aria-atomic', 'false');
      document.body.appendChild(region);
    }

    const item = document.createElement('div');
    item.className = 'auto-toast';
    item.setAttribute('role', options.error ? 'alert' : 'status');

    const text = document.createElement('span');
    text.textContent = message;
    item.appendChild(text);

    if (typeof options.undo === 'function') {
      const undo = document.createElement('button');
      undo.type = 'button';
      undo.className = 'btn btn-sm btn-ghost';
      undo.textContent = 'بازگردانی';
      undo.addEventListener('click', async () => {
        undo.disabled = true;
        try {
          await options.undo();
          item.remove();
        } catch (error) {
          undo.disabled = false;
          text.textContent = 'بازگردانی انجام نشد؛ دوباره تلاش کنید.';
        }
      });
      item.appendChild(undo);
    }

    region.appendChild(item);
    window.setTimeout(() => item.remove(), options.duration || 5500);
    return item;
  }

  async function persistForm(form) {
    const indicator = qs('[data-save-indicator]', form) || qs(`[data-save-indicator-for="${form.id}"]`);
    const endpoint = form.dataset.autosaveEndpoint || form.action;
    if (!endpoint || !form.method || form.method.toLowerCase() !== 'post') return;

    if (indicator) {
      indicator.dataset.state = 'saving';
      indicator.textContent = 'در حال ذخیره';
    }

    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        body: new FormData(form),
        credentials: 'same-origin',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      if (indicator) {
        indicator.dataset.state = 'saved';
        indicator.textContent = 'ذخیره شد';
      }
      form.dataset.dirty = 'false';
    } catch (error) {
      if (indicator) {
        indicator.dataset.state = 'error';
        indicator.textContent = 'ذخیره ناموفق؛ دوباره تلاش کنید';
      }
      throw error;
    }
  }

  function setupOptInAutosave() {
    qsa('form[data-autosave="server"]')
      .filter((form) => form.dataset.autosaveEndpoint || form.action)
      .forEach((form) => {
        let timer = null;
        qsa('input:not([type="hidden"]),select,textarea', form).forEach((control) => {
          control.addEventListener('input', () => {
            form.dataset.dirty = 'true';
            window.clearTimeout(timer);
            timer = window.setTimeout(() => persistForm(form).catch(() => {}), 900);
          });
          control.addEventListener('change', () => {
            form.dataset.dirty = 'true';
            window.clearTimeout(timer);
            timer = window.setTimeout(() => persistForm(form).catch(() => {}), 250);
          });
        });
      });
  }

  function setupAutoNextFocus() {
    const firstTask = qs('[data-work-item] [data-primary-action]');
    const requested = new URLSearchParams(window.location.search).get('focus');
    if (requested === 'first' && firstTask) firstTask.focus();
  }

  function setupTechnicalDetails() {
    qsa('details[data-technical-details]').forEach((details) => {
      details.addEventListener('toggle', () => {
        if (details.open) details.dataset.wasOpened = 'true';
      });
    });
  }

  window.ClinicAutomation = Object.freeze({ toast, persistForm });

  humanizePrimaryNavigation();
  setupActionMenus();
  setupAutomaticFilters();
  setupOneClickContactOutcomes();
  setupOptInAutosave();
  setupAutoNextFocus();
  setupTechnicalDetails();
})();
