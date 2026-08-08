(() => {
  'use strict';

  const catalogNode = document.getElementById('patientWorkspaceDrugCatalog');
  const classSelect = document.getElementById('workspace-drug-class');
  const drugSelect = document.getElementById('workspace-drug-name');
  const doseInput = document.getElementById('workspace-drug-dose');
  const doseOptions = document.getElementById('workspace-drug-dose-options');

  if (!catalogNode || !classSelect || !drugSelect || !doseInput || !doseOptions) {
    return;
  }

  let catalog = [];
  try {
    const parsed = JSON.parse(catalogNode.textContent || '[]');
    catalog = Array.isArray(parsed) ? parsed : [];
  } catch (_error) {
    return;
  }

  const byName = new Map(
    catalog
      .filter((item) => item && item.generic_fa)
      .map((item) => [String(item.generic_fa), item])
  );

  function optionFor(item) {
    const option = document.createElement('option');
    option.value = String(item.generic_fa || '');
    option.textContent = String(item.generic_fa || '');
    option.dataset.drugClass = String(item.drug_class_key || '');
    return option;
  }

  function renderDrugs(classKey, selectedName) {
    const current = selectedName || drugSelect.value;
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = classKey
      ? 'انتخاب دارو از این کلاس'
      : 'انتخاب دارو از فهرست استاندارد';

    drugSelect.replaceChildren(placeholder);
    catalog
      .filter((item) => !classKey || String(item.drug_class_key || '') === classKey)
      .forEach((item) => drugSelect.appendChild(optionFor(item)));

    if (current && Array.from(drugSelect.options).some((option) => option.value === current)) {
      drugSelect.value = current;
    }
  }

  function renderDoses(item) {
    doseOptions.replaceChildren();
    const doses = item && Array.isArray(item.doses) ? item.doses : [];
    doses.forEach((dose) => {
      const option = document.createElement('option');
      option.value = String(dose);
      doseOptions.appendChild(option);
    });
  }

  function syncFromDrug() {
    const selected = byName.get(drugSelect.value);
    if (!selected) {
      renderDoses(null);
      return;
    }
    const classKey = String(selected.drug_class_key || '');
    if (classKey && classSelect.value !== classKey) {
      classSelect.value = classKey;
      renderDrugs(classKey, String(selected.generic_fa));
    }
    renderDoses(selected);
  }

  classSelect.addEventListener('change', () => {
    const classKey = classSelect.value;
    const selected = byName.get(drugSelect.value);
    const keep = selected && String(selected.drug_class_key || '') === classKey
      ? String(selected.generic_fa)
      : '';
    renderDrugs(classKey, keep);
    if (!keep) {
      doseInput.value = '';
      renderDoses(null);
    }
  });

  drugSelect.addEventListener('change', syncFromDrug);

  const initialDrug = drugSelect.value;
  renderDrugs(classSelect.value, initialDrug);
  if (initialDrug) {
    syncFromDrug();
  }
})();
