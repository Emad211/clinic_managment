"use client";

import { useCallback, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import {
  ApiError,
  apiGetOpenAccountingInvoices,
  type AccountingInvoiceDTO,
} from "@/lib/api";
import { formatJalali, formatToman, toFarsiDigits } from "@/lib/jalali";
import { useAuth } from "@/hooks/useAuth";
import Nav from "@/components/Nav";
import styles from "./invoices.module.css";

function pricingLabel(version: string): string {
  if (version === "halqe_visit_procedure_v1") return "کامل: ویزیت، پرستاری و پروسیجر";
  if (version === "halqe_visit_nursing_v1") return "ویزیت و خدمات پرستاری";
  if (version === "halqe_visit_v1") return "ویزیت";
  return "legacy — فقط خواندنی";
}

export default function AccountingInvoicesPage() {
  const { ready, logout } = useAuth();
  const pathname = usePathname();
  const [invoices, setInvoices] = useState<AccountingInvoiceDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [accessDenied, setAccessDenied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await apiGetOpenAccountingInvoices(200, 0);
      setInvoices(response.items);
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
          : "دریافت فاکتورهای باز ناموفق بود.",
      );
    } finally {
      setLoading(false);
    }
  }, [logout]);

  useEffect(() => {
    if (ready) void load();
  }, [ready, load]);

  if (!ready) return null;

  return (
    <div className={styles.layout}>
      <Nav
        currentPath={pathname ?? "/accounting/invoices"}
        pageTitle="فاکتورهای باز"
        onLogout={logout}
      />
      <main className={styles.main} id="main-content">
        <header className={styles.header}>
          <div>
            <h1>فاکتورهای باز</h1>
            <p>نمای واحد جزئیات، اصلاح آیتم‌ها و کنترل تسویه</p>
          </div>
          <div className={styles.headerActions}>
            <Link href="/accounting" className={styles.secondaryLink}>پذیرش</Link>
            <Link href="/accounting/nursing" className={styles.secondaryLink}>پرستاری</Link>
            <Link href="/accounting/procedures" className={styles.secondaryLink}>پروسیجر</Link>
            <Link href="/accounting/payments" className={styles.secondaryLink}>تسویه</Link>
            <button type="button" onClick={load} disabled={loading}>تازه‌سازی</button>
          </div>
        </header>

        {accessDenied && (
          <div className={styles.errorBox} role="alert">
            این بخش فقط برای پذیرش و مدیران حسابداری در دسترس است.
          </div>
        )}
        {error && <div className={styles.errorBox} role="alert">{error}</div>}

        {!accessDenied && (loading ? (
          <div className={styles.stateBox} role="status">در حال بارگذاری…</div>
        ) : invoices.length === 0 ? (
          <div className={styles.stateBox}>فاکتور بازی وجود ندارد.</div>
        ) : (
          <div className={styles.tableWrap}>
            <table>
              <thead>
                <tr>
                  <th>شماره</th>
                  <th>بیمار</th>
                  <th>تاریخ کاری</th>
                  <th>بیمه</th>
                  <th>موتور مالی</th>
                  <th>جمع فعلی</th>
                  <th>عملیات</th>
                </tr>
              </thead>
              <tbody>
                {invoices.map((invoice) => (
                  <tr key={invoice.id}>
                    <td><strong>#{toFarsiDigits(invoice.id)}</strong></td>
                    <td>
                      <strong>{invoice.patient_full_name}</strong>
                      <small dir="ltr">{invoice.phone_number || "—"}</small>
                    </td>
                    <td>{formatJalali(invoice.work_date || invoice.opened_at)}</td>
                    <td>{invoice.insurance_type || "—"}</td>
                    <td>
                      <span
                        className={
                          invoice.pricing_version === "legacy"
                            ? styles.legacyBadge
                            : styles.engineBadge
                        }
                      >
                        {pricingLabel(invoice.pricing_version)}
                      </span>
                    </td>
                    <td>{formatToman(invoice.total_amount)}</td>
                    <td>
                      <Link
                        href={`/accounting/invoices/${invoice.id}`}
                        className={styles.detailLink}
                      >
                        مشاهده و اصلاح
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </main>
    </div>
  );
}
