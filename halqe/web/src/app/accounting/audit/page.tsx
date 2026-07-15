"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname } from "next/navigation";

import Nav from "@/components/Nav";
import { useAuth } from "@/hooks/useAuth";
import { ApiError } from "@/lib/api";
import {
  apiGetAccountingAuditLogs,
  type AccountingAuditFilters,
  type AccountingAuditSearchDTO,
} from "@/lib/api/accounting-audit";
import { formatJalali, formatToman, toFarsiDigits } from "@/lib/jalali";
import styles from "./audit.module.css";


type FilterState = {
  dateFrom: string;
  dateTo: string;
  userId: string;
  actionType: string;
  actionCategory: string;
  invoiceId: string;
  patientId: string;
  searchText: string;
  pageSize: string;
};

const ACTION_LABELS: Record<string, string> = {
  login: "ورود",
  logout: "خروج",
  patient_create: "ایجاد بیمار",
  patient_update: "ویرایش بیمار",
  invoice_create: "ایجاد فاکتور",
  invoice_open: "بازکردن فاکتور",
  invoice_close: "بستن فاکتور",
  invoice_view: "مشاهده فاکتور",
  visit_add: "ثبت ویزیت",
  visit_delete: "حذف ویزیت",
  injection_add: "ثبت تزریق",
  injection_delete: "حذف تزریق",
  procedure_add: "ثبت پروسیجر",
  procedure_delete: "حذف پروسیجر",
  consumable_use: "ثبت مصرفی",
  consumable_delete: "حذف مصرفی",
  item_payment_set: "تغییر پرداخت",
  payroll_settings_upsert: "تنظیم قرارداد حقوق",
  shift_staff_set: "تنظیم کادر شیفت",
};

const CATEGORY_LABELS: Record<string, string> = {
  auth: "احراز هویت",
  patient: "بیمار",
  invoice: "فاکتور",
  visit: "ویزیت",
  injection: "تزریق",
  nursing: "پرستاری",
  procedure: "پروسیجر",
  consumable: "مصرفی",
  shift: "شیفت",
  print: "چاپ",
  report: "گزارش",
  configuration: "تنظیمات",
};

