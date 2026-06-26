"use client";

/**
 * RegisterVisitForm — inline register-visit form (encounter + vitals + free
 * prescription). Extracted verbatim from patients/[uuid]/page.tsx (cleanup
 * step 9). Behaviour-preserving: identical UI, identical create→vitals→
 * prescription→complete flow, identical validation.
 */

import { useRef, useState } from "react";
import {
  apiCreateEncounter,
  apiAddVitals,
  apiCompleteEncounter,
  apiAddPrescription,
  ALLOWED_FREQUENCIES,
  ALLOWED_ROUTES,
  FREQUENCY_LABEL,
  ROUTE_LABEL,
  type EncounterType,
  type VitalIn,
  type PrescriptionItemIn,
  type PrescriptionFrequency,
  type PrescriptionRoute,
} from "@/lib/api";
import { VITAL_CATALOG, VITAL_CATALOG_MAP } from "@/lib/vital-catalog";
import { ENCOUNTER_TYPE_LABEL, encounterErrorMessage } from "./encounter-labels";
import styles from "@/app/patients/[uuid]/record.module.css";

// ────────────────────────────────────────────────────────────
// Vital row shape used inside the form
// ────────────────────────────────────────────────────────────

interface VitalRow {
  id: number;       // local key only
  /** Canonical key from VITAL_CATALOG, or raw text when isOther=true. */
  type: string;
  value: string;    // string while typing; parsed to number on submit
  unit: string;
  /** True when the user chose «دیگر» — shows free-text type + free unit. */
  isOther: boolean;
}

// ────────────────────────────────────────────────────────────
// Prescription row shape used inside the visit form
// ────────────────────────────────────────────────────────────

interface RxRow {
  id: number;           // local key only
  drug_name: string;
  drug_class: string;
  dose_value: string;   // string while typing; parsed on submit
  dose_unit: string;
  frequency: PrescriptionFrequency | "";
  route: PrescriptionRoute | "";
  quantity: string;     // string while typing
  duration_days: string;
  instructions: string;
  /** True if the user tried to submit with this row soft-required fields empty */
  warnEmpty: boolean;
}

/** The default kind sent to the backend (no CHECK in DB — "outpatient" is conventional). */
const RX_DEFAULT_KIND = "outpatient";

/** Dose unit datalist suggestions (common; not enforced). */
const DOSE_UNIT_SUGGESTIONS = ["mg", "mcg", "g", "unit", "IU", "mL", "drop"];

// ────────────────────────────────────────────────────────────
// Sub-component: register-visit form (inline, no external modal lib)
// ────────────────────────────────────────────────────────────

