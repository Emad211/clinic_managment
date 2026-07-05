"use client";

/**
 * Allergies — safety-critical allergy surface (فاز ۱ cockpit).
 *
 * Two exports:
 *   1) AllergiesBanner — a prominent banner rendered ABOVE the tabs (outside tab
 *      content) so an allergy is NEVER hidden behind a tab. Renders ONLY when at
 *      least one allergy exists (returns null otherwise — no empty banner). Its
 *      colour + severity are safety cues: red if any severe/anaphylaxis, else amber.
 *      role="alert" so assistive tech announces it (life-safety information).
 *   2) Allergies — the full section (list + add + delete) that lives inside the
 *      «پرونده» record tab.
 *
 * Data flow (layering respected): the PAGE owns the fetch (via listAllergies) and
 * passes the array + an `onChanged` callback down. Add/delete call the API client
 * then invoke onChanged so the page refetches — no business logic in the component,
 * only request shaping + local form state.
 *
 * Colour is not the only signal: severity is shown as a text label + icon; the
 * banner leads with a warning glyph and the word «حساسیت».
 */

import { useState, type FormEvent } from "react";
import {
  addAllergy,
  deleteAllergy,
  errorMessageFromCode,
  ApiError,
  type AllergyDTO,
  type AllergySeverity,
} from "@/lib/api";
import { formatJalali } from "@/lib/jalali";
import styles from "./Allergies.module.css";

// ────────────────────────────────────────────────────────────
// Severity display metadata
// ────────────────────────────────────────────────────────────

interface SeverityMeta {
  label: string;
  className: string;
  /** True for the two danger tiers that drive the red banner. */
  danger: boolean;
}

const SEVERITY_META: Record<
  "mild" | "moderate" | "severe" | "anaphylaxis",
  SeverityMeta
> = {
  mild: { label: "خفیف", className: styles.severityMild, danger: false },
  moderate: { label: "متوسط", className: styles.severityModerate, danger: false },
  severe: { label: "شدید", className: styles.severitySevere, danger: true },
  anaphylaxis: { label: "آنافیلاکسی", className: styles.severityAnaphylaxis, danger: true },
};

const SEVERITY_UNKNOWN: SeverityMeta = {
  label: "نامشخص",
  className: styles.severityUnknown,
  danger: false,
};

function severityMeta(severity: AllergySeverity): SeverityMeta {
  if (severity && severity in SEVERITY_META) {
    return SEVERITY_META[severity as keyof typeof SEVERITY_META];
  }
  return SEVERITY_UNKNOWN;
}

/** True when any allergy in the list is a danger-tier severity. */
function hasDanger(allergies: AllergyDTO[]): boolean {
  return allergies.some((a) => severityMeta(a.severity).danger);
}

// Severity options for the <select> (empty = unspecified).
const SEVERITY_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "نامشخص" },
  { value: "mild", label: "خفیف" },
  { value: "moderate", label: "متوسط" },
  { value: "severe", label: "شدید" },
  { value: "anaphylaxis", label: "آنافیلاکسی" },
];

// ────────────────────────────────────────────────────────────
// Banner — above the tabs, only when allergies exist
// ────────────────────────────────────────────────────────────

