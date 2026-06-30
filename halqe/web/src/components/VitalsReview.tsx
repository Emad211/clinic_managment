"use client";

/**
 * VitalsReview — خوشهٔ J، قدم ۴۷
 *
 * UIِ تأییدِ پزشک برای دادهٔ خوداظهارِ بیمار (Assert A / B / C از gp-family-medicine-advisor).
 *
 * دو بخش:
 *   1) «صندوقِ تأیید» (VerificationInbox) — یک سکشنِ مجزا بالای جدولِ ویتال‌ها که فقط
 *      آیتم‌های pendingِ خوداظهار را با دکمه‌های «تأیید»/«رد» نشان می‌دهد + شمارش.
 *      اگر هیچ pendingای نباشد، اصلاً رندر نمی‌شود (نه سکشنِ خالی).
 *   2) جدولِ ویتال‌های اخیر (RecentVitalsTable) — همان جدولِ قبلی + برچسبِ سه‌حالته:
 *      خوداظهارِ تأییدشده / ردشده / clinic عادی.
 *
 * منطقِ سه‌حالته از فیلدهای backendِ verified + rejected_at مشتق می‌شود
 * (vitalReviewState در api.ts — single source of truth).
 *
 * اصلِ ایمنی: همه فقط «پیشنهاد/کمک»؛ پزشک تصمیم می‌گیرد. هشدارِ اختلاف inline است،
 * نه مسدودکننده/popup.
 */

import { useState } from "react";
import {
  verifyVital,
  rejectVital,
  vitalReviewState,
  errorMessageFromCode,
  ApiError,
  type VitalReadingDTO,
} from "@/lib/api";
import { formatJalali, toFarsiDigits } from "@/lib/jalali";
import { VITAL_CATALOG_MAP } from "@/lib/vital-catalog";
import { vitalLevelDisplay, type VitalLevel } from "@/lib/vital-level";
import styles from "@/app/patients/[uuid]/record.module.css";

// ────────────────────────────────────────────────────────────
// Discrepancy thresholds (safety, GP)
//
// Client-side constants ONLY for an inline, non-blocking advisory hint when a
// self-reported value diverges sharply from the most-recent clinic-entered
// value of the SAME type. The physician decides — this never blocks an action.
//
// ⚠️ Source of truth for clinical thresholds is `clinical_indicators` (backend);
// these are deliberately coarse UI heuristics until that table is surfaced via API.
// ────────────────────────────────────────────────────────────

/** fbs (and other glucose-like) → relative threshold: >30% difference is "significant". */
const FBS_REL_THRESHOLD = 0.3;
/** bp_systolic → absolute threshold: >20 mmHg difference is "significant". */
const BP_SYS_ABS_THRESHOLD = 20;

/** A vital is "self-reported" when its source is exactly 'patient_self'. */
function isSelfReport(v: VitalReadingDTO): boolean {
  return v.source === "patient_self";
}

/** Persian label for a vital type, falling back to the raw key. */
function vitalLabel(type: string): string {
  return VITAL_CATALOG_MAP[type]?.label ?? type;
}

/**
 * Compute an inline discrepancy hint for a pending self-reported reading,
 * comparing it to the latest *valid clinic* reading of the same type.
 *
 * "valid clinic" = source !== 'patient_self' (i.e. clinic-entered / legacy) AND
 * not rejected. Returns a Persian hint string, or null when there is no
 * comparable clinic value or the difference is within threshold.
 *
 * `all` is the full recent_vitals list (any order); we pick the most recent by
 * measured_at among matching clinic readings.
 */
