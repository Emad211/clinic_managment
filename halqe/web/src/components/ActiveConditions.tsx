"use client";

/**
 * ActiveConditions — "بیماری‌های مزمن فعال" section on the patient detail page.
 *
 * فاز ۱: an optional `controlByCode` map (condition_code → control state, from
 * record.per_disease) lets us show a control status badge (ok/warn/danger + shape
 * + label) NEXT TO the disease name. When the map is absent or a code is missing
 * (older backend, or a disease with no per_disease entry), no badge is shown — the
 * section degrades to its previous markup. Colour is never the only signal.
 */

import { type ConditionDTO, type ControlDTO } from "@/lib/api";
import { formatJalali } from "@/lib/jalali";
import { CONTROL_META } from "@/lib/clinical-status";
import styles from "@/app/patients/[uuid]/record.module.css";

export function ActiveConditions({
  conditions,
  controlByCode,
}: {
  conditions: ConditionDTO[];
  /** Optional map from condition_code → control state (record.per_disease). */
  controlByCode?: Record<string, ControlDTO>;
}) {
  return (
    <section className={`${styles.card} ${styles.section}`} aria-label="بیماری‌های فعال">
      <h2 className={styles.sectionTitle}>بیماری‌های مزمن فعال</h2>
      {conditions.length === 0 ? (
        <p className={styles.emptyNote}>هیچ بیماری مزمن فعالی ثبت نشده است.</p>
      ) : (
        <ul className={styles.conditionList} aria-label="فهرست بیماری‌های فعال">
          {conditions.map((c) => {
            const control =
              c.condition_code && controlByCode
                ? controlByCode[c.condition_code]
                : undefined;
            const meta = control ? CONTROL_META[control.status] : null;
            return (
              <li key={c.id} className={styles.conditionItem}>
                <span className={styles.conditionNameRow}>
                  <span className={styles.conditionName}>
                    {c.condition_name ?? c.condition_code ?? "بیماری ثبت‌شده"}
                  </span>
                  {meta && control && (
                    <span
                      className={`${styles.statusBadge} ${styles[meta.className]}`}
                      data-status={control.status}
                      aria-label={`وضعیت کنترل: ${control.label}`}
                      data-testid={`condition-control-${c.condition_code}`}
                    >
                      <span className={styles.statusBadgeIcon} aria-hidden="true">
                        {meta.icon}
                      </span>
                      {control.label}
                    </span>
                  )}
                </span>
                <span className={styles.conditionMeta}>
                  {c.stage && `مرحله: ${c.stage} · `}
                  {c.onset_date && `شروع: ${formatJalali(c.onset_date)}`}
                  {c.notes && ` · ${c.notes}`}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
