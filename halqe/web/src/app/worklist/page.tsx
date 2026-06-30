"use client";

import { useEffect, useState, useCallback } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import {
  apiGetWorklist,
  apiMarkDone,
  type WorklistItem,
  ApiError,
} from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";
import { formatJalali, formatToman, todayTehranISO } from "@/lib/jalali";
import Nav from "@/components/Nav";
import styles from "./worklist.module.css";

const PAGE_SIZE = 20;

// Status filter options shown to the user
const STATUS_FILTERS = [
  { value: undefined, label: "سررسیدشده / باز" },     // backend default: open + due
  { value: "open", label: "همه‌ی باز" },
  { value: "done", label: "انجام‌شده" },
  { value: "dismissed", label: "رد‌شده" },
] as const;

type FilterStatus = (typeof STATUS_FILTERS)[number]["value"];

// Per-row optimistic state after a mark-done action
type RowState = Record<number, { done: boolean; busy: boolean; error: string | null }>;

function statusBadgeClass(status: string): string {
  if (status === "done") return `${styles.badge} ${styles.badgeDone}`;
  if (status === "dismissed") return `${styles.badge} ${styles.badgeDismissed}`;
  return `${styles.badge} ${styles.badgeOpen}`;
}

function statusLabel(status: string): string {
  if (status === "done") return "انجام‌شده";
  if (status === "dismissed") return "رد‌شده";
  return "باز";
}

/**
 * A task is "overdue" only when it is still open AND its due date is strictly
 * before today (Tehran). Done/dismissed tasks are never flagged — they are
 * resolved, not pending triage. ISO YYYY-MM-DD strings compare lexicographically,
 * so `<` is a correct date comparison (and we use Tehran's "today", not UTC).
 *
 * Triage safety (GP): a follow-up that is months overdue must look different
 * from one due today, so a frail/elderly patient does not slip through.
 */
function isOverdue(status: string, dueDate: string | null): boolean {
  if (status !== "open") return false;
  if (!dueDate) return false;
  return dueDate < todayTehranISO();
}