export function discrepancyHint(
  pending: VitalReadingDTO,
  all: VitalReadingDTO[],
): string | null {
  const clinicSameType = all.filter(
    (v) =>
      v.id !== pending.id &&
      v.type === pending.type &&
      !isSelfReport(v) &&
      v.rejected_at === null,
  );
  if (clinicSameType.length === 0) return null;

  // Most recent clinic reading by measured_at (ISO strings sort lexicographically).
  const latestClinic = clinicSameType.reduce((a, b) =>
    b.measured_at > a.measured_at ? b : a,
  );

  const self = pending.value;
  const clinic = latestClinic.value;

  let significant = false;
  if (pending.type === "bp_systolic") {
    significant = Math.abs(self - clinic) > BP_SYS_ABS_THRESHOLD;
  } else if (pending.type === "fbs") {
    // Relative difference vs the clinic value (guard divide-by-zero).
    if (clinic !== 0) {
      significant = Math.abs(self - clinic) / Math.abs(clinic) > FBS_REL_THRESHOLD;
    }
  }
  // Other types: no client-side heuristic yet (backend clinical_indicators is the
  // future source of truth). Return null so we don't show a noisy/false hint.
  if (!significant) return null;

  const unit = latestClinic.unit ? ` ${latestClinic.unit}` : "";
  return `اختلافِ چشمگیر با آخرین مقدارِ مطب: ${toFarsiDigits(clinic)}${unit}`;
}

// ────────────────────────────────────────────────────────────
// Verification inbox card (one pending self-report row)
// ────────────────────────────────────────────────────────────

function PendingVitalRow({
  vital,
  all,
  uuid,
  onReviewed,
}: {
  vital: VitalReadingDTO;
  all: VitalReadingDTO[];
  uuid: string;
  onReviewed: () => void;
}) {
  const [busy, setBusy] = useState<null | "verify" | "reject">(null);
  const [error, setError] = useState<string | null>(null);

  const hint = discrepancyHint(vital, all);
  const lbl = vitalLabel(vital.type);
  const unit = vital.unit ?? "";

  async function handleVerify() {
    setError(null);
    setBusy("verify");
    try {
      await verifyVital(uuid, vital.id);
      onReviewed();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        // The 'conflict' code is generic; for verify it means "already verified".
        setError("این مورد قبلاً تأیید شده است.");
      } else if (err instanceof ApiError) {
        setError(errorMessageFromCode(err.code, `خطا: ${err.message}`));
      } else {
        setError("تأیید ناموفق بود. دوباره امتحان کنید.");
      }
      setBusy(null);
    }
  }

  async function handleReject() {
    setError(null);
    setBusy("reject");
    try {
      await rejectVital(uuid, vital.id);
      onReviewed();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError("این مورد قبلاً بررسی شده است.");
      } else if (err instanceof ApiError) {
        setError(errorMessageFromCode(err.code, `خطا: ${err.message}`));
      } else {
        setError("رد ناموفق بود. دوباره امتحان کنید.");
      }
      setBusy(null);
    }
  }

  return (
    <li className={styles.pendingVitalRow} role="group" aria-label={`مورد تأییدنشده: ${lbl}`}>
      <div className={styles.pendingVitalMain}>
        <div className={styles.pendingVitalInfo}>
          <span className={styles.pendingVitalType}>{lbl}</span>
          <span className={styles.pendingVitalValue}>
            {toFarsiDigits(vital.value)}
            {unit && <span className={styles.pendingVitalUnit}> {unit}</span>}
          </span>
          <time className={styles.pendingVitalTime} dateTime={vital.measured_at}>
            {formatJalali(vital.measured_at)}
          </time>
          <span className={styles.selfReportPendingBadge}>
            خوداظهارِ بیمار — تأییدنشده
          </span>
        </div>

        <div className={styles.pendingVitalActions}>
          <button
            type="button"
            className={styles.verifyBtn}
            onClick={handleVerify}
            disabled={busy !== null}
            aria-busy={busy === "verify"}
          >
            {busy === "verify" ? "در حال تأیید…" : "تأیید"}
          </button>
          <button
            type="button"
            className={styles.rejectBtn}
            onClick={handleReject}
            disabled={busy !== null}
            aria-busy={busy === "reject"}
          >
            {busy === "reject" ? "در حال رد…" : "رد"}
          </button>
        </div>
      </div>

      {/* Inline, non-blocking discrepancy hint (safety GP) */}
      {hint && (
        <p className={styles.discrepancyHint} role="note">
          <span aria-hidden="true">⚠ </span>
          {hint}
        </p>
      )}

      {error && (
        <p className={styles.pendingVitalError} role="alert">
          {error}
        </p>
      )}
    </li>
  );
}