function iso(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function defaults(): FilterState {
  const end = new Date();
  const start = new Date(end);
  start.setDate(end.getDate() - 29);
  return {
    dateFrom: iso(start),
    dateTo: iso(end),
    userId: "",
    actionType: "",
    actionCategory: "",
    invoiceId: "",
    patientId: "",
    searchText: "",
    pageSize: "50",
  };
}

function toQuery(filters: FilterState, page: number): AccountingAuditFilters {
  return {
    date_from: filters.dateFrom,
    date_to: filters.dateTo,
    page,
    page_size: Number(filters.pageSize),
    user_id: filters.userId ? Number(filters.userId) : null,
    action_type: filters.actionType,
    action_category: filters.actionCategory,
    invoice_id: filters.invoiceId ? Number(filters.invoiceId) : null,
    patient_id: filters.patientId ? Number(filters.patientId) : null,
    search_text: filters.searchText,
  };
}

function dateTime(value: string): string {
  const time = new Date(value).toLocaleTimeString("fa-IR", {
    hour: "2-digit",
    minute: "2-digit",
  });
  return `${formatJalali(value)} · ${time}`;
}

function csvCell(value: unknown): string {
  return `"${String(value ?? "").replaceAll('"', '""')}"`;
}

function exportCsv(data: AccountingAuditSearchDTO) {
  const rows = data.rows.map((row) => [
    dateTime(row.created_at),
    row.user_full_name,
    ACTION_LABELS[row.action_type] ?? row.action_type,
    CATEGORY_LABELS[row.action_category] ?? row.action_category,
    row.description ?? "",
    row.target_name ?? row.target_type ?? "",
    row.invoice_id ?? "",
    row.patient_name ?? "",
    row.amount,
    row.old_value ?? "",
    row.new_value ?? "",
    row.ip_address ?? "",
  ]);
  const headers = [
    "زمان", "کاربر", "عملیات", "دسته", "توضیح", "هدف", "فاکتور",
    "بیمار", "مبلغ", "مقدار قبلی", "مقدار جدید", "IP",
  ];
  const content = [headers, ...rows]
    .map((row) => row.map(csvCell).join(","))
    .join("\r\n");
  const blob = new Blob(["\ufeff", content], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `halqe-accounting-audit-page-${data.page}.csv`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export default function AccountingAuditPage() {
  const { ready, logout } = useAuth();
  const pathname = usePathname();
  const [draft, setDraft] = useState<FilterState>(defaults);
  const [filters, setFilters] = useState<FilterState>(defaults);
  const [page, setPage] = useState(1);
  const [data, setData] = useState<AccountingAuditSearchDTO | null>(null);
  const [loading, setLoading] = useState(true);
  const [accessDenied, setAccessDenied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await apiGetAccountingAuditLogs(toQuery(filters, page));
      setData(response);
      setAccessDenied(false);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      if (err instanceof ApiError && err.status === 403) {
        setAccessDenied(true);
        return;
      }
      setError(
        err instanceof ApiError
          ? err.message
          : "دریافت رویدادهای حسابداری ناموفق بود.",
      );
    } finally {
      setLoading(false);
    }
  }, [filters, logout, page]);

  useEffect(() => {
    if (ready) void load();
  }, [ready, load]);

  const pages = useMemo(() => {
    const total = data?.total_pages ?? 0;
    if (total <= 1) return [];
    const start = Math.max(1, Math.min(page - 2, total - 4));
    return Array.from({ length: Math.min(5, total) }, (_, index) => start + index);
  }, [data?.total_pages, page]);

  function applyFilters() {
    setPage(1);
    setFilters({ ...draft });
  }

  function resetFilters() {
    const next = defaults();
    setDraft(next);
    setPage(1);
    setFilters(next);
  }

  if (!ready) return null;

  return (
    <div className={styles.layout}>
      <Nav
        currentPath={pathname ?? "/accounting/audit"}
        pageTitle="ردپای عملیات"
        onLogout={logout}
      />
      <main className={styles.main} id="main-content">
        <header className={styles.hero}>
          <div>
            <span className={styles.eyebrow}>ACCOUNTABILITY LEDGER</span>
            <h1>بازبینی رویدادهای حسابداری</h1>
            <p>
              جست‌وجوی فقط‌خواندنی عملیات مالی، تغییرات، کاربر، فاکتور و بیمار؛
              مرتب‌شده بر اساس زمان و محدود به tenant جاری.
            </p>
          </div>
          <div className={styles.heroStat}>
            <span>نتیجهٔ فیلتر</span>
            <strong>{toFarsiDigits(data?.total ?? 0)}</strong>
            <small>رویداد</small>
          </div>
        </header>

        {accessDenied && (
          <section className={styles.alert} role="alert">
            بازبینی رویدادها فقط برای مدیر یا ادمین قابل دسترسی است.
          </section>
        )}
        {error && <section className={styles.alert} role="alert">{error}</section>}

        {!accessDenied && (
          <>
            <section className={styles.filters} aria-label="فیلتر رویدادهای حسابداری">
              <label>
                از تاریخ
                <input
                  type="date"
                  value={draft.dateFrom}
                  onChange={(event) => setDraft((item) => ({ ...item, dateFrom: event.target.value }))}
                />
              </label>
              <label>
                تا تاریخ
                <input
                  type="date"
                  value={draft.dateTo}
                  onChange={(event) => setDraft((item) => ({ ...item, dateTo: event.target.value }))}
                />
              </label>
              <label>
                کاربر
                <select
                  value={draft.userId}
                  onChange={(event) => setDraft((item) => ({ ...item, userId: event.target.value }))}
                >
                  <option value="">همه کاربران</option>
                  {data?.filter_options.users.map((user) => (
                    <option key={`${user.user_id ?? "system"}-${user.username}`} value={user.user_id ?? ""}>
                      {user.full_name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                نوع عملیات
                <select
                  value={draft.actionType}
                  onChange={(event) => setDraft((item) => ({ ...item, actionType: event.target.value }))}
                >
                  <option value="">همه عملیات</option>
                  {data?.filter_options.action_types.map((value) => (
                    <option key={value} value={value}>{ACTION_LABELS[value] ?? value}</option>
                  ))}
                </select>
              </label>
              <label>
                دسته
                <select
                  value={draft.actionCategory}
                  onChange={(event) => setDraft((item) => ({ ...item, actionCategory: event.target.value }))}
                >
                  <option value="">همه دسته‌ها</option>
                  {data?.filter_options.action_categories.map((value) => (
                    <option key={value} value={value}>{CATEGORY_LABELS[value] ?? value}</option>
                  ))}
                </select>
              </label>
              <label>
                شماره فاکتور
                <input
                  inputMode="numeric"
                  value={draft.invoiceId}
                  onChange={(event) => setDraft((item) => ({ ...item, invoiceId: event.target.value }))}
                  placeholder="مثلاً ۱۲۳"
                />
              </label>
              <label>
                شناسه بیمار
                <input
                  inputMode="numeric"
                  value={draft.patientId}
                  onChange={(event) => setDraft((item) => ({ ...item, patientId: event.target.value }))}
                  placeholder="شناسه داخلی"
                />
              </label>
              <label className={styles.searchField}>
                جست‌وجوی متن
                <input
                  value={draft.searchText}
                  onChange={(event) => setDraft((item) => ({ ...item, searchText: event.target.value }))}
                  placeholder="توضیح، بیمار، هدف یا کاربر"
                />
              </label>
              <label>
                ردیف در صفحه
                <select
                  value={draft.pageSize}
                  onChange={(event) => setDraft((item) => ({ ...item, pageSize: event.target.value }))}
                >
                  <option value="25">۲۵</option>
                  <option value="50">۵۰</option>
                  <option value="100">۱۰۰</option>
                </select>
              </label>
              <div className={styles.filterActions}>
                <button type="button" className={styles.primary} onClick={applyFilters} disabled={loading}>
                  {loading ? "در حال دریافت…" : "اعمال فیلتر"}
                </button>
                <button type="button" onClick={resetFilters}>پاک‌کردن</button>
                <button type="button" onClick={() => data && exportCsv(data)} disabled={!data?.rows.length}>
                  CSV صفحه
                </button>
              </div>
            </section>

            <section className={styles.summaryGrid} aria-label="خلاصه دسته‌های رویداد">
              {(data?.category_summary ?? []).map((item) => (
                <article key={item.action_category}>
                  <span>{CATEGORY_LABELS[item.action_category] ?? item.action_category}</span>
                  <strong>{toFarsiDigits(item.count)}</strong>
                </article>
              ))}
            </section>

            <section className={styles.panel} aria-busy={loading}>
              <div className={styles.panelHeader}>
                <div>
                  <h2>دفتر رویدادها</h2>
                  <p>
                    {data
                      ? `${formatJalali(data.date_from)} تا ${formatJalali(data.date_to)}`
                      : "بازه در حال دریافت است"}
                  </p>
                </div>
                <span>صفحه {toFarsiDigits(page)}</span>
              </div>

              {loading && <div className={styles.state}>در حال دریافت رویدادها…</div>}
              {!loading && data?.rows.length === 0 && (
                <div className={styles.state}>رویدادی مطابق فیلتر فعلی پیدا نشد.</div>
              )}
              {!loading && data && data.rows.length > 0 && (
                <div className={styles.tableWrap}>
                  <table>
                    <thead>
                      <tr>
                        <th>زمان و کاربر</th>
                        <th>عملیات</th>
                        <th>شرح و هدف</th>
                        <th>ارتباط</th>
                        <th>مبلغ</th>
                        <th>تغییر</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.rows.map((row) => (
                        <tr key={row.id}>
                          <td data-label="زمان و کاربر">
                            <strong>{row.user_full_name}</strong>
                            <small>{dateTime(row.created_at)}</small>
                            {row.ip_address && <small dir="ltr">{row.ip_address}</small>}
                          </td>
                          <td data-label="عملیات">
                            <span className={styles.actionBadge}>
                              {ACTION_LABELS[row.action_type] ?? row.action_type}
                            </span>
                            <small>{CATEGORY_LABELS[row.action_category] ?? row.action_category}</small>
                          </td>
                          <td data-label="شرح و هدف">
                            <strong>{row.description ?? "—"}</strong>
                            <small>{row.target_name ?? row.target_type ?? "بدون هدف"}</small>
                          </td>
                          <td data-label="ارتباط">
                            <span>{row.invoice_id ? `فاکتور ${toFarsiDigits(row.invoice_id)}` : "—"}</span>
                            <small>{row.patient_name ?? (row.patient_id ? `بیمار ${toFarsiDigits(row.patient_id)}` : "")}</small>
                          </td>
                          <td data-label="مبلغ">{row.amount ? formatToman(row.amount) : "—"}</td>
                          <td data-label="تغییر">
                            {row.old_value || row.new_value ? (
                              <details>
                                <summary>مشاهده</summary>
                                <dl>
                                  <dt>قبل</dt><dd>{row.old_value ?? "—"}</dd>
                                  <dt>بعد</dt><dd>{row.new_value ?? "—"}</dd>
                                </dl>
                              </details>
                            ) : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {data && data.total_pages > 1 && (
                <nav className={styles.pagination} aria-label="صفحه‌بندی رویدادها">
                  <button type="button" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>
                    قبلی
                  </button>
                  {pages.map((value) => (
                    <button
                      type="button"
                      key={value}
                      className={value === page ? styles.activePage : undefined}
                      aria-current={value === page ? "page" : undefined}
                      onClick={() => setPage(value)}
                    >
                      {toFarsiDigits(value)}
                    </button>
                  ))}
                  <button
                    type="button"
                    disabled={page >= data.total_pages}
                    onClick={() => setPage((value) => value + 1)}
                  >
                    بعدی
                  </button>
                </nav>
              )}
            </section>
          </>
        )}
      </main>
    </div>
  );
}