export default function WorklistPage() {
  const { ready, logout } = useAuth();
  const pathname = usePathname();

  const [items, setItems] = useState<WorklistItem[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [filterStatus, setFilterStatus] = useState<FilterStatus>(undefined);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Per-row optimistic state
  const [rowStates, setRowStates] = useState<RowState>({});

  const fetchPage = useCallback(
    async (pageOffset: number, status: FilterStatus) => {
      setLoading(true);
      setError(null);
      try {
        const data = await apiGetWorklist({
          status,
          limit: PAGE_SIZE,
          offset: pageOffset,
        });
        setItems(data.items);
        setTotal(data.total);
        // Reset per-row state on each page load
        setRowStates({});
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          logout();
          return;
        }
        setError(
          err instanceof ApiError
            ? `خطا: ${err.message}`
            : "دریافت لیست پیگیری‌ها ناموفق بود.",
        );
      } finally {
        setLoading(false);
      }
    },
    [logout],
  );

  // Fire initial fetch only once the auth guard has confirmed a valid token
  useEffect(() => {
    if (!ready) return;
    fetchPage(0, filterStatus);
  // Run only on mount (after ready) — filter changes handled by handleFilterChange
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);

  function handleFilterChange(status: FilterStatus) {
    if (status === filterStatus) return;
    setFilterStatus(status);
    setOffset(0);
    fetchPage(0, status);
  }

  function handlePrev() {
    const newOffset = Math.max(0, offset - PAGE_SIZE);
    setOffset(newOffset);
    fetchPage(newOffset, filterStatus);
  }

  function handleNext() {
    const newOffset = offset + PAGE_SIZE;
    if (newOffset < total) {
      setOffset(newOffset);
      fetchPage(newOffset, filterStatus);
    }
  }

  async function handleMarkDone(taskId: number) {
    // Optimistically mark busy
    setRowStates((prev) => ({
      ...prev,
      [taskId]: { done: false, busy: true, error: null },
    }));
    try {
      await apiMarkDone(taskId);
      // Optimistically flip to done
      setRowStates((prev) => ({
        ...prev,
        [taskId]: { done: true, busy: false, error: null },
      }));
    } catch (err) {
      let msg = "خطا در ثبت";
      if (err instanceof ApiError) {
        if (err.status === 404) msg = "تسک یافت نشد";
        else if (err.status === 409) msg = "قبلاً انجام شده";
        else if (err.status === 401) {
          logout();
          return;
        } else {
          msg = err.message;
        }
      }
      setRowStates((prev) => ({
        ...prev,
        [taskId]: { done: false, busy: false, error: msg },
      }));
    }
  }

  // Auth guard: render nothing while useAuth is checking/redirecting
  if (!ready) return null;

  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  // Show the revenue column only when the backend returned at least one non-null
  // revenue value — which only happens for MANAGER users (backend-enforced gate).
  const hasRevenue = items.some((item) => item.revenue != null);

  return (
    <div className={styles.layout}>
      <Nav
        currentPath={pathname ?? "/worklist"}
        pageTitle="لیست پیگیری‌ها"
        onLogout={logout}
      />

      <main className={styles.main} id="main-content">
        <div className={styles.pageHeader}>
          <h1 className={styles.pageTitle}>لیست پیگیری‌ها</h1>
          {!loading && !error && (
            <span className={styles.totalBadge}>مجموع: {total}</span>
          )}
          {/* Status filter buttons */}
          <div className={styles.toolbar} role="group" aria-label="فیلتر وضعیت">
            <span className={styles.filterLabel}>وضعیت:</span>
            {STATUS_FILTERS.map(({ value, label }) => (
              <button
                key={String(value)}
                type="button"
                onClick={() => handleFilterChange(value)}
                className={
                  filterStatus === value
                    ? `${styles.filterBtn} ${styles.filterBtnActive}`
                    : styles.filterBtn
                }
                aria-pressed={filterStatus === value}
              >
                {label}
              </button>
            ))}
          </div>
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
              onClick={() => fetchPage(offset, filterStatus)}
              className={styles.retryBtn}
            >
              تلاش مجدد
            </button>
          </div>
        )}

        {/* Empty */}
        {!loading && !error && items.length === 0 && (
          <div className={styles.stateBox} role="status">
            هیچ پیگیری‌ای در این وضعیت وجود ندارد.
          </div>
        )}

        {/* Table */}
        {!loading && !error && items.length > 0 && (
          <>
            <div className={styles.tableWrapper}>
              <table className={styles.table} aria-label="لیست پیگیری‌های بیماران">
                <thead>
                  <tr>
                    <th scope="col">بیمار</th>
                    <th scope="col">نوع پیگیری</th>
                    <th scope="col">تاریخ سررسید</th>
                    <th scope="col">وضعیت</th>
                    {hasRevenue && (
                      <th scope="col" className={styles.revenueCell}>درآمد</th>
                    )}
                    <th scope="col">اقدام</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => {
                    const rs = rowStates[item.id];
                    const isDone = rs?.done || item.status === "done" || item.status === "dismissed";
                    const isBusy = rs?.busy ?? false;
                    const rowError = rs?.error ?? null;
                    const effectiveStatus = rs?.done ? "done" : item.status;

                    return (
                      <tr
                        key={item.id}
                        className={
                          isDone
                            ? `${styles.tableRow} ${styles.tableRowDone}`
                            : styles.tableRow
                        }
                      >
                        {/* Patient name — link to patient card if uuid available */}
                        <td className={styles.nameCell}>
                          {item.patient_uuid ? (
                            <Link href={`/patients/${item.patient_uuid}`}>
                              {item.patient_full_name ?? "بیمار ناشناس"}
                            </Link>
                          ) : (
                            item.patient_full_name ?? (
                              <span className="text-muted">بیمار ناشناس</span>
                            )
                          )}
                        </td>

                        {/* Reason / kind */}
                        <td>{item.reason ?? item.kind ?? "—"}</td>

                        {/* Due date via Jalali stub; flag overdue open tasks */}
                        <td className={styles.monoCell}>
                          {formatJalali(item.due_date)}
                          {isOverdue(effectiveStatus, item.due_date) && (
                            <span className={styles.overdue} role="status">
                              <span aria-hidden="true">⚠ </span>
                              سررسید گذشته
                            </span>
                          )}
                        </td>

                        {/* Status badge */}
                        <td>
                          <span
                            className={statusBadgeClass(effectiveStatus)}
                            aria-label={`وضعیت: ${statusLabel(effectiveStatus)}`}
                          >
                            {statusLabel(effectiveStatus)}
                          </span>
                        </td>

                        {/* Revenue — manager-only column; only rendered when hasRevenue */}
                        {hasRevenue && (
                          <td
                            className={styles.revenueCell}
                            aria-label={
                              item.revenue != null
                                ? `درآمد: ${formatToman(item.revenue)}`
                                : "درآمد: ندارد"
                            }
                          >
                            {item.revenue != null ? formatToman(item.revenue) : "—"}
                          </td>
                        )}

                        {/* Mark-done action — only for open, not-yet-flipped rows */}
                        <td>
                          {!isDone && (
                            <>
                              <button
                                type="button"
                                className={styles.doneBtn}
                                onClick={() => handleMarkDone(item.id)}
                                disabled={isBusy}
                                aria-label={`انجام شد: پیگیری بیمار ${item.patient_full_name ?? item.id}`}
                              >
                                {isBusy ? "…" : "انجام شد"}
                              </button>
                              {rowError && (
                                <span className={styles.rowError} role="alert">
                                  {rowError}
                                </span>
                              )}
                            </>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            <nav className={styles.pagination} aria-label="صفحه‌بندی پیگیری‌ها">
              <button
                onClick={handleNext}
                disabled={offset + PAGE_SIZE >= total}
                className={styles.pageBtn}
                aria-label="صفحه بعد"
              >
                بعدی
              </button>
              <span className={styles.pageInfo} aria-live="polite">
                صفحهٔ {currentPage} از {totalPages}
              </span>
              <button
                onClick={handlePrev}
                disabled={offset === 0}
                className={styles.pageBtn}
                aria-label="صفحه قبل"
              >
                قبلی
              </button>
            </nav>
          </>
        )}
      </main>
    </div>
  );
}
