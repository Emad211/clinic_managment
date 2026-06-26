"use client";

/**
 * EncountersList — recent encounters list for the patient detail page.
 * Extracted verbatim from patients/[uuid]/page.tsx (cleanup step 9).
 * Behaviour-preserving: identical fetch (apiListEncounters 10/0), identical
 * loading/error/empty states, identical Jalali rendering + status badges.
 */

import { useEffect, useState } from "react";
import {
  apiListEncounters,
  ApiError,
  type EncounterOut,
} from "@/lib/api";
import { formatJalali } from "@/lib/jalali";
import {
  ENCOUNTER_TYPE_LABEL,
  ENCOUNTER_STATUS_LABEL,
} from "./encounter-labels";
import styles from "@/app/patients/[uuid]/record.module.css";

export function EncountersList({
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
