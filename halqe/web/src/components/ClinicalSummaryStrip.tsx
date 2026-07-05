"use client";

/**
 * ClinicalSummaryStrip — the at-a-glance safety strip (فاز ۱ cockpit).
 *
 * Four mini-KPIs so a physician grasps "where is this patient?" in ~10 seconds:
 *   1. کنترل            (control state)
 *   2. خطر (+ عامل غالب) (risk tier + dominant driver)
 *   3. پیگیریِ باز       (open_followups_count)
 *   4. تجدیدِ نسخه       (refill_due_count)
 *
 * graceful fallback (قید مقدس): the whole strip renders only when at least the
 * control OR risk block is present. Individual count tiles render only when their
 * number is a real number (an older backend that omits the field → tile hidden).
 * If nothing is available the component returns null — no empty shell.
 *
 * Colour is not the only signal: each status tile carries an icon glyph + a text
 * label + an aria-label. Counts use tabular Persian digits.
 */

import {
  type ControlDTO,
  type RiskDTO,
} from "@/lib/api";
import { toFarsiDigits } from "@/lib/jalali";
import { CONTROL_META, RISK_META } from "@/lib/clinical-status";
import styles from "@/app/patients/[uuid]/record.module.css";

export interface ClinicalSummaryStripProps {
  control?: ControlDTO;
  risk?: RiskDTO;
  openFollowupsCount?: number;
  refillDueCount?: number;
}

export function ClinicalSummaryStrip({
  control,
  risk,
  openFollowupsCount,
  refillDueCount,
}: ClinicalSummaryStripProps) {
  const ctrl = control ? CONTROL_META[control.status] : null;
  const rsk = risk ? RISK_META[risk.level] : null;

  const hasFollowups = typeof openFollowupsCount === "number";
  const hasRefills = typeof refillDueCount === "number";

  // Nothing to show → render nothing (screening-timeline pattern).
  if (!ctrl && !rsk && !hasFollowups && !hasRefills) return null;

  return (
    <section
      className={styles.summaryStrip}
      aria-label="خلاصهٔ بالینی"
      data-testid="clinical-summary-strip"
    >
      {ctrl && control && (
        <div
          className={`${styles.kpiTile} ${styles[ctrl.className]}`}
          data-testid="kpi-control"
          data-status={control.status}
        >
          <span className={styles.kpiLabel}>کنترل</span>
          <span className={styles.kpiValue}>
            <span className={styles.kpiIcon} aria-hidden="true">{ctrl.icon}</span>
            <span aria-label={`وضعیت کنترل: ${control.label}`}>{control.label}</span>
          </span>
        </div>
      )}

      {rsk && risk && (
        <div
          className={`${styles.kpiTile} ${styles[rsk.className]}`}
          data-testid="kpi-risk"
          data-risk={risk.level}
        >
          <span className={styles.kpiLabel}>خطر</span>
          <span className={styles.kpiValue}>
            <span className={styles.kpiIcon} aria-hidden="true">{rsk.icon}</span>
            <span aria-label={`سطح خطر: ${rsk.label}`}>{rsk.label}</span>
          </span>
          {risk.dominant && (
            <span className={styles.kpiSub} data-testid="kpi-risk-dominant">
              عامل غالب: {risk.dominant}
            </span>
          )}
        </div>
      )}

      {hasFollowups && (
        <div
          className={`${styles.kpiTile} ${
            openFollowupsCount! > 0 ? styles.kpiTileActive : ""
          }`}
          data-testid="kpi-followups"
        >
          <span className={styles.kpiLabel}>پیگیریِ باز</span>
          <span className={styles.kpiValue}>
            <span className={styles.kpiCount}>
              {toFarsiDigits(openFollowupsCount!)}
            </span>
            <span className={styles.kpiUnit}>مورد</span>
          </span>
        </div>
      )}

      {hasRefills && (
        <div
          className={`${styles.kpiTile} ${
            refillDueCount! > 0 ? styles.kpiTileActive : ""
          }`}
          data-testid="kpi-refills"
        >
          <span className={styles.kpiLabel}>تجدیدِ نسخه</span>
          <span className={styles.kpiValue}>
            <span className={styles.kpiCount}>
              {toFarsiDigits(refillDueCount!)}
            </span>
            <span className={styles.kpiUnit}>دارو</span>
          </span>
        </div>
      )}
    </section>
  );
}