export function RegisterVisitForm({
  uuid,
  onSuccess,
  onClose,
}: {
  uuid: string;
  onSuccess: () => void;
  onClose: () => void;
}) {
  const [encounterType, setEncounterType] = useState<EncounterType>("visit");
  const [chiefComplaint, setChiefComplaint] = useState("");
  const [vitals, setVitals] = useState<VitalRow[]>([
    { id: 1, type: "", value: "", unit: "", isOther: false },
  ]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const nextId = useRef(2);

  // ── Prescription state ──────────────────────────────────
  const [rxRows, setRxRows] = useState<RxRow[]>([]);
  const nextRxId = useRef(1);

  function addRxRow() {
    setRxRows((prev) => [
      ...prev,
      {
        id: nextRxId.current++,
        drug_name: "",
        drug_class: "",
        dose_value: "",
        dose_unit: "",
        frequency: "",
        route: "",
        quantity: "",
        duration_days: "",
        instructions: "",
        warnEmpty: false,
      },
    ]);
  }

  function removeRxRow(id: number) {
    setRxRows((prev) => prev.filter((r) => r.id !== id));
  }

  function updateRxRow(id: number, field: keyof Omit<RxRow, "id" | "warnEmpty">, val: string) {
    setRxRows((prev) =>
      prev.map((r) => (r.id === id ? { ...r, [field]: val, warnEmpty: false } : r)),
    );
  }

  // ────────────────────────────────────────────────────────

  function addVitalRow() {
    setVitals((prev) => [
      ...prev,
      { id: nextId.current++, type: "", value: "", unit: "", isOther: false },
    ]);
  }

  function removeVitalRow(id: number) {
    setVitals((prev) => prev.filter((r) => r.id !== id));
  }

  function updateVitalRow(id: number, field: keyof Omit<VitalRow, "id" | "isOther">, val: string) {
    setVitals((prev) =>
      prev.map((r) => (r.id === id ? { ...r, [field]: val } : r)),
    );
  }

  /**
   * Handle the vital-type <select> change.
   * - Canonical key selected: auto-fill unit (read-only), isOther=false.
   * - «دیگر» selected: clear type text, clear unit, isOther=true.
   */
  function handleVitalTypeSelect(id: number, selectedKey: string) {
    if (selectedKey === "__other__") {
      setVitals((prev) =>
        prev.map((r) =>
          r.id === id ? { ...r, type: "", unit: "", isOther: true } : r,
        ),
      );
    } else {
      const item = VITAL_CATALOG_MAP[selectedKey];
      setVitals((prev) =>
        prev.map((r) =>
          r.id === id
            ? { ...r, type: selectedKey, unit: item?.unit ?? "", isOther: false }
            : r,
        ),
      );
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    // ── Front-end prescription validation ──────────────────
    // Hard block: any rx row with empty drug_name → stop.
    const emptyDrugRows = rxRows.filter((r) => r.drug_name.trim() === "");
    if (emptyDrugRows.length > 0) {
      setRxRows((prev) =>
        prev.map((r) => (r.drug_name.trim() === "" ? { ...r, warnEmpty: true } : r)),
      );
      setError("نام دارو در یک یا چند ردیف نسخه خالی است. لطفاً وارد کنید یا ردیف را حذف کنید.");
      return;
    }
    // Hard block: quantity <= 0 or duration_days <= 0 if provided.
    const invalidNumRx = rxRows.find(
      (r) =>
        (r.quantity.trim() !== "" && (parseInt(r.quantity) <= 0 || isNaN(parseInt(r.quantity)))) ||
        (r.duration_days.trim() !== "" && (parseInt(r.duration_days) <= 0 || isNaN(parseInt(r.duration_days)))),
    );
    if (invalidNumRx) {
      setError("تعداد یا مدت مصرف باید عدد مثبت باشد.");
      return;
    }

    // Soft warning: rows with non-empty drug_name but missing route/frequency/quantity
    const softWarnRows = rxRows.filter(
      (r) =>
        r.drug_name.trim() !== "" &&
        (r.route === "" || r.frequency === "" || r.quantity.trim() === ""),
    );
    if (softWarnRows.length > 0) {
      // Mark them with warnEmpty so UI shows the inline warning
      setRxRows((prev) =>
        prev.map((r) =>
          softWarnRows.some((w) => w.id === r.id) ? { ...r, warnEmpty: true } : r,
        ),
      );
      // Soft: do NOT return — user can still submit after seeing the warning
    }

    setBusy(true);

    // Filter out blank rows; normalize type to lowercase canonical key.
    const validVitals: VitalIn[] = vitals
      .filter((r) => r.type.trim() !== "" && r.value.trim() !== "")
      .map((r) => ({
        type: r.type.trim().toLowerCase(),   // canonical key is always lowercase
        value: parseFloat(r.value),
        unit: r.unit.trim() || null,
        source: "clinic",
      }));

    // Build prescription items from non-empty rows.
    const rxItems: PrescriptionItemIn[] = rxRows
      .filter((r) => r.drug_name.trim() !== "")
      .map((r) => ({
        drug_name: r.drug_name.trim(),
        drug_class: r.drug_class.trim() || null,
        dose_value: r.dose_value.trim() !== "" ? parseFloat(r.dose_value) : null,
        dose_unit: r.dose_unit.trim() || null,
        frequency: (r.frequency as PrescriptionFrequency) || null,
        route: (r.route as PrescriptionRoute) || null,
        quantity: r.quantity.trim() !== "" ? parseInt(r.quantity, 10) : null,
        duration_days: r.duration_days.trim() !== "" ? parseInt(r.duration_days, 10) : null,
        instructions: r.instructions.trim() || null,
      }));

    try {
      // Step 1: create encounter
      const enc = await apiCreateEncounter(uuid, {
        encounter_type: encounterType,
        chief_complaint: chiefComplaint.trim() || null,
      });

      // Step 2: add vitals (batch, only if any)
      if (validVitals.length > 0) {
        await apiAddVitals(enc.id, validVitals);
      }

      // Step 3: add prescription (only if any items provided)
      if (rxItems.length > 0) {
        await apiAddPrescription(enc.id, {
          kind: RX_DEFAULT_KIND,
          items: rxItems,
          mode: "free",
        });
      }

      // Step 4: complete the encounter
      await apiCompleteEncounter(enc.id);

      setSuccess(true);
      // Brief pause so user sees success state, then close + refresh
      setTimeout(() => {
        onSuccess();
      }, 900);
    } catch (err) {
      setError(encounterErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (success) {
    return (
      <div className={styles.visitFormSuccess} role="status" aria-live="polite">
        <span className={styles.successIcon} aria-hidden="true">✓</span>
        ویزیت با موفقیت ثبت شد.
      </div>
    );
  }

  return (
    <form
      className={styles.visitForm}
      onSubmit={handleSubmit}
      aria-label="فرم ثبت ویزیت"
      noValidate
    >
      <div className={styles.visitFormHeader}>
        <h3 className={styles.visitFormTitle}>ثبت ویزیت جدید</h3>
        <button
          type="button"
          className={styles.visitFormClose}
          onClick={onClose}
          aria-label="بستن فرم ثبت ویزیت"
          disabled={busy}
        >
          ×
        </button>
      </div>

      {/* Encounter type */}
      <div className={styles.formGroup}>
        <label htmlFor="enc-type" className={styles.formLabel}>
          نوع ویزیت
        </label>
        <select
          id="enc-type"
          className={styles.formSelect}
          value={encounterType}
          onChange={(e) => setEncounterType(e.target.value as EncounterType)}
          disabled={busy}
        >
          {(Object.keys(ENCOUNTER_TYPE_LABEL) as EncounterType[]).map((t) => (
            <option key={t} value={t}>
              {ENCOUNTER_TYPE_LABEL[t]}
            </option>
          ))}
        </select>
      </div>

      {/* Chief complaint */}
      <div className={styles.formGroup}>
        <label htmlFor="chief-complaint" className={styles.formLabel}>
          شکایت اصلی
        </label>
        <textarea
          id="chief-complaint"
          className={styles.formTextarea}
          value={chiefComplaint}
          onChange={(e) => setChiefComplaint(e.target.value)}
          disabled={busy}
          rows={2}
          placeholder="شکایت اصلی بیمار را وارد کنید…"
          aria-label="شکایت اصلی بیمار"
        />
      </div>

      {/* Vitals mini-form */}
      <fieldset className={styles.vitalsFieldset} disabled={busy}>
        <legend className={styles.vitalsLegend}>اندازه‌گیری‌ها (اختیاری)</legend>

        <div className={styles.vitalsHeader} aria-hidden="true">
          <span>نوع</span>
          <span>مقدار</span>
          <span>واحد</span>
          <span />
        </div>

        {vitals.map((row) => {
          // Determine the current select value:
          //  - canonical key when isOther=false and type is non-empty
          //  - "__other__" when isOther=true
          //  - "" (placeholder) when nothing yet selected
          const selectValue = row.isOther
            ? "__other__"
            : row.type !== ""
            ? row.type
            : "";

          return (
            <div key={row.id} className={styles.vitalInputRow} role="group" aria-label="ردیف اندازه‌گیری">
              {/* ── نوع: select از کاتالوگ canonical ─── */}
              <div className={styles.vitalTypeCell}>
                <label
                  htmlFor={`vital-type-${row.id}`}
                  className={styles.srOnly}
                >
                  نوع اندازه‌گیری
                </label>
                <select
                  id={`vital-type-${row.id}`}
                  className={styles.formSelect}
                  value={selectValue}
                  onChange={(e) => handleVitalTypeSelect(row.id, e.target.value)}
                  aria-label="نوع اندازه‌گیری"
                >
                  <option value="" disabled>
                    — انتخاب کنید —
                  </option>
                  {VITAL_CATALOG.map((item) => (
                    <option key={item.key} value={item.key}>
                      {item.label}
                    </option>
                  ))}
                  <option value="__other__">دیگر…</option>
                </select>

                {/* Free-text input shown only when «دیگر» is selected */}
                {row.isOther && (
                  <input
                    className={styles.formInput}
                    type="text"
                    value={row.type}
                    onChange={(e) => updateVitalRow(row.id, "type", e.target.value)}
                    placeholder="نام اندازه‌گیری"
                    aria-label="نام اندازه‌گیری (دیگر)"
                  />
                )}
              </div>

              {/* ── مقدار ──────────────────────────── */}
              <input
                className={styles.formInput}
                type="number"
                value={row.value}
                onChange={(e) => updateVitalRow(row.id, "value", e.target.value)}
                placeholder="مقدار"
                aria-label="مقدار اندازه‌گیری"
                step="any"
                min="0"
              />

              {/* ── واحد: read-only برای canonical، آزاد برای «دیگر» ── */}
              <input
                className={styles.formInput}
                type="text"
                value={row.unit}
                onChange={(e) => updateVitalRow(row.id, "unit", e.target.value)}
                placeholder="واحد"
                aria-label="واحد اندازه‌گیری"
                readOnly={!row.isOther && row.type !== ""}
              />

              {/* ── دکمه حذف ردیف ──────────────────── */}
              <button
                type="button"
                className={styles.removeRowBtn}
                onClick={() => removeVitalRow(row.id)}
                aria-label="حذف این ردیف"
                disabled={vitals.length === 1}
              >
                −
              </button>
            </div>
          );
        })}

        <button
          type="button"
          className={styles.addRowBtn}
          onClick={addVitalRow}
          disabled={busy}
        >
          + افزودن ردیف
        </button>
      </fieldset>

      {/* ── نسخهٔ آزاد (اختیاری) ── */}
      <fieldset className={styles.prescriptionFieldset} disabled={busy}>
        <legend className={styles.prescriptionLegend}>نسخهٔ آزاد (اختیاری)</legend>

        {/* Safety framing — always visible */}
        <p className={styles.prescriptionFraming} role="note">
          این نسخه توسطِ پزشکِ معالج صادر می‌شود؛ مسئولیتِ تجویز بر عهدهٔ پزشک است.
          فقط نسخهٔ آزاد پشتیبانی می‌شود.
        </p>

        {rxRows.length > 0 && (
          <>
            {/* Column header */}
            <div className={styles.rxHeader} aria-hidden="true">
              <span>نام دارو *</span>
              <span>مسیر</span>
              <span>تناوب</span>
              <span>دوز</span>
              <span>تعداد</span>
              <span>مدت (روز)</span>
              <span />
            </div>

            {rxRows.map((row) => (
              <div key={row.id}>
                <div
                  className={styles.rxRow}
                  role="group"
                  aria-label="ردیف دارو"
                >
                  {/* ── نام دارو ── */}
                  <div>
                    <label htmlFor={`rx-drug-${row.id}`} className={styles.srOnly}>
                      نام دارو (اجباری)
                    </label>
                    <input
                      id={`rx-drug-${row.id}`}
                      className={`${styles.formInput}${row.warnEmpty && row.drug_name.trim() === "" ? " " + styles.rxFieldWarn : ""}`}
                      type="text"
                      value={row.drug_name}
                      onChange={(e) => updateRxRow(row.id, "drug_name", e.target.value)}
                      placeholder="نام دارو *"
                      aria-label="نام دارو"
                      aria-required="true"
                      autoComplete="off"
                      required
                    />
                  </div>

                  {/* ── مسیر تجویز ── */}
                  <div>
                    <label htmlFor={`rx-route-${row.id}`} className={styles.srOnly}>
                      مسیر تجویز
                    </label>
                    <select
                      id={`rx-route-${row.id}`}
                      className={`${styles.formSelect}${row.warnEmpty && row.route === "" ? " " + styles.rxFieldWarn : ""}`}
                      value={row.route}
                      onChange={(e) => updateRxRow(row.id, "route", e.target.value)}
                      aria-label="مسیر تجویز"
                    >
                      <option value="">— مسیر —</option>
                      {ALLOWED_ROUTES.map((r) => (
                        <option key={r} value={r}>
                          {ROUTE_LABEL[r]}
                        </option>
                      ))}
                    </select>
                  </div>

                  {/* ── تناوب ── */}
                  <div>
                    <label htmlFor={`rx-freq-${row.id}`} className={styles.srOnly}>
                      تناوب مصرف
                    </label>
                    <select
                      id={`rx-freq-${row.id}`}
                      className={`${styles.formSelect}${row.warnEmpty && row.frequency === "" ? " " + styles.rxFieldWarn : ""}`}
                      value={row.frequency}
                      onChange={(e) => updateRxRow(row.id, "frequency", e.target.value)}
                      aria-label="تناوب مصرف"
                    >
                      <option value="">— تناوب —</option>
                      {ALLOWED_FREQUENCIES.map((f) => (
                        <option key={f} value={f}>
                          {FREQUENCY_LABEL[f]}
                        </option>
                      ))}
                    </select>
                  </div>

                  {/* ── دوز (مقدار + واحد) ── */}
                  <div style={{ display: "flex", gap: "4px" }}>
                    <input
                      className={styles.formInput}
                      type="number"
                      value={row.dose_value}
                      onChange={(e) => updateRxRow(row.id, "dose_value", e.target.value)}
                      placeholder="دوز"
                      aria-label="مقدار دوز"
                      step="any"
                      min="0"
                      style={{ flex: 1 }}
                    />
                    <input
                      className={styles.formInput}
                      type="text"
                      list={`dose-unit-list-${row.id}`}
                      value={row.dose_unit}
                      onChange={(e) => updateRxRow(row.id, "dose_unit", e.target.value)}
                      placeholder="واحد"
                      aria-label="واحد دوز"
                      style={{ flex: 1 }}
                    />
                    <datalist id={`dose-unit-list-${row.id}`}>
                      {DOSE_UNIT_SUGGESTIONS.map((u) => (
                        <option key={u} value={u} />
                      ))}
                    </datalist>
                  </div>

                  {/* ── تعداد ── */}
                  <div>
                    <label htmlFor={`rx-qty-${row.id}`} className={styles.srOnly}>
                      تعداد
                    </label>
                    <input
                      id={`rx-qty-${row.id}`}
                      className={`${styles.formInput}${row.warnEmpty && row.quantity.trim() === "" ? " " + styles.rxFieldWarn : ""}`}
                      type="number"
                      value={row.quantity}
                      onChange={(e) => updateRxRow(row.id, "quantity", e.target.value)}
                      placeholder="تعداد"
                      aria-label="تعداد"
                      min="1"
                      step="1"
                    />
                  </div>

                  {/* ── مدت (روز) ── */}
                  <div>
                    <label htmlFor={`rx-days-${row.id}`} className={styles.srOnly}>
                      مدت مصرف (روز)
                    </label>
                    <input
                      id={`rx-days-${row.id}`}
                      className={styles.formInput}
                      type="number"
                      value={row.duration_days}
                      onChange={(e) => updateRxRow(row.id, "duration_days", e.target.value)}
                      placeholder="روز"
                      aria-label="مدت مصرف به روز"
                      min="1"
                      step="1"
                    />
                  </div>

                  {/* ── حذف ردیف ── */}
                  <button
                    type="button"
                    className={styles.removeRowBtn}
                    onClick={() => removeRxRow(row.id)}
                    aria-label="حذف این دارو"
                  >
                    −
                  </button>
                </div>

                {/* دستورالعمل مصرف (زیر هر ردیف، یک ردیف کامل) */}
                <div style={{ marginBottom: "8px" }}>
                  <input
                    className={styles.formInput}
                    type="text"
                    value={row.instructions}
                    onChange={(e) => updateRxRow(row.id, "instructions", e.target.value)}
                    placeholder="دستورالعمل مصرف (اختیاری)"
                    aria-label={`دستورالعمل مصرف داروی ردیف ${row.id}`}
                  />
                </div>

                {/* Soft warning message */}
                {row.warnEmpty && row.drug_name.trim() !== "" && (row.route === "" || row.frequency === "" || row.quantity.trim() === "") && (
                  <div className={styles.rxRowWarn} role="note">
                    مسیر، تناوب یا تعداد وارد نشده — می‌توانید ادامه دهید یا تکمیل کنید.
                  </div>
                )}
              </div>
            ))}
          </>
        )}

        <button
          type="button"
          className={styles.addRowBtn}
          onClick={addRxRow}
          disabled={busy}
        >
          + افزودن دارو
        </button>
      </fieldset>

      {/* Error */}
      {error && (
        <div className={styles.visitFormError} role="alert">
          {error}
        </div>
      )}

      {/* Actions */}
      <div className={styles.visitFormActions}>
        <button
          type="submit"
          className={styles.submitBtn}
          disabled={busy}
          aria-busy={busy}
        >
          {busy ? "در حال ثبت…" : "ثبت ویزیت"}
        </button>
        <button
          type="button"
          className={styles.cancelBtn}
          onClick={onClose}
          disabled={busy}
        >
          انصراف
        </button>
      </div>
    </form>
  );
}
