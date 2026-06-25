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
  errorMessageFromCode,
  type ClinicalRecordDTO,
  type SuggestionsResponseDTO,
  type EncounterOut,
  type EncounterType,
  type VitalIn,
  ApiError,
} from "@/lib/api";
import { formatJalali } from "@/lib/jalali";
import { vitalLevelDisplay, type VitalLevel } from "@/lib/vital-level";
import { useAuth } from "@/hooks/useAuth";
import Nav from "@/components/Nav";
import { SuggestionsPanel } from "@/components/SuggestionsPanel";
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
  type: string;
  value: string;    // string while typing; parsed to number on submit
  unit: string;
}

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
    { id: 1, type: "", value: "", unit: "" },
  ]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const nextId = useRef(2);

  function addVitalRow() {
    setVitals((prev) => [
      ...prev,
      { id: nextId.current++, type: "", value: "", unit: "" },
    ]);
  }

  function removeVitalRow(id: number) {
    setVitals((prev) => prev.filter((r) => r.id !== id));
  }

  function updateVitalRow(id: number, field: keyof Omit<VitalRow, "id">, val: string) {
    setVitals((prev) =>
      prev.map((r) => (r.id === id ? { ...r, [field]: val } : r)),
    );
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);

    // Filter out blank rows
    const validVitals: VitalIn[] = vitals
      .filter((r) => r.type.trim() !== "" && r.value.trim() !== "")
      .map((r) => ({
        type: r.type.trim(),
        value: parseFloat(r.value),
        unit: r.unit.trim() || null,
        source: "clinic",
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

      // Step 3: complete the encounter
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

        {vitals.map((row) => (
          <div key={row.id} className={styles.vitalInputRow} role="group" aria-label="ردیف اندازه‌گیری">
            <input
              className={styles.formInput}
              type="text"
              value={row.type}
              onChange={(e) => updateVitalRow(row.id, "type", e.target.value)}
              placeholder="مثال: FBS"
              aria-label="نوع اندازه‌گیری"
            />
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
            <input
              className={styles.formInput}
              type="text"
              value={row.unit}
              onChange={(e) => updateVitalRow(row.id, "unit", e.target.value)}
              placeholder="واحد"
              aria-label="واحد اندازه‌گیری"
            />
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
        ))}

        <button
          type="button"
          className={styles.addRowBtn}
          onClick={addVitalRow}
          disabled={busy}
        >
          + افزودن ردیف
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

  // Gate fetches on auth readiness
  useEffect(() => {
    if (!ready) return;
    // Fire both requests in parallel
    fetchRecord();
    fetchSuggestions();
    // fetchRecord and fetchSuggestions are stable useCallback refs; re-run only on ready change
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

            {/* Recent vitals */}
            <section className={`${styles.card} ${styles.section}`} aria-label="ویتال‌های اخیر">
              <h2 className={styles.sectionTitle}>ویتال‌های اخیر</h2>
              {record.recent_vitals.length === 0 ? (
                <p className={styles.emptyNote}>هیچ ویتالی ثبت نشده است.</p>
              ) : (
                <div className={styles.tableWrapper}>
                  <table className={styles.table} aria-label="جدول ویتال‌های اخیر">
                    <thead>
                      <tr>
                        <th scope="col">نوع</th>
                        <th scope="col">مقدار</th>
                        <th scope="col">واحد</th>
                        <th scope="col">تاریخ اندازه‌گیری</th>
                        <th scope="col">منبع</th>
                      </tr>
                    </thead>
                    <tbody>
                      {record.recent_vitals.map((v) => {
                        const lvl = vitalLevelDisplay(v.level as VitalLevel);
                        const badgeClass =
                          lvl.key === "ok" ? styles.vitalLevelOk :
                          lvl.key === "warn" ? styles.vitalLevelWarn :
                          lvl.key === "danger" ? styles.vitalLevelDanger :
                          null;
                        return (
                          <tr key={v.id} className={styles.tableRow}>
                            <td className={styles.vitalType}>{v.type}</td>
                            <td>
                              <span
                                className={styles.vitalValueCell}
                                aria-label={lvl.ariaLabel || undefined}
                              >
                                <span className={styles.vitalValue}>{v.value}</span>
                                {badgeClass && (
                                  <span
                                    className={`${styles.vitalLevelBadge} ${badgeClass}`}
                                    aria-hidden="true"
                                  >
                                    {lvl.label}
                                  </span>
                                )}
                              </span>
                            </td>
                            <td>{v.unit ?? "—"}</td>
                            <td>{formatJalali(v.measured_at)}</td>
                            <td>{v.source ?? "—"}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            {/* Recent encounters list */}
            <section className={`${styles.card} ${styles.section}`} aria-label="ویزیت‌های اخیر">
              <h2 className={styles.sectionTitle}>ویزیت‌های اخیر</h2>
              <EncountersList uuid={uuid} refreshKey={encounterRefreshKey} />
            </section>

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
