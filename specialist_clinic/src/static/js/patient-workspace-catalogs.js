(() => {
  'use strict';

  const qs = (selector, root = document) => root.querySelector(selector);

  function parseJson(script) {
    if (!script) return [];
    try {
      const value = JSON.parse(script.textContent || '[]');
      return Array.isArray(value) ? value : [];
    } catch (_) {
      return [];
    }
  }

  function setupMedicationForm(form) {
    const catalog = parseJson(qs('[data-drug-catalog-json]', form));
    const byId = new Map(catalog.map((item) => [String(item.id), item]));
    const drugSelect = qs('[data-drug-catalog-select]', form);
    const doseSelect = qs('[data-drug-dose-select]', form);
    const customField = qs('[data-custom-dose-field]', form);
    const customInput = qs('[data-custom-dose-input]', form);
    const help = qs('[data-drug-class-help]', form);
    if (!drugSelect || !doseSelect || !customField || !customInput) return;

    const restoreValue = doseSelect.dataset.restoreValue || '';

    function syncCustomField() {
      const custom = doseSelect.value === '__custom__';
      customField.hidden = !custom;
      customInput.required = custom;
      if (custom) customInput.focus({ preventScroll: true });
    }

    function renderDoses({ restore = false } = {}) {
      const item = byId.get(drugSelect.value);
      const previous = restore ? restoreValue : '';
      doseSelect.replaceChildren();

      const placeholder = document.createElement('option');
      placeholder.value = '';
      placeholder.textContent = item ? 'انتخاب دوز' : 'ابتدا دارو را انتخاب کنید';
      doseSelect.appendChild(placeholder);

      if (item) {
        const doses = Array.isArray(item.doses) ? item.doses : [];
        doses.forEach((dose) => {
          const option = document.createElement('option');
          option.value = String(dose);
          option.textContent = String(dose);
          doseSelect.appendChild(option);
        });
        const custom = document.createElement('option');
        custom.value = '__custom__';
        custom.textContent = doses.length ? 'دوز دیگر…' : 'ورود دوز';
        doseSelect.appendChild(custom);

        const selectedOption = drugSelect.options[drugSelect.selectedIndex];
        const classLabel = selectedOption?.parentElement?.label || item.drug_class_key || '';
        if (help) {
          help.textContent = `${item.generic_fa}${classLabel ? ` · ${classLabel}` : ''}`;
        }
      } else if (help) {
        help.textContent = 'نام و کلاس دارو از فهرست رسمی ثبت می‌شود.';
      }

      if (previous && Array.from(doseSelect.options).some((option) => option.value === previous)) {
        doseSelect.value = previous;
      } else if (item && (!Array.isArray(item.doses) || item.doses.length === 0)) {
        doseSelect.value = '__custom__';
      }
      syncCustomField();
    }

    drugSelect.addEventListener('change', () => renderDoses());
    doseSelect.addEventListener('change', syncCustomField);
    renderDoses({ restore: true });
  }

  function setupLabForm(form) {
    const select = qs('[data-lab-catalog-select]', form);
    const help = qs('[data-lab-catalog-help]', form);
    if (!select || !help) return;

    function sync() {
      const option = select.options[select.selectedIndex];
      if (!option || !option.value) {
        help.textContent = 'واحد و محدوده مرجع پس از انتخاب نمایش داده می‌شود.';
        return;
      }
      const unit = option.dataset.unit || 'بدون واحد';
      const low = option.dataset.refLow || '';
      const high = option.dataset.refHigh || '';
      let reference = 'محدوده مرجع ثبت نشده';
      if (low || high) reference = `${low || '—'} تا ${high || '—'}`;
      help.textContent = `واحد: ${unit} · محدوده مرجع: ${reference}`;
    }

    select.addEventListener('change', sync);
    sync();
  }

  function setupAcquisitionForm(form) {
    const source = qs('[data-acquisition-source]', form);
    const patientField = qs('[data-acquisition-patient-referrer]', form);
    const patientSelect = qs('[data-acquisition-referrer-select]', form);
    const freeField = qs('[data-acquisition-free-referrer]', form);
    const freeInput = freeField?.querySelector('input');
    if (!source || !patientField || !patientSelect || !freeField || !freeInput) return;

    function sync() {
      const patientReferral = source.value === 'PATIENT_REFERRAL';
      const doctorReferral = source.value === 'DOCTOR_REFERRAL';
      patientField.hidden = !patientReferral;
      patientSelect.disabled = !patientReferral;
      patientSelect.required = patientReferral;
      freeField.hidden = patientReferral || !doctorReferral;
      freeInput.disabled = patientReferral || !doctorReferral;
      freeInput.required = doctorReferral;
    }

    source.addEventListener('change', sync);
    sync();
  }

  function setup() {
    document.querySelectorAll('[data-catalog-medication-form]').forEach(setupMedicationForm);
    document.querySelectorAll('[data-catalog-lab-form]').forEach(setupLabForm);
    document.querySelectorAll('[data-acquisition-form]').forEach(setupAcquisitionForm);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setup, { once: true });
  } else {
    setup();
  }
})();
