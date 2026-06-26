"use client";

/**
 * ActiveMedications — "داروهای فعال" table on the patient detail page.
 * Extracted verbatim from patients/[uuid]/page.tsx (cleanup step 9).
 * Behaviour-preserving: identical table markup, identical empty state,
 * identical "—" fallbacks + Jalali start-date rendering.
 */

import { type MedicationDTO } from "@/lib/api";
import { formatJalali } from "@/lib/jalali";
import styles from "@/app/patients/[uuid]/record.module.css";

export function ActiveMedications({
  medications,
}: {
  medications: MedicationDTO[];
}) {
  return (
    <section className={`${styles.card} ${styles.section}`} aria-label="داروهای فعال">
      <h2 className={styles.sectionTitle}>داروهای فعال</h2>
      {medications.length === 0 ? (
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
              {medications.map((m) => (
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
  );
}
