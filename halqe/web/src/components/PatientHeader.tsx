"use client";

/**
 * PatientHeader — full-width patient demographics card on the detail page.
 * Extracted verbatim from patients/[uuid]/page.tsx (cleanup step 9).
 * Behaviour-preserving: identical markup, identical optional-field guards,
 * identical Jalali rendering for birthdate.
 */

import { type PatientDemographics } from "@/lib/api";
import { formatJalali } from "@/lib/jalali";
import styles from "@/app/patients/[uuid]/record.module.css";

export function PatientHeader({
  demo,
}: {
  demo: PatientDemographics | null | undefined;
}) {
  return (
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
  );
}
