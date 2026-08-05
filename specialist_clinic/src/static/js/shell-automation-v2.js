(() => {
  'use strict';

  const qs = (selector, root = document) => root.querySelector(selector);
  const qsa = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  function initPersianDatepicker() {
    if (!window.jQuery || !window.jQuery.fn.persianDatepicker) return;
    window.jQuery('input.jdate').persianDatepicker({
      format: 'YYYY/MM/DD',
      autoClose: true,
      initialValue: false,
      observer: true,
      calendar: { persian: { locale: 'fa' } },
      toolbox: {
        todayButton: { enabled: true, text: { fa: 'امروز' } },
        calendarSwitch: { enabled: false },
      },
    });
    qsa('.datepicker-plot-area[id="plotId"]').forEach((picker, index) => {
      picker.id = `datepicker-plot-${index}`;
    });
  }

  function enhanceLegacyLabels() {
    qsa('.section-title').forEach((element) => {
      if (!element.hasAttribute('role')) {
        element.setAttribute('role', 'heading');
        element.setAttribute('aria-level', '2');
      }
    });

    qsa('.fld,.field').forEach((group, index) => {
      const label = qs('label', group);
      const control = qs('input:not([type="hidden"]),select,textarea', group);
      if (!label || !control || label.htmlFor || control.closest('label')) return;
      if (!control.id) control.id = `auto-field-${index}`;
      label.htmlFor = control.id;
    });
  }

  function markScrollableTables() {
    qsa('.table-wrap').forEach((wrapper) => {
      const scrollable = wrapper.scrollWidth > wrapper.clientWidth;
      if (scrollable) {
        wrapper.tabIndex = 0;
        wrapper.setAttribute('role', 'region');
        wrapper.setAttribute('aria-label', 'جدول قابل پیمایش افقی');
      } else {
        wrapper.removeAttribute('tabindex');
        wrapper.removeAttribute('role');
        wrapper.removeAttribute('aria-label');
      }
    });
  }

  function setupNavigationDrawer() {
    const sidebar = qs('#clinic-sidebar');
    const backdrop = qs('.sidebar-backdrop');
    const toggles = qsa('[data-shell-menu-toggle]');
    if (!sidebar || !backdrop || !toggles.length) return;

    const setOpen = (open, restoreFocus = false) => {
      sidebar.classList.toggle('is-open', open);
      document.body.classList.toggle('nav-open', open);
      backdrop.setAttribute('aria-hidden', open ? 'false' : 'true');
      backdrop.tabIndex = open ? 0 : -1;
      toggles.forEach((toggle) => {
        toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
        toggle.setAttribute('aria-label', open ? 'بستن منوی اصلی' : 'باز کردن منوی اصلی');
      });
      if (open) {
        const first = qs('input,a,button', sidebar);
        if (first) window.setTimeout(() => first.focus(), 0);
      } else if (restoreFocus && toggles[0]) {
        toggles[0].focus();
      }
    };

    toggles.forEach((toggle) => {
      toggle.addEventListener('click', () => setOpen(!sidebar.classList.contains('is-open')));
    });
    backdrop.addEventListener('click', () => setOpen(false, true));
    qsa('a', sidebar).forEach((link) => {
      link.addEventListener('click', () => {
        if (window.innerWidth <= 900) setOpen(false);
      });
    });

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && sidebar.classList.contains('is-open')) {
        setOpen(false, true);
        return;
      }
      if (event.key !== 'Tab' || !sidebar.classList.contains('is-open')) return;
      const focusable = qsa('a[href],button:not([disabled]),input:not([disabled])', sidebar);
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });

    window.matchMedia('(min-width:901px)').addEventListener('change', (event) => {
      if (event.matches) setOpen(false);
    });
  }

  function setupGlobalSearchShortcut() {
    const search = qs('#global-patient-search');
    if (!search) return;
    document.addEventListener('keydown', (event) => {
      const target = event.target;
      const typing = target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement || target?.isContentEditable;
      if (!typing && (event.key === '/' || ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k'))) {
        event.preventDefault();
        if (window.innerWidth <= 900) qs('[data-shell-menu-toggle]')?.click();
        window.setTimeout(() => search.focus(), 50);
      }
    });
  }

  function preventDuplicateSubmit() {
    document.addEventListener('submit', (event) => {
      const form = event.target;
      if (!(form instanceof HTMLFormElement)) return;
      const button = event.submitter || qs('button[type="submit"],button:not([type]),input[type="submit"]', form);
      if (!button || button.disabled) return;
      if (button.name) {
        const mirror = document.createElement('input');
        mirror.type = 'hidden';
        mirror.name = button.name;
        mirror.value = button.value;
        form.appendChild(mirror);
      }
      form.setAttribute('aria-busy', 'true');
      button.dataset.originalHtml = button.tagName === 'BUTTON' ? button.innerHTML : button.value;
      button.disabled = true;
      button.classList.add('is-loading');
      button.setAttribute('aria-label', 'در حال انجام');
      if (button.tagName === 'BUTTON') button.innerHTML = '<span class="spinner" aria-hidden="true"></span><span>در حال انجام…</span>';
      else button.value = 'در حال انجام…';
      qs('#form-status')?.replaceChildren(document.createTextNode('درخواست در حال انجام است.'));
      window.setTimeout(() => {
        if (!document.contains(button)) return;
        button.disabled = false;
        button.classList.remove('is-loading');
        button.removeAttribute('aria-label');
        if (button.tagName === 'BUTTON') button.innerHTML = button.dataset.originalHtml || '';
        else button.value = button.dataset.originalHtml || '';
        form.removeAttribute('aria-busy');
        const status = qs('#form-status');
        if (status) status.textContent = '';
      }, 8000);
    }, true);
  }

  window.CLINIC_THEME = {
    tick: '#9aa8c6',
    grid: 'rgba(40,52,73,.55)',
    text: '#e9eef9',
    primary: '#3b82f6',
    ok: '#22c55e',
    warn: '#f59e0b',
    danger: '#ef4444',
    info: '#06b6d4',
    violet: '#8b5cf6',
    font: 'Vazirmatn, Tahoma, sans-serif',
  };
  if (window.Chart) {
    window.Chart.defaults.font.family = window.CLINIC_THEME.font;
    window.Chart.defaults.color = window.CLINIC_THEME.tick;
    window.Chart.defaults.borderColor = window.CLINIC_THEME.grid;
  }

  document.addEventListener('DOMContentLoaded', () => {
    initPersianDatepicker();
    enhanceLegacyLabels();
    markScrollableTables();
    setupNavigationDrawer();
    setupGlobalSearchShortcut();
    preventDuplicateSubmit();
  });
  window.addEventListener('resize', markScrollableTables, { passive: true });
})();
