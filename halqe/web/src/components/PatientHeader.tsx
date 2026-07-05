"use client";

/**
 * PatientHeader — full-width patient demographics header on the detail page.
 *
 * فاز ۱ (safety cockpit): the sticky header is now the at-a-glance identity +
 * safety strip. Beyond the original demographics (name, national_id, phone,
 * birthdate, gender) it now shows, WHEN the backend supplies them:
 *   - age (derived) inline in the meta row
 *   - a control badge (کنترل‌شده/مرزی/کنترل‌نشده/بدون داده)
 *   - a risk badge (پرخطر/متوسط/کم/پایدار) with the dominant driver
 *
 * graceful fallback (قید مقدس): control/risk are OPTIONAL. When absent (an older
 * backend), the badges are simply not rendered — the header degrades to exactly
 * its previous markup, and the page never breaks.
 *
 * Colour-is-not-the-only-signal: every badge carries a text label + an aria-label,
 * so status is legible without relying on colour alone.
 */

import {
  type PatientDemographics,
  type ControlDTO,
  type RiskDTO,
} from "@/lib/api";
import { formatJalali, toFarsiDigits } from "@/lib/jalali";
import { CONTROL_META, RISK_META } from "@/lib/clinical-status";
import styles from "@/app/patients/[uuid]/record.module.css";

export function PatientHeader({
  demo,
  control,
  risk,
}: {
  demo: PatientDemographics | null | undefined;
  control?: ControlDTO;
  risk?: RiskDTO;
}) {
  const ctrl = control ? CONTROL_META[control.status] : null;
  const rsk = risk ? RISK_META[risk.level] : null;

  return (
    <div className={`${styles.card} ${styles.patientHeader}`} role="region" aria-label="مشخصات بیمار">
      <div className={styles.patientHeaderTop}>
        <h1 className={styles.patientName}>
          {demo?.full_name ?? "بیمار ناشناس"}
        </h1>

        {/* Safety badges — rendered only when the backend supplies them */}
        {(ctrl || rsk) && (
          <div className={styles.headerBadges}>
            {ctrl && (
              <span
                className={`${styles.statusBadge} ${styles[ctrl.className]}`}
                data-status={control!.status}
                aria-label={`وضعیت کنترل: ${control!.label}`}
              >
                <span className={styles.statusBadgeIcon} aria-hidden="true">
                  {ctrl.icon}
                </span>
                کنترل: {control!.label}
              </span>
            )}
            {rsk && (
              <span
                className={`${styles.statusBadge} ${styles[rsk.className]}`}
                data-risk={risk!.level}
                aria-label={
                  `سطح خطر: ${rsk.label}` +
                  (risk!.dominant ? ` — عامل غالب: ${risk!.dominant}` : "")
                }
              >
                <span className={styles.statusBadgeIcon} aria-hidden="true">
                  {rsk.icon}
                </span>
                خطر: {rsk.label}
                {risk!.dominant && (
                  <span className={styles.riskDominant}> · {risk!.dominant}</span>
                )}
              </span>
            )}
          </div>
        )}
      </div>

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
        {typeof demo?.age === "number" && (
          <div className={styles.metaItem}>
            <dt className={styles.metaLabel}>سن</dt>
            <dd className={styles.metaValue}>{toFarsiDigits(demo.age)} سال</dd>
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
  );
}
