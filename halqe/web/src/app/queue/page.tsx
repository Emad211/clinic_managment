"use client";

/**
 * /queue — Doctor Visit Queue
 *
 * Displays today's (or a selected date's) visit queue in two sections:
 *   - «در انتظار» : waiting + in_progress entries
 *   - «انجام‌شده» : done entries
 *
 * Polls every 30 s (lightweight setInterval) and clears on unmount.
 * Polling is suspended during an in-flight start/done action; a manual
 * refetch runs immediately after each action completes.
 *
 * Auth guard: useAuth() → ready/logout pattern (same as all protected pages).
 * 401 from any API call → logout().
 */

import { useEffect, useState, useRef, useCallback } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import {
  apiGetDoctorQueue,
  apiStartVisit,
  apiMarkVisitDone,
  ApiError,
  type DoctorQueueEntry,
} from "@/lib/api";
import { formatJalali, toFarsiDigits } from "@/lib/jalali";
import { useAuth } from "@/hooks/useAuth";
import Nav from "@/components/Nav";
import styles from "./queue.module.css";

// ─────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────

function statusBadge(status: string): { label: string; cls: string } {
  if (status === "in_progress")
    return { label: "در حال ویزیت", cls: styles.badgeInProgress };
  if (status === "done") return { label: "انجام‌شده", cls: styles.badgeDone };
  return { label: "در انتظار", cls: styles.badgeWaiting };
}

// ─────────────────────────────────────────────────────────────
// Per-row busy/error state
// ─────────────────────────────────────────────────────────────

type RowState = Record<
  number,
  { busy: boolean; error: string | null; notesOpen: boolean; notes: string }
>;

// ─────────────────────────────────────────────────────────────
// Row component
// ─────────────────────────────────────────────────────────────

interface QueueRowProps {
  entry: DoctorQueueEntry;
  rs: RowState[number] | undefined;
  onStart: (invoiceId: number) => void;
  onDone: (invoiceId: number, notes: string) => void;
  onNotesToggle: (invoiceId: number) => void;
  onNotesChange: (invoiceId: number, value: string) => void;
}

function QueueRow({
  entry,
  rs,
  onStart,
  onDone,
  onNotesToggle,
  onNotesChange,
}: QueueRowProps) {
  const busy = rs?.busy ?? false;
  const rowError = rs?.error ?? null;
  const notesOpen = rs?.notesOpen ?? false;
  const notes = rs?.notes ?? "";
  const badge = statusBadge(entry.status);

  return (
    <tr className={styles.tableRow}>
      {/* Name + link to patient record */}
      <td className={styles.nameCell}>
        {entry.enrolled && entry.patient_uuid ? (
          <Link href={`/patients/${entry.patient_uuid}`}>{entry.full_name}</Link>
        ) : (
          entry.full_name
        )}
        {entry.enrolled && (
          <span className={styles.enrolledBadge} aria-label="بیمار ثبت‌شده در سیستم">
            ثبت‌شده
          </span>
        )}
      </td>

      {/* Phone */}
      <td className={styles.phoneCell} dir="ltr">
        {entry.phone_number ?? "—"}
      </td>

      {/* opened_at — when they checked in */}
      <td className={styles.monoCell}>
        {formatJalali(entry.opened_at ?? entry.work_date)}
      </td>

      {/* Status badge */}
      <td>
        <span className={`${styles.badge} ${badge.cls}`} aria-label={`وضعیت: ${badge.label}`}>
          {badge.label}
        </span>
      </td>

      {/* Action column */}
      <td className={styles.actionCell}>
        {entry.status === "waiting" && (
          <button
            type="button"
            className={styles.startBtn}
            onClick={() => onStart(entry.invoice_id)}
            disabled={busy}
            aria-label={`شروع ویزیت بیمار ${entry.full_name}`}
          >
            {busy ? "…" : "شروع ویزیت"}
          </button>
        )}

        {entry.status === "in_progress" && (
          <div className={styles.doneGroup}>
            <button
              type="button"
              className={styles.doneBtn}
              onClick={() => onNotesToggle(entry.invoice_id)}
              disabled={busy}
              aria-expanded={notesOpen}
              aria-label={`پایان ویزیت بیمار ${entry.full_name}`}
            >
              {busy ? "…" : "پایان ویزیت"}
            </button>

            {notesOpen && (
              <div className={styles.notesBox}>
                <textarea
                  className={styles.notesInput}
                  value={notes}
                  onChange={(e) =>
                    onNotesChange(entry.invoice_id, e.target.value)
                  }
                  placeholder="یادداشت پزشک (اختیاری)"
                  rows={2}
                  aria-label="یادداشت پزشک"
                />
                <button
                  type="button"
                  className={styles.confirmDoneBtn}
                  onClick={() => onDone(entry.invoice_id, notes)}
                  disabled={busy}
                >
                  تأیید پایان
                </button>
              </div>
            )}
          </div>
        )}

        {rowError && (
          <span className={styles.rowError} role="alert">
            {rowError}
          </span>
        )}
      </td>
    </tr>
  );
}

