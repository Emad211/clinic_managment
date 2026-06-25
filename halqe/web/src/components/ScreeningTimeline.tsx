/**
 * ScreeningTimeline — سکشنِ تقویمِ غربالگری در پروندهٔ بیمار.
 *
 * ویژگی‌ها:
 *   - suggestion-only: یادآور است نه دستور؛ همیشه framing را نشان می‌دهد.
 *   - ترتیبِ آیتم‌ها از سرور حفظ می‌شود (never_done/overdue اول).
 *   - items=[] → state خالیِ تمیز.
 *   - null در last_done_at / next_due_at بدونِ crash مدیریت می‌شود.
 *   - رقمِ فارسی برای اعداد از toFarsiDigits.
 */

"use client";

import { type ScreeningItem, type ScreeningStatus } from "@/lib/api";
import { formatJalali, toFarsiDigits } from "@/lib/jalali";
import styles from "./ScreeningTimeline.module.css";

// ────────────────────────────────────────────────────────────
// Status metadata
// ────────────────────────────────────────────────────────────

const STATUS_LABEL: Record<ScreeningStatus, string> = {
  never_done: "هرگز انجام نشده",
  overdue: "گذشته",
  due_soon: "نزدیک به موعد",
  ok: "به‌موقع",
};

const STATUS_CLASS: Record<ScreeningStatus, string> = {
  never_done: styles.statusNeverDone,
  overdue: styles.statusOverdue,
  due_soon: styles.statusDueSoon,
  ok: styles.statusOk,
};

// ────────────────────────────────────────────────────────────
// Single item row
// ────────────────────────────────────────────────────────────

function ScreeningRow({ item }: { item: ScreeningItem }) {
  const statusLabel = STATUS_LABEL[item.status] ?? item.status;
  const statusClass = STATUS_CLASS[item.status] ?? "";
  const lastDone = item.last_done_at ? formatJalali(item.last_done_at) : "هرگز";
  const nextDue = item.next_due_at ? formatJalali(item.next_due_at) : "—";

  return (
    <li
      className={`${styles.item} ${item.status === "never_done" ? styles.itemNeverDone : ""}`}
      data-status={item.status}
      aria-label={`${item.label_fa}: وضعیت ${statusLabel}`}
    >
      <div className={styles.itemHeader}>
        <span className={styles.itemLabel}>{item.label_fa}</span>
        <span
          className={`${styles.statusBadge} ${statusClass}`}
          aria-label={`وضعیتِ غربالگری: ${statusLabel}`}
          data-testid={`screening-status-${item.item_key}`}
        >
          {statusLabel}
        </span>
      </div>

      <dl className={styles.itemMeta}>
        <div className={styles.metaRow}>
          <dt className={styles.metaKey}>آخرین انجام</dt>
          <dd
            className={`${styles.metaVal} ${item.last_done_at === null ? styles.metaValNever : ""}`}
            data-testid={`screening-last-${item.item_key}`}
          >
            {lastDone}
          </dd>
        </div>
        <div className={styles.metaRow}>
          <dt className={styles.metaKey}>سررسیدِ بعدی</dt>
          <dd
            className={styles.metaVal}
            data-testid={`screening-next-${item.item_key}`}
          >
            {nextDue}
          </dd>
        </div>
        <div className={styles.metaRow}>
          <dt className={styles.metaKey}>فاصلهٔ توصیه‌شده</dt>
          <dd className={styles.metaVal}>
            {toFarsiDigits(item.interval_months)} ماه
          </dd>
        </div>
      </dl>
    </li>
  );
}

// ────────────────────────────────────────────────────────────
// Main export
// ────────────────────────────────────────────────────────────

export interface ScreeningTimelineProps {
  framing: string;
  items: ScreeningItem[];
}

export function ScreeningTimeline({ framing, items }: ScreeningTimelineProps) {
  // Empty state: render a clean note, not an error
  if (items.length === 0) {
    return (
      <section
        className={styles.section}
        aria-label="تقویمِ غربالگری"
        data-testid="screening-timeline-section"
      >
        <div className={styles.sectionHeader}>
          <h2 className={styles.sectionTitle}>تقویمِ غربالگری</h2>
          <span className={styles.suggestionOnlyChip} aria-hidden="true">
            پیشنهاد
          </span>
        </div>
        <div className={styles.framingBanner} role="note">
          <span className={styles.framingIcon} aria-hidden="true">!</span>
          {framing}
        </div>
        <p className={styles.emptyNote} data-testid="screening-empty">
          هیچ برنامهٔ غربالگری‌ای برای بیماری‌های ثبت‌شده پیکربندی نشده است.
        </p>
      </section>
    );
  }

  return (
    <section
      className={styles.section}
      aria-label="تقویمِ غربالگری"
      data-testid="screening-timeline-section"
    >
      <div className={styles.sectionHeader}>
        <h2 className={styles.sectionTitle}>تقویمِ غربالگری</h2>
        <span className={styles.suggestionOnlyChip} aria-hidden="true">
          پیشنهاد
        </span>
      </div>

      {/* Framing banner — suggestion-only; always shown when items present */}
      <div
        className={styles.framingBanner}
        role="note"
        aria-label="این سکشن فقط یادآور است، نه دستور"
      >
        <span className={styles.framingIcon} aria-hidden="true">!</span>
        {framing}
      </div>

      {/* Item list — server order preserved */}
      <ul
        className={styles.list}
        aria-label="فهرستِ برنامه‌های غربالگری"
        data-testid="screening-list"
      >
        {items.map((item) => (
          <ScreeningRow key={item.item_key} item={item} />
        ))}
      </ul>
    </section>
  );
}
