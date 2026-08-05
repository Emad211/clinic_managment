(() => {
  'use strict';

  const qs = (selector, root = document) => root.querySelector(selector);
  const qsa = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const normalize = (value) => String(value || '').replace(/\s+/g, ' ').trim();

  const hero = qs('.patient-hero');
  const oldTabbar = qs('.tabbar[role="tablist"]');
  const summaryPane = qs('#pane-cockpit');
  const trendsPane = qs('#pane-trends');
  const medicationsPane = qs('#pane-meds');
  const recordPane = qs('#pane-record');
  if (!hero || !oldTabbar || !summaryPane || !trendsPane || !medicationsPane || !recordPane) return;

  document.documentElement.classList.add('patient-workspace-v2');
  document.body.classList.add('patient-workspace-v2');

  function ensureStyles() {
    if (qs('link[data-patient-workspace-v2]')) return;
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = '/static/css/patient-workspace-automation-v2.css';
    link.dataset.patientWorkspaceV2 = 'true';
    document.head.appendChild(link);
  }

  function titleText(element) {
    return normalize(qs('.section-title', element)?.textContent);
  }

  function findCard(root, title) {
    return qsa('.section-title', root)
      .find((heading) => normalize(heading.textContent).startsWith(title))
      ?.closest('.card') || null;
  }

  function createPane(name, label) {
    const pane = document.createElement('section');
    pane.className = 'tab-pane patient-workspace-pane';
    pane.id = `pane-${name}`;
    pane.dataset.pane = name;
    pane.setAttribute('role', 'tabpanel');
    pane.setAttribute('aria-labelledby', `tab-${name}`);
    pane.setAttribute('aria-label', label);
    pane.hidden = true;
    return pane;
  }

  function renamePane(pane, name, label) {
    pane.id = `pane-${name}`;
    pane.dataset.pane = name;
    pane.setAttribute('aria-labelledby', `tab-${name}`);
    pane.setAttribute('aria-label', label);
    pane.classList.add('patient-workspace-pane');
  }

  function closestActionLink(pattern) {
    return qsa('.pt-actions a', hero).find((link) => pattern.test(link.getAttribute('href') || '')) || null;
  }

  function cloneActionLink(source, label) {
    if (!source) return null;
    const clone = source.cloneNode(true);
    clone.removeAttribute('id');
    clone.className = 'btn btn-ghost patient-workspace-action';
    const icon = qs('svg', clone);
    clone.textContent = label;
    if (icon) clone.prepend(icon);
    return clone;
  }

  function createTextAction(label, href) {
    const link = document.createElement('a');
    link.className = 'btn btn-ghost patient-workspace-action';
    link.href = href;
    link.textContent = label;
    return link;
  }

  function moveHeaderContextIntoStickyHero(encountersPane) {
    const allergy = Array.from(hero.parentElement?.children || [])
      .find((node) => node !== hero && node.matches?.('.alert-banner.alert-warn') && normalize(node.textContent).startsWith('آلرژی‌ها'));
    if (allergy) {
      allergy.classList.add('patient-workspace-allergy');
      hero.appendChild(allergy);
    }

    const statusItems = qsa('.patient-status-item', hero);
    const appointmentCard = qsa(':scope > .grid > .card, :scope > .card', encountersPane)
      .find((card) => titleText(card).startsWith('نوبت‌ها'));
    const visitCard = qsa(':scope > .grid > .card, :scope > .card', encountersPane)
      .find((card) => titleText(card).startsWith('سابقه ویزیت'));

    const appointmentRow = appointmentCard
      ? qsa(':scope > .flex, .list-row', appointmentCard).find((row) => !row.classList.contains('section-title'))
      : null;
    const visitRow = visitCard
      ? qsa(':scope > .flex, .list-row', visitCard).find((row) => !row.classList.contains('section-title'))
      : null;

    const appointmentItem = statusItems.find((item) => normalize(qs('span', item)?.textContent).includes('نوبت'));
    if (appointmentItem) {
      qs('span', appointmentItem).textContent = 'نوبت بعدی';
      const raw = normalize(appointmentRow?.textContent);
      qs('strong', appointmentItem).textContent = raw ? raw.split('—')[0].trim() : 'ثبت نشده';
    }

    const visitItem = statusItems.find((item) => normalize(qs('span', item)?.textContent).includes('ویزیت'));
    if (visitItem) {
      qs('span', visitItem).textContent = 'آخرین پزشک';
      const raw = normalize(visitRow?.textContent);
      const pieces = raw.split('—');
      qs('strong', visitItem).textContent = pieces.length > 1 ? pieces[1].split('(')[0].trim() : 'ثبت نشده';
    }
  }

  function buildActionsPane(actionsPane, quickVitalsCard, followupsCard, consent) {
    const quickCard = document.createElement('section');
    quickCard.className = 'card patient-workspace-quick-actions';
    quickCard.innerHTML = `
      <div class="section-title">
        <span>اقدامات پرونده</span>
        <span class="section-sub">اقدام‌های پرتکرار بدون جست‌وجو میان صفحات</span>
      </div>
      <div class="patient-workspace-action-grid"></div>
    `;
    const grid = qs('.patient-workspace-action-grid', quickCard);
    const patientName = normalize(qs('#patient-name')?.textContent);
    const currentPatientPath = window.location.pathname.replace(/\/$/, '');

    const appointmentLink = closestActionLink(/appointments\/new/);
    const patientCardLink = closestActionLink(/\/card(?:$|\?)/);
    const workCenterLink = qsa('#clinic-sidebar a.nav-item')
      .find((link) => normalize(link.textContent) === 'مرکز کارها');

    const appointmentAction = cloneActionLink(appointmentLink, 'ثبت نوبت');
    if (appointmentAction) grid.appendChild(appointmentAction);

    const measurementButton = document.createElement('button');
    measurementButton.type = 'button';
    measurementButton.className = 'btn btn-ghost patient-workspace-action';
    measurementButton.textContent = 'ثبت شاخص';
    measurementButton.addEventListener('click', () => {
      activate('actions', { updateHash: true });
      quickVitalsCard?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      qs('input:not([type="hidden"]),select,textarea', quickVitalsCard || document)?.focus();
    });
    grid.appendChild(measurementButton);

    if (workCenterLink) {
      const url = new URL(workCenterLink.href, window.location.origin);
      url.searchParams.set('view', 'all');
      if (patientName) url.searchParams.set('q', patientName);
      grid.appendChild(createTextAction('کارهای این بیمار', url.toString()));
    }

    grid.appendChild(createTextAction('بررسی اختلاف اطلاعات', `${currentPatientPath}/reconciliation`));

    if (patientCardLink) {
      const cardAction = cloneActionLink(patientCardLink, 'کارت بیمار و یادآوری');
      if (cardAction) grid.appendChild(cardAction);
      patientCardLink.remove();
    }

    const inviteForm = qsa('form', medicationsPane).find((form) => {
      try {
        return /\/invite$/.test(new URL(form.action, window.location.origin).pathname);
      } catch (_) {
        return false;
      }
    });
    if (inviteForm) {
      inviteForm.classList.add('patient-workspace-inline-action');
      const button = qs('button', inviteForm);
      if (button) {
        button.className = 'btn btn-ghost patient-workspace-action';
        button.textContent = 'افزودن دعوت پیامکی';
      }
      grid.appendChild(inviteForm);
    }

    actionsPane.appendChild(quickCard);
    if (consent) actionsPane.appendChild(consent);
    if (followupsCard) actionsPane.appendChild(followupsCard);
    if (quickVitalsCard) {
      quickVitalsCard.id = 'patient-quick-vitals';
      actionsPane.appendChild(quickVitalsCard);
    }
  }

  ensureStyles();

  const actionsPane = createPane('actions', 'اقدامات');
  const encountersPane = createPane('encounters-documents', 'ویزیت‌ها و اسناد');
  renamePane(summaryPane, 'summary', 'خلاصه');
  renamePane(trendsPane, 'clinical-data', 'داده‌های بالینی');
  renamePane(medicationsPane, 'medications', 'دارو و نسخه');

  summaryPane.after(actionsPane);
  actionsPane.after(trendsPane);
  trendsPane.after(medicationsPane);
  medicationsPane.after(encountersPane);

  const followupsCard = findCard(summaryPane, 'پیگیری‌های باز');
  const quickVitalsCard = findCard(summaryPane, 'ثبت سریع شاخص‌ها');
  const careTimelineCard = qs('.care-timeline-card', summaryPane);
  const consent = qs('#sms-consent');

  const encounterGrid = qsa(':scope > .grid', recordPane).find((grid) => {
    const text = normalize(grid.textContent);
    return text.includes('نوبت‌ها') && text.includes('سابقه ویزیت');
  });
  if (careTimelineCard) encountersPane.appendChild(careTimelineCard);
  if (encounterGrid) encountersPane.appendChild(encounterGrid);

  Array.from(recordPane.childNodes).forEach((node) => trendsPane.appendChild(node));
  recordPane.remove();

  buildActionsPane(actionsPane, quickVitalsCard, followupsCard, consent);
  moveHeaderContextIntoStickyHero(encountersPane);

  const paneDefinitions = [
    { name: 'summary', label: 'خلاصه' },
    { name: 'actions', label: 'اقدامات' },
    { name: 'clinical-data', label: 'داده‌های بالینی' },
    { name: 'medications', label: 'دارو و نسخه' },
    { name: 'encounters-documents', label: 'ویزیت‌ها و اسناد' },
  ];
  const paneMap = new Map(
    qsa('.patient-workspace-pane').map((pane) => [pane.dataset.pane, pane])
  );

  const newTabbar = document.createElement('div');
  newTabbar.className = 'tabbar patient-workspace-tabs';
  newTabbar.setAttribute('role', 'tablist');
  newTabbar.setAttribute('aria-label', 'بخش‌های پرونده بیمار');

  const oldSummaryPill = qs('#tab-cockpit .pill')?.cloneNode(true);
  paneDefinitions.forEach((definition, index) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.role = 'tab';
    button.id = `tab-${definition.name}`;
    button.dataset.tab = definition.name;
    button.setAttribute('aria-controls', `pane-${definition.name}`);
    button.setAttribute('aria-selected', index === 0 ? 'true' : 'false');
    button.tabIndex = index === 0 ? 0 : -1;
    button.textContent = definition.label;
    if (definition.name === 'summary' && oldSummaryPill) button.appendChild(oldSummaryPill);
    newTabbar.appendChild(button);
  });
  oldTabbar.replaceWith(newTabbar);

  const aliases = {
    cockpit: 'summary',
    summary: 'summary',
    worklist: 'actions',
    appointment: 'actions',
    actions: 'actions',
    trends: 'clinical-data',
    record: 'clinical-data',
    labs: 'clinical-data',
    vitals: 'clinical-data',
    'clinical-data': 'clinical-data',
    meds: 'medications',
    medications: 'medications',
    'encounters-documents': 'encounters-documents',
  };

  function normalizeTab(name) {
    return aliases[name] || 'summary';
  }

  function updateSelection(name) {
    qsa('[role="tab"]', newTabbar).forEach((button) => {
      const selected = button.dataset.tab === name;
      button.classList.toggle('active', selected);
      button.setAttribute('aria-selected', selected ? 'true' : 'false');
      button.tabIndex = selected ? 0 : -1;
    });
    paneMap.forEach((pane, paneName) => {
      pane.hidden = paneName !== name;
    });
  }

  function activate(requested, options = {}) {
    const name = normalizeTab(requested);
    updateSelection(name);
    if (name === 'clinical-data' && typeof window.initTrends === 'function') {
      window.initTrends();
    }
    if (options.updateHash !== false) {
      try {
        history.replaceState(null, '', `#${name}`);
      } catch (_) {
        // Hash persistence is an enhancement; navigation remains usable without it.
      }
    }
    return name;
  }

  qsa('[role="tab"]', newTabbar).forEach((button, index, buttons) => {
    button.addEventListener('click', () => activate(button.dataset.tab));
    button.addEventListener('keydown', (event) => {
      if (!['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      let next = index;
      if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = buttons.length - 1;
      else next = (index + (event.key === 'ArrowRight' ? -1 : 1) + buttons.length) % buttons.length;
      buttons[next].focus();
      activate(buttons[next].dataset.tab);
    });
  });

  qsa('[data-open-tab]').forEach((control) => {
    const clone = control.cloneNode(true);
    control.replaceWith(clone);
    clone.dataset.openTab = normalizeTab(clone.dataset.openTab);
    clone.addEventListener('click', (event) => {
      event.preventDefault();
      activate(clone.dataset.openTab);
      newTabbar.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });

  const workCenterLink = qsa('#clinic-sidebar a.nav-item')
    .find((link) => normalize(link.textContent) === 'مرکز کارها');
  qsa('a', document).forEach((link) => {
    if (!workCenterLink || !normalize(link.textContent).includes('پیگیری')) return;
    const href = link.getAttribute('href') || '';
    if (!href.includes('/followups')) return;
    const url = new URL(workCenterLink.href, window.location.origin);
    url.searchParams.set('view', 'all');
    const patientName = normalize(qs('#patient-name')?.textContent);
    if (patientName) url.searchParams.set('q', patientName);
    link.href = url.toString();
  });

  let compactScheduled = false;
  const syncCompactHeader = () => {
    compactScheduled = false;
    hero.classList.toggle('is-compact', window.scrollY > 150);
  };
  window.addEventListener('scroll', () => {
    if (compactScheduled) return;
    compactScheduled = true;
    window.requestAnimationFrame(syncCompactHeader);
  }, { passive: true });
  syncCompactHeader();

  const rawHash = decodeURIComponent((window.location.hash || '').replace('#', ''));
  const targetElement = rawHash ? document.getElementById(rawHash) : null;
  if (targetElement && targetElement.closest('.patient-workspace-pane')) {
    const paneName = targetElement.closest('.patient-workspace-pane').dataset.pane;
    activate(paneName, { updateHash: false });
    window.setTimeout(() => targetElement.scrollIntoView({ block: 'start' }), 0);
  } else {
    activate(rawHash || 'summary', { updateHash: rawHash === '' });
  }

  window.PatientWorkspaceV2 = Object.freeze({ activate });
})();
