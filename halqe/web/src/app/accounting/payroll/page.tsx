"use client";

import { useCallback, useEffect, useState } from "react";
import { usePathname } from "next/navigation";

import Nav from "@/components/Nav";
import { useAuth } from "@/hooks/useAuth";
import { ApiError } from "@/lib/api";
import { apiGetAccountingPayrollReport } from "@/lib/api/accounting-payroll-report";
import type { AccountingPayrollReportDTO } from "@/lib/api/accounting-report-types";
import { formatJalali, formatToman, toFarsiDigits } from "@/lib/jalali";
import styles from "../reports/reports.module.css";


function iso(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function initialRange() {
  const end = new Date();
  const start = new Date(end);
  start.setDate(end.getDate() - 29);
  return { dateFrom: iso(start), dateTo: iso(end) };
}

function csv(value: unknown): string {
  return `"${String(value ?? "").replaceAll('"', '""')}"`;
}

export default function AccountingPayrollPage() {
  const { ready, logout } = useAuth();
  const pathname = usePathname();
  const [range, setRange] = useState(initialRange);
  const [staffType, setStaffType] = useState("");
  const [shift, setShift] = useState("");
  const [report, setReport] = useState<AccountingPayrollReportDTO | null>(null);
  const [loading, setLoading] = useState(true);
  const [accessDenied, setAccessDenied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setReport(await apiGetAccountingPayrollReport({
        date_from: range.dateFrom,
        date_to: range.dateTo,
        staff_type: staffType,
        shift,
      }));
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
      setError(err instanceof ApiError ? err.message : "محاسبه حقوق ناموفق بود.");
    } finally {
      setLoading(false);
    }
  }, [range, staffType, shift, logout]);

  useEffect(() => {
    if (ready) void load();
  }, [ready, load]);

  function exportCsv() {
    if (!report) return;
    const rows = [
      ["نام", "نوع", "شیفت صبح", "شیفت عصر", "شیفت شب", "حقوق ناخالص", "مالیات", "خالص"],
      ...report.rows.map((row) => [
        row.name,
        row.type_label,
        row.shift_counts.morning,
        row.shift_counts.evening,
        row.shift_counts.night,
        row.gross_salary,
        row.tax_amount,
        row.net_salary,
      ]),
    ];
    const blob = new Blob(["\ufeff", rows.map((row) => row.map(csv).join(",")).join("\r\n")], {
      type: "text/csv;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "halqe-payroll-preview.csv";
    anchor.click();
    URL.revokeObjectURL(url);
  }

  if (!ready) return null;

  return (
    <div className={styles.layout}>
      <Nav currentPath={pathname ?? "/accounting/payroll"} pageTitle="محاسبه حقوق" onLogout={logout} />
      <main className={styles.main} id="main-content">
        <header className={styles.hero}>
          <div>
            <span className={styles.eyebrow}>PAYROLL PREVIEW</span>
            <h1>محاسبه حقوق کادر درمان</h1>
            <p>
              محاسبه بر اساس حضور واقعی شیفت، فاکتورهای بسته، سهم ویزیت و درصد خدمات انجام می‌شود.
              این صفحه فقط preview است و هیچ پرداخت یا سند حقوقی ایجاد نمی‌کند.
            </p>
          </div>
          <div className={styles.heroBadge}>
            <span>بازه محاسبه</span>
            <strong>{formatJalali(range.dateFrom)} تا {formatJalali(range.dateTo)}</strong>
          </div>
        </header>

        {accessDenied && <div className={styles.errorBox} role="alert">این بخش فقط برای مدیر یا ادمین قابل دسترسی است.</div>}
        {error && <div className={styles.errorBox} role="alert">{error}</div>}

        {!accessDenied && (
          <>
            <section className={styles.filters} aria-label="فیلتر محاسبه حقوق">
              <label>از تاریخ<input type="date" value={range.dateFrom} onChange={(e) => setRange((r) => ({ ...r, dateFrom: e.target.value }))} /></label>
              <label>تا تاریخ<input type="date" value={range.dateTo} onChange={(e) => setRange((r) => ({ ...r, dateTo: e.target.value }))} /></label>
              <label>نوع کادر<select value={staffType} onChange={(e) => setStaffType(e.target.value)}><option value="">همه</option><option value="doctor">پزشک</option><option value="nurse">پرستار</option></select></label>
              <label>شیفت<select value={shift} onChange={(e) => setShift(e.target.value)}><option value="">همه</option><option value="morning">صبح</option><option value="evening">عصر</option><option value="night">شب</option></select></label>
              <button type="button" className={styles.primaryButton} onClick={load} disabled={loading}>{loading ? "در حال محاسبه…" : "محاسبه"}</button>
            </section>

            {loading && !report ? <div className={styles.stateBox} role="status">در حال محاسبه حقوق…</div> : report ? (
              <>
                <section className={styles.metrics} aria-label="خلاصه حقوق">
                  <article><span>تعداد کادر</span><strong>{toFarsiDigits(report.summary.staff_count)}</strong><small>دارای فعالیت یا تنظیمات فعال</small></article>
                  <article><span>ناخالص</span><strong>{formatToman(report.summary.gross_salary)}</strong><small>پیش از کسر مالیات پزشک</small></article>
                  <article><span>مالیات</span><strong>{formatToman(report.summary.tax_amount)}</strong><small>طبق فرمول legacy فقط پزشک</small></article>
                  <article className={styles.metricPrimary}><span>خالص قابل بررسی</span><strong>{formatToman(report.summary.net_salary)}</strong><small>پیش‌نمایش، نه سند پرداخت</small></article>
                </section>

                <section className={styles.panel}>
                  <div className={styles.panelHeader}>
                    <div><h2>ریز محاسبه به تفکیک کادر</h2><p>پایه شیفت و سهم هر خدمت جدا نمایش داده می‌شود.</p></div>
                    <button type="button" onClick={exportCsv}>خروجی CSV</button>
                  </div>
                  <div className={styles.tableWrap}>
                    <table>
                      <thead><tr><th>کادر</th><th>نوع</th><th>شیفت‌ها</th><th>ریز محاسبه</th><th>ناخالص</th><th>مالیات</th><th>خالص</th></tr></thead>
                      <tbody>
                        {report.rows.map((row) => (
                          <tr key={row.id}>
                            <td>{row.name}</td>
                            <td><span className={styles.typeBadge}>{row.type_label}</span></td>
                            <td>صبح {toFarsiDigits(row.shift_counts.morning)} · عصر {toFarsiDigits(row.shift_counts.evening)} · شب {toFarsiDigits(row.shift_counts.night)}</td>
                            <td>{row.details.length ? row.details.map((detail) => `${detail.label}: ${formatToman(detail.total)}`).join(" | ") : "بدون فعالیت"}</td>
                            <td>{formatToman(row.gross_salary)}</td>
                            <td>{formatToman(row.tax_amount)}</td>
                            <td><strong>{formatToman(row.net_salary)}</strong></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              </>
            ) : null}
          </>
        )}
      </main>
    </div>
  );
}