export function AllergiesBanner({ allergies }: { allergies: AllergyDTO[] }) {
  if (!allergies || allergies.length === 0) return null;

  const danger = hasDanger(allergies);

  return (
    <div
      className={`${styles.banner} ${danger ? styles.bannerDanger : styles.bannerWarn}`}
      role="alert"
      data-testid="allergies-banner"
      data-severity={danger ? "danger" : "warn"}
    >
      <span className={styles.bannerIcon} aria-hidden="true">
        ⚠
      </span>
      <span className={styles.bannerTitle}>حساسیت‌های ثبت‌شده</span>
      <div className={styles.bannerList}>
        {allergies.map((a) => {
          const meta = severityMeta(a.severity);
          return (
            <span
              key={a.id}
              className={styles.bannerChip}
              data-testid={`allergy-chip-${a.id}`}
            >
              {a.substance}
              {a.severity && (
                <span className={styles.bannerChipSeverity}>({meta.label})</span>
              )}
            </span>
          );
        })}
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────
// Full section — list + add + delete (record tab)
// ────────────────────────────────────────────────────────────

export function Allergies({
  uuid,
  allergies,
  onChanged,
}: {
  uuid: string;
  allergies: AllergyDTO[];
  /** Called after a successful add/delete so the page refetches. */
  onChanged: () => void;
}) {
  const [substance, setSubstance] = useState("");
  const [severity, setSeverity] = useState("");
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleAdd(e: FormEvent) {
    e.preventDefault();
    const trimmed = substance.trim();
    if (!trimmed) {
      setError("نام مادهٔ حساسیت‌زا الزامی است.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await addAllergy(uuid, {
        substance: trimmed,
        severity: (severity || null) as AllergySeverity,
        note: note.trim() || null,
      });
      setSubstance("");
      setSeverity("");
      setNote("");
      onChanged();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? errorMessageFromCode(err.code, err.message)
          : "افزودن حساسیت ناموفق بود.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(id: number) {
    setDeletingId(id);
    setError(null);
    try {
      await deleteAllergy(uuid, id);
      onChanged();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? errorMessageFromCode(err.code, err.message)
          : "حذف حساسیت ناموفق بود.",
      );
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <section
      className={styles.section}
      aria-label="حساسیت‌ها"
      data-testid="allergies-section"
    >
      <h2 className={styles.sectionTitle}>حساسیت‌ها</h2>

      {allergies.length === 0 ? (
        <p className={styles.emptyNote} data-testid="allergies-empty">
          هیچ حساسیتی ثبت نشده است.
        </p>
      ) : (
        <ul className={styles.list} aria-label="فهرست حساسیت‌ها">
          {allergies.map((a) => {
            const meta = severityMeta(a.severity);
            return (
              <li
                key={a.id}
                className={`${styles.item} ${meta.danger ? styles.itemDanger : ""}`}
                data-testid={`allergy-item-${a.id}`}
              >
                <div className={styles.itemMain}>
                  <span className={styles.substance}>{a.substance}</span>
                  <span
                    className={`${styles.severityBadge} ${meta.className}`}
                    aria-label={`شدت: ${meta.label}`}
                  >
                    {meta.label}
                  </span>
                  {a.note && <span className={styles.note}>{a.note}</span>}
                </div>
                <button
                  type="button"
                  className={styles.deleteBtn}
                  onClick={() => handleDelete(a.id)}
                  disabled={deletingId === a.id}
                  aria-label={`حذف حساسیت به ${a.substance}`}
                >
                  {deletingId === a.id ? "در حال حذف…" : "حذف"}
                </button>
              </li>
            );
          })}
        </ul>
      )}

      <form className={styles.addForm} onSubmit={handleAdd}>
        <div className={`${styles.field} ${styles.fieldGrow}`}>
          <label className={styles.fieldLabel} htmlFor="allergy-substance">
            مادهٔ حساسیت‌زا
          </label>
          <input
            id="allergy-substance"
            className={styles.input}
            value={substance}
            onChange={(e) => setSubstance(e.target.value)}
            placeholder="مثلاً پنی‌سیلین"
            disabled={submitting}
          />
        </div>
        <div className={styles.field}>
          <label className={styles.fieldLabel} htmlFor="allergy-severity">
            شدت
          </label>
          <select
            id="allergy-severity"
            className={styles.select}
            value={severity}
            onChange={(e) => setSeverity(e.target.value)}
            disabled={submitting}
          >
            {SEVERITY_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
        <div className={`${styles.field} ${styles.fieldGrow}`}>
          <label className={styles.fieldLabel} htmlFor="allergy-note">
            توضیح (اختیاری)
          </label>
          <input
            id="allergy-note"
            className={styles.input}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="واکنش/توضیح"
            disabled={submitting}
          />
        </div>
        <button type="submit" className={styles.addBtn} disabled={submitting}>
          {submitting ? "در حال افزودن…" : "افزودن حساسیت"}
        </button>
        {error && (
          <p className={styles.error} role="alert">
            {error}
          </p>
        )}
      </form>
    </section>
  );
}