// ─────────────────────────────────────────────────────────────
// Main page
// ─────────────────────────────────────────────────────────────

const POLL_INTERVAL_MS = 30_000;

export default function QueuePage() {
  const { ready, logout } = useAuth();
  const pathname = usePathname();

  const [waiting, setWaiting] = useState<DoctorQueueEntry[]>([]);
  const [done, setDone] = useState<DoctorQueueEntry[]>([]);
  const [workDate, setWorkDate] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rowStates, setRowStates] = useState<RowState>({});

  // Guard: don't let polling interfere while an action is in-flight
  const actionInFlight = useRef(false);

  // ── Fetch ──────────────────────────────────────────────────

  const fetchQueue = useCallback(async () => {
    if (actionInFlight.current) return;
    setError(null);
    try {
      const data = await apiGetDoctorQueue();
      setWaiting(data.waiting);
      setDone(data.done);
      setWorkDate(data.work_date);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setError(
        err instanceof ApiError
          ? `خطا: ${err.message}`
          : "دریافت صف ویزیت ناموفق بود.",
      );
    } finally {
      setLoading(false);
    }
  }, [logout]);

  // ── Mount: wait for auth, then fetch + start polling ──────

  useEffect(() => {
    if (!ready) return;

    // Initial load
    fetchQueue();

    // Polling — light-weight, cleared on unmount
    const timerId = setInterval(() => {
      fetchQueue();
    }, POLL_INTERVAL_MS);

    return () => {
      clearInterval(timerId);
    };
  }, [ready, fetchQueue]);

  // ── Actions ────────────────────────────────────────────────

  async function handleStart(invoiceId: number) {
    actionInFlight.current = true;
    setRowStates((prev) => ({
      ...prev,
      [invoiceId]: {
        busy: true,
        error: null,
        notesOpen: prev[invoiceId]?.notesOpen ?? false,
        notes: prev[invoiceId]?.notes ?? "",
      },
    }));
    try {
      await apiStartVisit(invoiceId);
      setRowStates((prev) => ({
        ...prev,
        [invoiceId]: { busy: false, error: null, notesOpen: false, notes: "" },
      }));
      await fetchQueue();
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.status === 401
            ? null
            : err.message
          : "خطا در شروع ویزیت";
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setRowStates((prev) => ({
        ...prev,
        [invoiceId]: {
          busy: false,
          error: msg,
          notesOpen: prev[invoiceId]?.notesOpen ?? false,
          notes: prev[invoiceId]?.notes ?? "",
        },
      }));
    } finally {
      actionInFlight.current = false;
    }
  }

  async function handleDone(invoiceId: number, notes: string) {
    actionInFlight.current = true;
    setRowStates((prev) => ({
      ...prev,
      [invoiceId]: {
        busy: true,
        error: null,
        notesOpen: prev[invoiceId]?.notesOpen ?? false,
        notes: prev[invoiceId]?.notes ?? "",
      },
    }));
    try {
      await apiMarkVisitDone(invoiceId, notes || undefined);
      setRowStates((prev) => ({
        ...prev,
        [invoiceId]: { busy: false, error: null, notesOpen: false, notes: "" },
      }));
      await fetchQueue();
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.status === 401
            ? null
            : err.message
          : "خطا در پایان ویزیت";
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setRowStates((prev) => ({
        ...prev,
        [invoiceId]: {
          busy: false,
          error: msg,
          notesOpen: prev[invoiceId]?.notesOpen ?? true,
          notes: prev[invoiceId]?.notes ?? notes,
        },
      }));
    } finally {
      actionInFlight.current = false;
    }
  }

  function handleNotesToggle(invoiceId: number) {
    setRowStates((prev) => ({
      ...prev,
      [invoiceId]: {
        busy: prev[invoiceId]?.busy ?? false,
        error: null,
        notesOpen: !(prev[invoiceId]?.notesOpen ?? false),
        notes: prev[invoiceId]?.notes ?? "",
      },
    }));
  }

  function handleNotesChange(invoiceId: number, value: string) {
    setRowStates((prev) => ({
      ...prev,
      [invoiceId]: {
        ...(prev[invoiceId] ?? {
          busy: false,
          error: null,
          notesOpen: true,
        }),
        notes: value,
      },
    }));
  }

  // ── Render guard ───────────────────────────────────────────

  if (!ready) return null;

  // ── Render ─────────────────────────────────────────────────

  const totalWaiting = waiting.length;
  const totalDone = done.length;

  return (
    <div className={styles.layout}>
      <Nav
        currentPath={pathname ?? "/queue"}
        pageTitle="صف ویزیت"
        onLogout={logout}
      />

      <main className={styles.main} id="main-content">
        {/* Header */}
        <div className={styles.pageHeader}>
          <h1 className={styles.pageTitle}>صف ویزیت</h1>
          {workDate && (
            <span className={styles.dateBadge} aria-label={`تاریخ کاری: ${formatJalali(workDate)}`}>
              {formatJalali(workDate)}
            </span>
          )}
        </div>

        {/* Loading */}
        {loading && (
          <div className={styles.stateBox} role="status" aria-live="polite">
            <span className={styles.spinner} aria-hidden="true" />
            در حال بارگذاری…
          </div>
        )}

        {/* Error */}
        {!loading && error && (
          <div className={styles.errorBox} role="alert">
            <p>{error}</p>
            <button
              type="button"
              onClick={() => fetchQueue()}
              className={styles.retryBtn}
            >
              تلاش مجدد
            </button>
          </div>
        )}

        {/* Content — two sections */}
        {!loading && !error && (
          <>
            {/* ── Section 1: در انتظار ── */}
            <section aria-labelledby="waiting-heading" className={styles.section}>
              <h2 id="waiting-heading" className={styles.sectionTitle}>
                در انتظار
                <span className={styles.countChip}>{toFarsiDigits(totalWaiting)}</span>
              </h2>

              {totalWaiting === 0 ? (
                <div className={styles.emptyBox} role="status">
                  هیچ بیماری در صف انتظار نیست.
                </div>
              ) : (
                <div className={styles.tableWrapper}>
                  <table
                    className={styles.table}
                    aria-label="بیماران در انتظار ویزیت"
                  >
                    <thead>
                      <tr>
                        <th scope="col">بیمار</th>
                        <th scope="col">تلفن</th>
                        <th scope="col">زمان ورود</th>
                        <th scope="col">وضعیت</th>
                        <th scope="col">اقدام</th>
                      </tr>
                    </thead>
                    <tbody>
                      {waiting.map((entry) => (
                        <QueueRow
                          key={entry.invoice_id}
                          entry={entry}
                          rs={rowStates[entry.invoice_id]}
                          onStart={handleStart}
                          onDone={handleDone}
                          onNotesToggle={handleNotesToggle}
                          onNotesChange={handleNotesChange}
                        />
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            {/* ── Section 2: انجام‌شده ── */}
            <section aria-labelledby="done-heading" className={styles.section}>
              <h2 id="done-heading" className={styles.sectionTitle}>
                انجام‌شده
                <span className={styles.countChip}>{toFarsiDigits(totalDone)}</span>
              </h2>

              {totalDone === 0 ? (
                <div className={styles.emptyBox} role="status">
                  هنوز هیچ ویزیتی تکمیل نشده است.
                </div>
              ) : (
                <div className={styles.tableWrapper}>
                  <table
                    className={styles.table}
                    aria-label="ویزیت‌های انجام‌شده"
                  >
                    <thead>
                      <tr>
                        <th scope="col">بیمار</th>
                        <th scope="col">تلفن</th>
                        <th scope="col">زمان ورود</th>
                        <th scope="col">وضعیت</th>
                        <th scope="col">انجام‌دهنده</th>
                      </tr>
                    </thead>
                    <tbody>
                      {done.map((entry) => (
                        <tr key={entry.invoice_id} className={`${styles.tableRow} ${styles.tableRowDone}`}>
                          <td className={styles.nameCell}>
                            {entry.enrolled && entry.patient_uuid ? (
                              <Link href={`/patients/${entry.patient_uuid}`}>
                                {entry.full_name}
                              </Link>
                            ) : (
                              entry.full_name
                            )}
                            {entry.enrolled && (
                              <span className={styles.enrolledBadge}>ثبت‌شده</span>
                            )}
                          </td>
                          <td className={styles.phoneCell} dir="ltr">
                            {entry.phone_number ?? "—"}
                          </td>
                          <td className={styles.monoCell}>
                            {formatJalali(entry.opened_at ?? entry.work_date)}
                          </td>
                          <td>
                            <span
                              className={`${styles.badge} ${styles.badgeDone}`}
                              aria-label="وضعیت: انجام‌شده"
                            >
                              انجام‌شده
                            </span>
                          </td>
                          <td className={styles.doneByCell}>
                            {entry.done_by ?? "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </>
        )}
      </main>
    </div>
  );
}
