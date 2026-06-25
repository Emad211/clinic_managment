"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useParams, usePathname } from "next/navigation";
import Link from "next/link";
import {
  apiGetRecord,
  apiGetSuggestions,
  apiCreateEncounter,
  apiAddVitals,
  apiCompleteEncounter,
  apiListEncounters,
  apiAddPrescription,
  getScreeningTimeline,
  errorMessageFromCode,
  ALLOWED_FREQUENCIES,
  ALLOWED_ROUTES,
  FREQUENCY_LABEL,
  ROUTE_LABEL,
  type ClinicalRecordDTO,
  type SuggestionsResponseDTO,
  type ScreeningTimelineResponse,
  type EncounterOut,
  type EncounterType,
  type VitalIn,
  type PrescriptionItemIn,
  type PrescriptionFrequency,
  type PrescriptionRoute,
  ApiError,
} from "@/lib/api";
import { formatJalali } from "@/lib/jalali";
import { VITAL_CATALOG, VITAL_CATALOG_MAP } from "@/lib/vital-catalog";
import { useAuth } from "@/hooks/useAuth";
import Nav from "@/components/Nav";
import { SuggestionsPanel } from "@/components/SuggestionsPanel";
import { ScreeningTimeline } from "@/components/ScreeningTimeline";
import { VerificationInbox, RecentVitalsTable } from "@/components/VitalsReview";
import { PatientCardShare } from "@/components/PatientCardShare";
import styles from "./record.module.css";

// ────────────────────────────────────────────────────────────
// Encounter helpers
// ────────────────────────────────────────────────────────────

const ENCOUNTER_TYPE_LABEL: Record<EncounterType, string> = {
  visit: "ویزیت",
  follow_up: "پیگیری",
  phone: "تلفنی",
  remote: "از راه دور",
};

const ENCOUNTER_STATUS_LABEL: Record<string, string> = {
  open: "باز",
  completed: "تکمیل‌شده",
  cancelled: "لغوشده",
};

/** Map backend error codes to human-readable Farsi messages. */
function encounterErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    // Primary path: use stable code from ApiError.code (set from backend body.code).
    if (err.code) {
      return errorMessageFromCode(err.code, `خطا: ${err.message}`);
    }
    // Fallback for older responses without a code field: status-based.
    if (err.status === 401) return "لطفاً دوباره وارد شوید.";
    if (err.status === 404) return "بیمار یا ویزیت یافت نشد.";
    if (err.status === 409) return "تعارض داده — ممکن است این ویزیت قبلاً ثبت شده باشد.";
    if (err.status === 422) return "داده‌های وارد‌شده معتبر نیستند.";
    return `خطا: ${err.message}`;
  }
  return "عملیات ناموفق بود. دوباره امتحان کنید.";
}

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

