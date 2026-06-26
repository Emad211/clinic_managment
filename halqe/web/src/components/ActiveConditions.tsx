"use client";

/**
 * ActiveConditions — "بیماری‌های مزمن فعال" section on the patient detail page.
 * Extracted verbatim from patients/[uuid]/page.tsx (cleanup step 9).
 * Behaviour-preserving: identical markup, identical empty state, identical
 * meta composition + Jalali onset rendering.
 */

import { type ConditionDTO } from "@/lib/api";
import { formatJalali } from "@/lib/jalali";
import styles from "@/app/patients/[uuid]/record.module.css";

export function ActiveConditions({
  conditions,
}: {
  conditions: ConditionDTO[];
}) {
  return (
    <section className={`${styles.card} ${styles.section}`} aria-label="بیماری‌های فعال">
      <h2 className={styles.sectionTitle}>بیماری‌های مزمن فعال</h2>
      {conditions.length === 0 ? (
        <p className={styles.emptyNote}>هیچ بیماری مزمن فعالی ثبت نشده است.</p>
      ) : (
        <ul className={styles.conditionList} aria-label="فهرست بیماری‌های فعال">
          {conditions.map((c) => (
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
  );
}
