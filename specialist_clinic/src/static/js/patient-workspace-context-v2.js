(() => {
  'use strict';

  const workspace = window.PatientWorkspaceV2;
  if (!workspace) return;

  const STORAGE_KEY = 'clinic.patient-workspace.active-tab';
  const VALID_TABS = new Set([
    'summary',
    'actions',
    'clinical-data',
    'medications',
    'encounters-documents',
  ]);
  const qs = (selector, root = document) => root.querySelector(selector);
  const qsa = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  function selectedTab() {
    const selected = qs('.patient-workspace-tabs [role="tab"][aria-selected="true"]');
    const name = selected?.dataset.tab || '';
    return VALID_TABS.has(name) ? name : 'summary';
  }

  function storedTab() {
    try {
      const value = window.sessionStorage.getItem(STORAGE_KEY) || '';
      return VALID_TABS.has(value) ? value : '';
    } catch (_) {
      return '';
    }
  }

  function persist(name) {
    if (!VALID_TABS.has(name)) return;
    try {
      window.sessionStorage.setItem(STORAGE_KEY, name);
    } catch (_) {
      // Tab memory is optional; the workspace remains fully usable without it.
    }
    try {
      const url = new URL(window.location.href);
      url.searchParams.set('workspace_tab', name);
      url.hash = name;
      window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
    } catch (_) {
      // URL state is progressive enhancement only.
    }
  }

  const queryTab = new URLSearchParams(window.location.search).get('workspace_tab') || '';
  const current = selectedTab();
  const remembered = storedTab();
  const initial = VALID_TABS.has(queryTab)
    ? queryTab
    : (current === 'summary' && remembered ? remembered : current);
  if (initial !== current) workspace.activate(initial);
  persist(initial);

  qsa('.patient-workspace-tabs [role="tab"]').forEach((tab) => {
    tab.addEventListener('click', () => {
      window.queueMicrotask(() => persist(selectedTab()));
    });
    tab.addEventListener('keydown', (event) => {
      if (!['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(event.key)) return;
      window.queueMicrotask(() => persist(selectedTab()));
    });
  });

  // Normal POST redirects do not carry a URL fragment. Remembering only the active
  // UI tab lets the next render restore context without storing patient data.
  qsa('form', document).forEach((form) => {
    form.addEventListener('submit', () => persist(selectedTab()), { capture: true });
  });
})();