function RegisterVisitForm({
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

// ────────────────────────────────────────────────────────────
// Sub-component: recent encounters list
// ────────────────────────────────────────────────────────────

function EncountersList({
  uuid,
  refreshKey,
}: {
  uuid: string;
  refreshKey: number;
}) {
  const [encounters, setEncounters] = useState<EncounterOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    apiListEncounters(uuid, 10, 0)
      .then((resp) => {
        if (!cancelled) setEncounters(resp.items);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(
            err instanceof ApiError
              ? `خطا: ${err.message}`
              : "بارگذاری ویزیت‌ها ناموفق بود.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [uuid, refreshKey]);

  if (loading) {
    return (
      <div className={styles.encLoading} role="status" aria-live="polite">
        <span className={styles.spinner} aria-hidden="true" />
        در حال بارگذاری ویزیت‌ها…
      </div>
    );
  }

  if (error) {
    return (
      <p className={styles.encError} role="alert">{error}</p>
    );
  }

  if (encounters.length === 0) {
    return (
      <p className={styles.emptyNote}>هیچ ویزیتی ثبت نشده است.</p>
    );
  }

  return (
    <ul className={styles.encList} aria-label="فهرست ویزیت‌های اخیر">
      {encounters.map((enc) => (
        <li key={enc.id} className={styles.encItem}>
          <div className={styles.encItemRow}>
            <span className={styles.encType}>
              {ENCOUNTER_TYPE_LABEL[enc.encounter_type] ?? enc.encounter_type}
            </span>
            <span
              className={styles.encStatusBadge}
              data-status={enc.status}
              aria-label={`وضعیت: ${ENCOUNTER_STATUS_LABEL[enc.status] ?? enc.status}`}
            >
              {ENCOUNTER_STATUS_LABEL[enc.status] ?? enc.status}
            </span>
          </div>
          <div className={styles.encMeta}>
            <time dateTime={enc.encounter_at}>
              {formatJalali(enc.encounter_at)}
            </time>
            {enc.chief_complaint && (
              <span className={styles.encComplaint}>{enc.chief_complaint}</span>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}

// RuleCard and SuggestionsPanel are imported from @/components/
// (extracted for testability and reuse — see src/components/RuleCard.tsx,
// src/components/SuggestionsPanel.tsx)

// ────────────────────────────────────────────────────────────
// Main page
// ────────────────────────────────────────────────────────────

export default function PatientDetailPage() {
  const { ready, logout } = useAuth();
  const params = useParams<{ uuid: string }>();
  const pathname = usePathname();
  const uuid = params?.uuid ?? "";

  const [record, setRecord] = useState<ClinicalRecordDTO | null>(null);
  const [recordLoading, setRecordLoading] = useState(true);
  const [recordError, setRecordError] = useState<string | null>(null);

  const [suggestions, setSuggestions] = useState<SuggestionsResponseDTO | null>(null);
  const [suggestionsLoading, setSuggestionsLoading] = useState(true);
  const [suggestionsError, setSuggestionsError] = useState<string | null>(null);

  const [screeningTimeline, setScreeningTimeline] = useState<ScreeningTimelineResponse | null>(null);

  // Register-visit form visibility + encounter list refresh trigger
  const [showVisitForm, setShowVisitForm] = useState(false);
  const [encounterRefreshKey, setEncounterRefreshKey] = useState(0);

  // Fetch record
  const fetchRecord = useCallback(async () => {
    if (!uuid) return;
    setRecordLoading(true);
    setRecordError(null);
    try {
      const data = await apiGetRecord(uuid);
      setRecord(data);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setRecordError(
        err instanceof ApiError
          ? `خطا: ${err.message}`
          : "بارگذاری پرونده ناموفق بود.",
      );
    } finally {
      setRecordLoading(false);
    }
  }, [uuid, logout]);

  // Fetch suggestions (independent of record — runs in parallel)
  const fetchSuggestions = useCallback(async () => {
    if (!uuid) return;
    setSuggestionsLoading(true);
    setSuggestionsError(null);
    try {
      const data = await apiGetSuggestions(uuid);
      setSuggestions(data);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setSuggestionsError(
        err instanceof ApiError
          ? `خطا: ${err.message}`
          : "بارگذاری پیشنهادات ناموفق بود.",
      );
    } finally {
      setSuggestionsLoading(false);
    }
  }, [uuid, logout]);

  // Fetch screening timeline (independent — runs in parallel; graceful on 404/error)
  const fetchScreeningTimeline = useCallback(async () => {
    if (!uuid) return;
    try {
      const data = await getScreeningTimeline(uuid);
      setScreeningTimeline(data);
    } catch {
      // Screening timeline is supplementary — silently omit on error.
      // Backend may return 404 if no screenings are configured; that is not an error.
      setScreeningTimeline(null);
    }
  }, [uuid]);

  // Gate fetches on auth readiness
  useEffect(() => {
    if (!ready) return;
    // Fire all three requests in parallel
    fetchRecord();
    fetchSuggestions();
    fetchScreeningTimeline();
    // Stable useCallback refs; re-run only on ready change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);

  // Auth guard: render nothing while useAuth is checking/redirecting
  if (!ready) return null;

  /** Called when a visit is successfully registered: refresh both record + suggestions + encounters list. */
  function handleVisitSuccess() {
    setShowVisitForm(false);
    // Bump refresh key to re-fetch the encounters list
    setEncounterRefreshKey((k) => k + 1);
    // Also refresh the record (new vitals) and suggestions (new clinical state)
    fetchRecord();
    fetchSuggestions();
  }

  /**
   * Called after a successful verify/reject of a self-reported vital:
   * refetch the record (so the item leaves the inbox / changes state) and the
   * suggestions (an approved vital may enter the clinical engine). Does NOT
   * touch the visit form or the encounter list.
   */
  function handleVitalReviewed() {
    fetchRecord();
    fetchSuggestions();
  }

  const demo = record?.demographics;

  return (
    <div className={styles.layout}>
      <Nav
        currentPath={pathname ?? `/patients/${uuid}`}
        pageTitle={demo?.full_name ?? undefined}
        onLogout={logout}
      />

      {/* Loading state */}
      {recordLoading && (
        <main className={styles.main} id="main-content" aria-label="محتوای اصلی">
          <div className={styles.stateBox} role="status" aria-live="polite">
            <span className={styles.spinner} aria-hidden="true" />
            در حال بارگذاری پرونده…
          </div>
        </main>
      )}

      {/* Error state */}
      {!recordLoading && recordError && (
        <main className={styles.main} id="main-content">
          <div className={styles.errorBox} role="alert">
            <p>{recordError}</p>
            <button onClick={fetchRecord} className={styles.retryBtn}>
              تلاش مجدد
            </button>
          </div>
        </main>
      )}

      {/* Record loaded */}
      {!recordLoading && !recordError && record && (
        <main className={styles.main} id="main-content" aria-label="محتوای اصلی">

          {/* Patient header — spans full width */}
          <div className={`${styles.card} ${styles.patientHeader}`} role="region" aria-label="مشخصات بیمار">
            <h1 className={styles.patientName}>
              {demo?.full_name ?? "بیمار ناشناس"}
            </h1>
            <dl className={styles.patientMeta}>
              {demo?.national_id && (
                <div className={styles.metaItem}>
                  <dt className={styles.metaLabel}>کد ملی</dt>
                  <dd className={styles.metaValueMono}>{demo.national_id}</dd>
                </div>
              )}
              {demo?.phone_number && (
                <div className={styles.metaItem}>
                  <dt className={styles.metaLabel}>تلفن</dt>
                  <dd className={styles.metaValueMono}>{demo.phone_number}</dd>
                </div>
              )}
              {demo?.birthdate && (
                <div className={styles.metaItem}>
                  <dt className={styles.metaLabel}>تاریخ تولد</dt>
                  <dd className={styles.metaValue}>{formatJalali(demo.birthdate)}</dd>
                </div>
              )}
              {demo?.gender && (
                <div className={styles.metaItem}>
                  <dt className={styles.metaLabel}>جنسیت</dt>
                  <dd className={styles.metaValue}>{demo.gender}</dd>
                </div>
              )}
            </dl>
          </div>

          {/* Left column: clinical record */}
          <div className={styles.recordColumn} role="region" aria-label="پرونده بالینی">

            {/* Register visit — button + inline form */}
            <div className={styles.visitSection}>
              {!showVisitForm ? (
                <button
                  className={styles.registerVisitBtn}
                  onClick={() => setShowVisitForm(true)}
                  aria-expanded={false}
                  aria-controls="register-visit-form"
                >
                  + ثبت ویزیت
                </button>
              ) : (
                <div id="register-visit-form">
                  <RegisterVisitForm
                    uuid={uuid}
                    onSuccess={handleVisitSuccess}
                    onClose={() => setShowVisitForm(false)}
                  />
                </div>
              )}
            </div>

            {/* Active conditions */}
            <section className={`${styles.card} ${styles.section}`} aria-label="بیماری‌های فعال">
              <h2 className={styles.sectionTitle}>بیماری‌های مزمن فعال</h2>
              {record.active_conditions.length === 0 ? (
                <p className={styles.emptyNote}>هیچ بیماری مزمن فعالی ثبت نشده است.</p>
              ) : (
                <ul className={styles.conditionList} aria-label="فهرست بیماری‌های فعال">
                  {record.active_conditions.map((c) => (
                    <li key={c.id} className={styles.conditionItem}>
                      <span className={styles.conditionName}>
                        {c.condition_name ?? c.condition_code ?? "بیماری ثبت‌شده"}
                      </span>
                      <span className={styles.conditionMeta}>
                        {c.stage && `مرحله: ${c.stage} · `}
                        {c.onset_date && `شروع: ${formatJalali(c.onset_date)}`}
                        {c.notes && ` · ${c.notes}`}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {/* Active medications */}
            <section className={`${styles.card} ${styles.section}`} aria-label="داروهای فعال">
              <h2 className={styles.sectionTitle}>داروهای فعال</h2>
              {record.active_medications.length === 0 ? (
                <p className={styles.emptyNote}>هیچ دارویی ثبت نشده است.</p>
              ) : (
                <div className={styles.tableWrapper}>
                  <table className={styles.table} aria-label="لیست داروهای فعال">
                    <thead>
                      <tr>
                        <th scope="col">نام دارو</th>
                        <th scope="col">دوز</th>
                        <th scope="col">برنامه</th>
                        <th scope="col">کلاس دارویی</th>
                        <th scope="col">شروع</th>
                      </tr>
                    </thead>
                    <tbody>
                      {record.active_medications.map((m) => (
                        <tr key={m.id} className={styles.tableRow}>
                          <td style={{ fontWeight: 600 }}>{m.drug_name}</td>
                          <td>{m.dose ?? "—"}</td>
                          <td>{m.schedule ?? "—"}</td>
                          <td>{m.drug_class ?? "—"}</td>
                          <td>{m.start_date ? formatJalali(m.start_date) : "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            {/* Verification inbox — صندوقِ تأیید دادهٔ خوداظهار.
                Renders ONLY when there is at least one pending self-report
                (the component returns null otherwise — no empty section). */}
            <VerificationInbox
              vitals={record.recent_vitals}
              uuid={uuid}
              onReviewed={handleVitalReviewed}
            />

            {/* Recent vitals (three-state aware) */}
            <section className={`${styles.card} ${styles.section}`} aria-label="ویتال‌های اخیر">
              <h2 className={styles.sectionTitle}>ویتال‌های اخیر</h2>
              <RecentVitalsTable vitals={record.recent_vitals} />
            </section>

            {/* Recent encounters list */}
            <section className={`${styles.card} ${styles.section}`} aria-label="ویزیت‌های اخیر">
              <h2 className={styles.sectionTitle}>ویزیت‌های اخیر</h2>
              <EncountersList uuid={uuid} refreshKey={encounterRefreshKey} />
            </section>

            {/* Screening timeline — only render when data is available */}
            {screeningTimeline && (
              <ScreeningTimeline
                framing={screeningTimeline.framing}
                items={screeningTimeline.items}
              />
            )}

            {/* کارتِ عمومیِ بیمار — صدورِ لینک + کپی + دکمهٔ SMSِ گِیت‌شده (قدم ۴۸) */}
            <PatientCardShare uuid={uuid} />

          </div>

          {/* Right column: suggestions */}
          <div className={styles.suggestionsColumn}>
            <SuggestionsPanel
              uuid={uuid}
              suggestions={suggestions}
              suggestionsLoading={suggestionsLoading}
              suggestionsError={suggestionsError}
            />
          </div>

        </main>
      )}
    </div>
  );
}