// ────────────────────────────────────────────────────────────
// Verification inbox (the "صندوقِ تأیید")
// ────────────────────────────────────────────────────────────

export function VerificationInbox({
  vitals,
  uuid,
  onReviewed,
}: {
  vitals: VitalReadingDTO[];
  uuid: string;
  onReviewed: () => void;
}) {
  // pending = self-reported AND state === 'pending'.
  const pending = vitals.filter(
    (v) => isSelfReport(v) && vitalReviewState(v) === "pending",
  );

  // Don't render an empty section — only show when there is something to review.
  if (pending.length === 0) return null;

  return (
    <section
      className={`${styles.card} ${styles.section} ${styles.verificationInbox}`}
      aria-label="صندوقِ تأیید دادهٔ خوداظهار"
    >
      <div className={styles.verificationInboxHeader}>
        <h2 className={styles.sectionTitle}>صندوقِ تأیید</h2>
        <span className={styles.verificationInboxCount} aria-live="polite">
          {toFarsiDigits(pending.length)} موردِ تأییدنشدهٔ خوداظهار
        </span>
      </div>
      <ul className={styles.pendingVitalList}>
        {pending.map((v) => (
          <PendingVitalRow
            key={v.id}
            vital={v}
            all={vitals}
            uuid={uuid}
            onReviewed={onReviewed}
          />
        ))}
      </ul>
    </section>
  );
}

// ────────────────────────────────────────────────────────────
// Recent vitals table (three-state aware)
// ────────────────────────────────────────────────────────────

export function RecentVitalsTable({ vitals }: { vitals: VitalReadingDTO[] }) {
  if (vitals.length === 0) {
    return <p className={styles.emptyNote}>هیچ ویتالی ثبت نشده است.</p>;
  }

  return (
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
          {vitals.map((v) => {
            const lvl = vitalLevelDisplay(v.level as VitalLevel);
            const badgeClass =
              lvl.key === "ok" ? styles.vitalLevelOk :
              lvl.key === "warn" ? styles.vitalLevelWarn :
              lvl.key === "danger" ? styles.vitalLevelDanger :
              null;

            const state = vitalReviewState(v);
            const selfReport = isSelfReport(v);
            const rejected = state === "rejected";

            return (
              <tr
                key={v.id}
                className={`${styles.tableRow}${rejected ? " " + styles.vitalRowRejected : ""}`}
              >
                <td className={styles.vitalType}>{v.type}</td>
                <td>
                  <span
                    className={styles.vitalValueCell}
                    aria-label={lvl.ariaLabel || undefined}
                  >
                    <span className={styles.vitalValue}>{toFarsiDigits(v.value)}</span>
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
                <td>
                  {/* Three-state source/review marker.
                      - self-report approved → «خوداظهارِ تأییدشده»
                      - self-report rejected → «ردشده» (dimmed row)
                      - self-report pending  → still shown in the inbox; here neutral label
                      - clinic / null        → raw source string */}
                  {selfReport && state === "approved" && (
                    <span className={styles.selfReportApprovedBadge}>
                      خوداظهارِ تأییدشده
                    </span>
                  )}
                  {rejected && (
                    <span className={styles.vitalRejectedBadge}>ردشده</span>
                  )}
                  {selfReport && state === "pending" && (
                    <span className={styles.vitalPendingMutedBadge}>
                      خوداظهار — در انتظار تأیید
                    </span>
                  )}
                  {!selfReport && (v.source ?? "—")}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
