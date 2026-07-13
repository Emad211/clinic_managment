"use client";

import Link from "next/link";
import {
  type PatientDemographics,
  type ControlDTO,
  type RiskDTO,
} from "@/lib/api";
import { formatJalali, toFarsiDigits } from "@/lib/jalali";
import { CONTROL_META, RISK_META } from "@/lib/clinical-status";
import styles from "@/app/patients/[uuid]/record.module.css";

/** Identity and safety header shared by the cockpit and the full record page. */
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
        <h1 className={styles.patientName}>{demo?.full_name ?? "بیمار ناشناس"}</h1>

        {(ctrl || rsk || demo?.uuid) && (
          <div className={styles.headerBadges}>
            {ctrl && (
              <span
                className={`${styles.statusBadge} ${styles[ctrl.className]}`}
                data-status={control!.status}
                aria-label={`وضعیت کنترل: ${control!.label}`}
              >
                <span className={styles.statusBadgeIcon} aria-hidden="true">{ctrl.icon}</span>
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
                <span className={styles.statusBadgeIcon} aria-hidden="true">{rsk.icon}</span>
                خطر: {rsk.label}
                {risk!.dominant && <span className={styles.riskDominant}> · {risk!.dominant}</span>}
              </span>
            )}
            {demo?.uuid && (
              <Link
                href={`/patients/${demo.uuid}/record`}
                className={styles.registerVisitBtn}
                aria-label={`بازکردن پرونده تخصصی کامل ${demo.full_name}`}
              >
                پرونده تخصصی کامل
              </Link>
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
