"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname } from "next/navigation";

import Nav from "@/components/Nav";
import { useAuth } from "@/hooks/useAuth";
import { ApiError } from "@/lib/api";
import {
  apiGetAccountingInvoiceReport,
  apiGetAccountingReportsOverview,
  apiGetAccountingServiceReport,
  type AccountingInvoiceReportDTO,
  type AccountingReportsOverviewDTO,
  type AccountingServiceReportDTO,
} from "@/lib/api/accounting-reports";
import { formatJalali, formatToman, toFarsiDigits } from "@/lib/jalali";
import styles from "./reports.module.css";


type View = "overview" | "invoices" | "services";
type Filters = {
  dateFrom: string;
  dateTo: string;
  status: string;
  insurance: string;
  reception: string;
  serviceType: string;
  shift: string;
};

const SERVICE_LABELS: Record<string, string> = {
  visit: "ویزیت",
  nursing: "پرستاری",
  procedure: "پروسیجر",
  consumable: "مصرفی",
};
const SHIFT_LABELS: Record<string, string> = {
  morning: "صبح",
  evening: "عصر",
  night: "شب",
};

function iso(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function initialFilters(): Filters {
  const end = new Date();
  const start = new Date(end);
  start.setDate(end.getDate() - 6);
  return {
    dateFrom: iso(start),
    dateTo: iso(end),
    status: "",
    insurance: "",
    reception: "",
    serviceType: "",
    shift: "",
  };
}

function errorText(error: unknown): string {
  return error instanceof ApiError
    ? error.message
    : "دریافت گزارش‌های حسابداری ناموفق بود.";
}

function csvCell(value: unknown): string {
  const text = value == null ? "" : String(value);
  return `"${text.replaceAll('"', '""')}"`;
}

function downloadCsv(filename: string, headers: string[], rows: unknown[][]) {
  const body = [headers, ...rows]
    .map((row) => row.map(csvCell).join(","))
    .join("\r\n");
  const blob = new Blob(["\ufeff", body], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export default function AccountingReportsPage() {
  const { ready, logout } = useAuth();
  const pathname = usePathname();
  const [view, setView] = useState<View>("overview");
  const [filters, setFilters] = useState<Filters>(initialFilters);
  const [overview, setOverview] = useState<AccountingReportsOverviewDTO | null>(null);
  const [invoices, setInvoices] = useState<AccountingInvoiceReportDTO | null>(null);
  const [services, setServices] = useState<AccountingServiceReportDTO | null>(null);
  const [loading, setLoading] = useState(true);
  const [accessDenied, setAccessDenied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const range = { date_from: filters.dateFrom, date_to: filters.dateTo };
    try {
      const [overviewData, invoiceData, serviceData] = await Promise.all([
        apiGetAccountingReportsOverview(range),
        apiGetAccountingInvoiceReport({
          ...range,
          status: filters.status,
          insurance_type: filters.insurance,
          reception_user: filters.reception,
          limit: 500,
        }),
        apiGetAccountingServiceReport({
          ...range,
          service_type: filters.serviceType,
          shift: filters.shift,
          limit: 700,
        }),
      ]);
      setOverview(overviewData);
      setInvoices(invoiceData);
      setServices(serviceData);
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
      setError(errorText(err));
    } finally {
      setLoading(false);
    }
  }, [filters, logout]);

  useEffect(() => {
    if (ready) void load();
  }, [ready, load]);

  const maxRevenue = useMemo(
    () => Math.max(1, ...(overview?.daily.map((item) => item.operating_revenue) ?? [1])),
    [overview],
  );

  function preset(days: number) {
    const end = new Date();
    const start = new Date(end);
    start.setDate(end.getDate() - days + 1);
    setFilters((current) => ({ ...current, dateFrom: iso(start), dateTo: iso(end) }));
  }

  function exportInvoices() {
    if (!invoices) return;
    downloadCsv(
      "halqe-invoices-report.csv",
      ["شماره", "تاریخ کاری", "بیمار", "وضعیت", "مبلغ", "بیمه", "پذیرش", "بستن توسط"],
      invoices.rows.map((row) => [
        row.id,
        row.work_date ? formatJalali(row.work_date) : "",
        row.patient_name,
        row.status === "closed" ? "بسته" : "باز",
        row.total_amount,
        row.insurance_type ?? "",
        row.opened_by_name ?? "",
        row.closed_by_name ?? "",
      ]),
    );
  }

  function exportServices() {
    if (!services) return;
    downloadCsv(
      "halqe-services-report.csv",
      ["نوع", "تاریخ", "بیمار", "خدمت", "تعداد", "مبلغ", "سهم بیمار", "سهم بیمه", "کادر", "شیفت"],
      services.rows.map((row) => [
        SERVICE_LABELS[row.service_type] ?? row.service_type,
        row.work_date ? formatJalali(row.work_date) : "",
        row.patient_name,
        row.service_name,
        row.quantity,
        row.amount,
        row.patient_amount,
        row.insurance_amount,
        row.staff_name ?? "",
        SHIFT_LABELS[row.shift ?? ""] ?? row.shift ?? "",
      ]),
    );
  }

  if (!ready) return null;

  return (
    <div className={styles.layout}>
      <Nav
        currentPath={pathname ?? "/accounting/reports"}
        pageTitle="گزارش‌های مالی"
        onLogout={logout}
      />
      <main className={styles.main} id="main-content">
        <header className={styles.hero}>
          <div>
            <span className={styles.eyebrow}>FINANCIAL INTELLIGENCE</span>
            <h1>مرکز گزارش‌های حسابداری</h1>
            <p>
              درآمد عملیاتی دقیقاً مطابق برنامهٔ قدیمی از ویزیت، خدمات پرستاری و
              پروسیجر محاسبه می‌شود. مصرفی‌ها جدا نمایش داده می‌شوند و وارد درآمد نیستند.
            </p>
          </div>
          <div className={styles.heroBadge}>
            <span>بازه فعال</span>
            <strong>
              {formatJalali(filters.dateFrom)} تا {formatJalali(filters.dateTo)}
            </strong>
          </div>
        </header>

        {accessDenied && (
          <section className={styles.errorBox} role="alert">
            گزارش‌های مالی فقط برای مدیر یا ادمین قابل دسترسی است.
          </section>
        )}
        {error && <section className={styles.errorBox} role="alert">{error}</section>}

        {!accessDenied && (
          <>
            <section className={styles.filters} aria-label="فیلتر گزارش">
              <div className={styles.presets}>
                {[7, 30, 90].map((days) => (
                  <button type="button" key={days} onClick={() => preset(days)}>
                    {toFarsiDigits(days)} روز
                  </button>
                ))}
              </div>
              <label>
                از تاریخ
                <input
                  type="date"
                  value={filters.dateFrom}
                  onChange={(event) => setFilters((current) => ({ ...current, dateFrom: event.target.value }))}
                />
              </label>
              <label>
                تا تاریخ
                <input
                  type="date"
                  value={filters.dateTo}
                  onChange={(event) => setFilters((current) => ({ ...current, dateTo: event.target.value }))}
                />
              </label>
              <button type="button" className={styles.primaryButton} onClick={load} disabled={loading}>
                {loading ? "در حال محاسبه…" : "به‌روزرسانی گزارش"}
              </button>
            </section>

            {loading && !overview ? (
              <div className={styles.stateBox} role="status">در حال محاسبه گزارش مالی…</div>
            ) : overview ? (
              <>
                <section className={styles.metrics} aria-label="شاخص‌های مالی">
                  <article className={styles.metricPrimary}>
                    <span>درآمد عملیاتی</span>
                    <strong>{formatToman(overview.revenue.operating_revenue)}</strong>
                    <small>بدون مصرفی؛ فقط فاکتورهای بسته</small>
                  </article>
                  <article>
                    <span>تعهد ثبت‌شده فاکتورها</span>
                    <strong>{formatToman(overview.invoices.total_liability)}</strong>
                    <small>{toFarsiDigits(overview.invoices.total)} فاکتور</small>
                  </article>
                  <article>
                    <span>بیماران یکتا</span>
                    <strong>{toFarsiDigits(overview.invoices.unique_patients)}</strong>
                    <small>{toFarsiDigits(overview.invoices.closed)} بسته · {toFarsiDigits(overview.invoices.open)} باز</small>
                  </article>
                  <article>
                    <span>هزینه مصرفی مرکز</span>
                    <strong>{formatToman(overview.consumables.amount)}</strong>
                    <small>جدا از درآمد عملیاتی</small>
                  </article>
                  <article>
                    <span>آیتم پرداخت‌نشده</span>
                    <strong>{toFarsiDigits(overview.payments.unpaid_items)}</strong>
                    <small>از {toFarsiDigits(overview.payments.items)} آیتم مالی</small>
                  </article>
                </section>

                <nav className={styles.tabs} aria-label="نمای گزارش">
                  {([
                    ["overview", "خلاصه و روند"],
                    ["invoices", "فاکتورها"],
                    ["services", "خدمات"],
                  ] as Array<[View, string]>).map(([key, label]) => (
                    <button
                      type="button"
                      key={key}
                      className={view === key ? styles.tabActive : ""}
                      onClick={() => setView(key)}
                      aria-current={view === key ? "page" : undefined}
                    >
                      {label}
                    </button>
                  ))}
                </nav>

                {view === "overview" && (
                  <div className={styles.overviewGrid}>
                    <section className={styles.panel}>
                      <div className={styles.panelHeader}>
                        <div><h2>روند روزانه درآمد</h2><p>ارتفاع ستون فقط درآمد عملیاتی را نشان می‌دهد.</p></div>
                      </div>
                      <div className={styles.chart} role="img" aria-label="نمودار روند درآمد روزانه">
                        {overview.daily.map((item) => (
                          <div className={styles.chartColumn} key={item.day}>
                            <span className={styles.chartValue}>{formatToman(item.operating_revenue)}</span>
                            <div className={styles.chartTrack}>
                              <div
                                className={styles.chartBar}
                                style={{ height: `${Math.max(3, (item.operating_revenue / maxRevenue) * 100)}%` }}
                              />
                            </div>
                            <small>{formatJalali(item.day)}</small>
                          </div>
                        ))}
                      </div>
                    </section>

                    <section className={styles.panel}>
                      <div className={styles.panelHeader}><div><h2>ترکیب درآمد</h2><p>مصرفی در این جمع وارد نمی‌شود.</p></div></div>
                      <div className={styles.revenueList}>
                        {(["visit", "nursing", "procedure"] as const).map((key) => (
                          <div key={key}>
                            <span>{SERVICE_LABELS[key]}</span>
                            <strong>{formatToman(overview.revenue[key].amount)}</strong>
                            <small>{toFarsiDigits(overview.revenue[key].count)} مورد</small>
                          </div>
                        ))}
                      </div>
                    </section>
                  </div>
                )}

                {view === "invoices" && invoices && (
                  <section className={styles.panel}>
                    <div className={styles.panelHeader}>
                      <div><h2>گزارش فاکتورها</h2><p>{toFarsiDigits(invoices.summary.total)} ردیف مطابق فیلتر</p></div>
                      <button type="button" onClick={exportInvoices}>خروجی CSV</button>
                    </div>
                    <div className={styles.inlineFilters}>
                      <label>وضعیت<select value={filters.status} onChange={(e) => setFilters((c) => ({ ...c, status: e.target.value }))}><option value="">همه</option><option value="open">باز</option><option value="closed">بسته</option></select></label>
                      <label>بیمه<select value={filters.insurance} onChange={(e) => setFilters((c) => ({ ...c, insurance: e.target.value }))}><option value="">همه</option>{overview.filters.insurances.map((item) => <option key={item}>{item}</option>)}</select></label>
                      <label>پذیرش<select value={filters.reception} onChange={(e) => setFilters((c) => ({ ...c, reception: e.target.value }))}><option value="">همه</option>{overview.filters.reception_users.map((item) => <option value={item.username} key={item.username}>{item.full_name}</option>)}</select></label>
                      <button type="button" onClick={load}>اعمال فیلتر</button>
                    </div>
                    <div className={styles.tableWrap}>
                      <table><thead><tr><th>شماره</th><th>تاریخ</th><th>بیمار</th><th>وضعیت</th><th>مبلغ</th><th>بیمه</th><th>پذیرش</th></tr></thead>
                        <tbody>{invoices.rows.map((row) => <tr key={row.id}><td data-label="شماره">#{toFarsiDigits(row.id)}</td><td data-label="تاریخ">{formatJalali(row.work_date)}</td><td data-label="بیمار">{row.patient_name}</td><td data-label="وضعیت"><span className={row.status === "closed" ? styles.statusClosed : styles.statusOpen}>{row.status === "closed" ? "بسته" : "باز"}</span></td><td data-label="مبلغ">{formatToman(row.total_amount)}</td><td data-label="بیمه">{row.insurance_type ?? "—"}</td><td data-label="پذیرش">{row.opened_by_name ?? "—"}</td></tr>)}</tbody>
                      </table>
                    </div>
                  </section>
                )}

                {view === "services" && services && (
                  <section className={styles.panel}>
                    <div className={styles.panelHeader}>
                      <div><h2>گزارش خدمات</h2><p>مصرفی‌های آوردهٔ بیمار و ردیف‌های استثنا در نمای پیش‌فرض حذف شده‌اند.</p></div>
                      <button type="button" onClick={exportServices}>خروجی CSV</button>
                    </div>
                    <div className={styles.inlineFilters}>
                      <label>نوع خدمت<select value={filters.serviceType} onChange={(e) => setFilters((c) => ({ ...c, serviceType: e.target.value }))}><option value="">همه</option>{Object.entries(SERVICE_LABELS).map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select></label>
                      <label>شیفت<select value={filters.shift} onChange={(e) => setFilters((c) => ({ ...c, shift: e.target.value }))}><option value="">همه</option>{Object.entries(SHIFT_LABELS).map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select></label>
                      <button type="button" onClick={load}>اعمال فیلتر</button>
                    </div>
                    <div className={styles.tableWrap}>
                      <table><thead><tr><th>نوع</th><th>تاریخ</th><th>بیمار</th><th>خدمت</th><th>تعداد</th><th>مبلغ</th><th>سهم بیمار</th><th>سهم بیمه</th><th>کادر</th></tr></thead>
                        <tbody>{services.rows.map((row) => <tr key={`${row.service_type}-${row.id}`}><td data-label="نوع"><span className={styles.typeBadge}>{SERVICE_LABELS[row.service_type]}</span></td><td data-label="تاریخ">{formatJalali(row.work_date)}</td><td data-label="بیمار">{row.patient_name}</td><td data-label="خدمت">{row.service_name}</td><td data-label="تعداد">{toFarsiDigits(row.quantity)}</td><td data-label="مبلغ">{formatToman(row.amount)}</td><td data-label="سهم بیمار">{formatToman(row.patient_amount)}</td><td data-label="سهم بیمه">{formatToman(row.insurance_amount)}</td><td data-label="کادر">{row.staff_name ?? "—"}</td></tr>)}</tbody>
                      </table>
                    </div>
                  </section>
                )}
              </>
            ) : null}
          </>
        )}
      </main>
    </div>
  );
}
