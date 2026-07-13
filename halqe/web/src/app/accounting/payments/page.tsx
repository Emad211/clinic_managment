"use client";

import { useCallback, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import {
  ApiError,
  apiCloseAccountingInvoice,
  apiGetAccountingInvoiceFinancials,
  apiGetOpenAccountingInvoices,
  apiSetAccountingItemPayment,
  apiSettleAccountingInvoice,
  type AccountingInvoiceDTO,
  type AccountingPaymentSummaryDTO,
  type AccountingPaymentType,
} from "@/lib/api";
import { formatJalali, formatToman, toFarsiDigits } from "@/lib/jalali";
import { useAuth } from "@/hooks/useAuth";
import Nav from "@/components/Nav";
import styles from "./payments.module.css";

interface PaymentRow {
  invoice: AccountingInvoiceDTO;
  summary: AccountingPaymentSummaryDTO;
}

const PAYMENT_METHODS: Array<{
  value: AccountingPaymentType;
  label: string;
}> = [
  { value: "card", label: "کارت" },
  { value: "cash", label: "نقد" },
  { value: "insurance", label: "بیمه" },
  { value: "supplementary", label: "بیمهٔ تکمیلی" },
];

function errorText(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

export default function AccountingPaymentsPage() {
  const { ready, logout } = useAuth();
  const pathname = usePathname();
  const [rows, setRows] = useState<PaymentRow[]>([]);
  const [methods, setMethods] = useState<Record<number, AccountingPaymentType>>({});
  const [busy, setBusy] = useState<Record<number, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [accessDenied, setAccessDenied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const open = await apiGetOpenAccountingInvoices(200, 0);
      const financials = await Promise.all(
        open.items.map((invoice) =>
          apiGetAccountingInvoiceFinancials(invoice.id),
        ),
      );
      const byId = new Map(financials.map((item) => [item.invoice_id, item]));
      setRows(
        open.items.map((invoice) => ({
          invoice,
          summary: byId.get(invoice.id) ?? {
            invoice_id: invoice.id,
            total_amount: invoice.total_amount,
            paid_amount: 0,
            remaining_amount: invoice.total_amount,
            all_items_paid: false,
            payment_type: null,
          },
        })),
      );
      setMethods((current) => {
        const next = { ...current };
        for (const invoice of open.items) {
          next[invoice.id] ??= "card";
        }
        return next;
      });
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
      setError(errorText(err, "دریافت وضعیت تسویه ناموفق بود."));
    } finally {
      setLoading(false);
    }
  }, [logout]);

  useEffect(() => {
    if (ready) void load();
  }, [ready, load]);

  function updateSummary(summary: AccountingPaymentSummaryDTO) {
    setRows((current) =>
      current.map((row) =>
        row.invoice.id === summary.invoice_id ? { ...row, summary } : row,
      ),
    );
  }

  async function settle(invoiceId: number) {
    setBusy((current) => ({ ...current, [invoiceId]: true }));
    setError(null);
    setNotice(null);
    try {
      const summary = await apiSettleAccountingInvoice(
        invoiceId,
        methods[invoiceId] ?? "card",
      );
      updateSummary(summary);
      setNotice(`فاکتور شمارهٔ ${toFarsiDigits(invoiceId)} تسویه شد.`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setError(errorText(err, "تسویهٔ فاکتور ناموفق بود."));
    } finally {
      setBusy((current) => ({ ...current, [invoiceId]: false }));
    }
  }

  async function undoSettlement(row: PaymentRow) {
    const visitId = row.invoice.visit_id;
    if (!visitId) {
      setError("آیتم ویزیت این فاکتور پیدا نشد.");
      return;
    }
    setBusy((current) => ({ ...current, [row.invoice.id]: true }));
    setError(null);
    setNotice(null);
    try {
      const summary = await apiSetAccountingItemPayment(
        row.invoice.id,
        "visit",
        visitId,
        null,
        false,
      );
      updateSummary(summary);
      setNotice(
        `تسویهٔ فاکتور شمارهٔ ${toFarsiDigits(row.invoice.id)} لغو شد.`,
      );
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setError(errorText(err, "لغو تسویه ناموفق بود."));
    } finally {
      setBusy((current) => ({ ...current, [row.invoice.id]: false }));
    }
  }

  async function close(row: PaymentRow) {
    if (!row.summary.all_items_paid) {
      setError("پیش از بستن فاکتور، همهٔ آیتم‌ها باید تسویه شوند.");
      return;
    }
    if (
      !window.confirm(
        `فاکتور بیمار «${row.invoice.patient_full_name}» بسته شود؟`,
      )
    ) {
      return;
    }

    const invoiceId = row.invoice.id;
    setBusy((current) => ({ ...current, [invoiceId]: true }));
    setError(null);
    setNotice(null);
    try {
      await apiCloseAccountingInvoice(invoiceId);
      setRows((current) =>
        current.filter((item) => item.invoice.id !== invoiceId),
      );
      setNotice(`فاکتور شمارهٔ ${toFarsiDigits(invoiceId)} بسته شد.`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setError(errorText(err, "بستن فاکتور ناموفق بود."));
    } finally {
      setBusy((current) => ({ ...current, [invoiceId]: false }));
    }
  }

  if (!ready) return null;

  return (
    <div className={styles.layout}>
      <Nav
        currentPath={pathname ?? "/accounting/payments"}
        pageTitle="تسویهٔ فاکتورها"
        onLogout={logout}
      />
      <main className={styles.main} id="main-content">
        <header className={styles.header}>
          <div>
            <h1>تسویهٔ فاکتورهای باز</h1>
            <p>
              ثبت روش پرداخت، کنترل مانده و بستن فاکتور فقط پس از تسویهٔ کامل
            </p>
          </div>
          <div className={styles.headerActions}>
            <Link href="/accounting" className={styles.secondaryLink}>
              پذیرش و فاکتور جدید
            </Link>
            <button type="button" onClick={load} disabled={loading}>
              تازه‌سازی
            </button>
          </div>
        </header>

        {accessDenied && (
          <section className={styles.errorBox} role="alert">
            این بخش فقط برای پذیرش و مدیران حسابداری در دسترس است.
          </section>
        )}
        {error && (
          <div className={styles.errorBox} role="alert">
            {error}
          </div>
        )}
        {notice && (
          <div className={styles.noticeBox} role="status" aria-live="polite">
            {notice}
          </div>
        )}

        {!accessDenied &&
          (loading ? (
            <div className={styles.stateBox} role="status">
              در حال دریافت وضعیت پرداخت…
            </div>
          ) : rows.length === 0 ? (
            <div className={styles.stateBox}>فاکتور بازی وجود ندارد.</div>
          ) : (
            <div className={styles.tableWrap}>
              <table>
                <thead>
                  <tr>
                    <th>فاکتور</th>
                    <th>بیمار</th>
                    <th>تاریخ</th>
                    <th>مبلغ</th>
                    <th>پرداخت‌شده</th>
                    <th>مانده</th>
                    <th>روش / عملیات</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => {
                    const invoice = row.invoice;
                    const summary = row.summary;
                    const isBusy = Boolean(busy[invoice.id]);
                    return (
                      <tr key={invoice.id}>
                        <td>
                          <strong>#{toFarsiDigits(invoice.id)}</strong>
                          <small>{invoice.insurance_type || "—"}</small>
                        </td>
                        <td>
                          <strong>{invoice.patient_full_name}</strong>
                          <small dir="ltr">{invoice.phone_number || "—"}</small>
                        </td>
                        <td>{formatJalali(invoice.work_date || invoice.opened_at)}</td>
                        <td>{formatToman(summary.total_amount)}</td>
                        <td className={styles.paidAmount}>
                          {formatToman(summary.paid_amount)}
                        </td>
                        <td
                          className={
                            summary.remaining_amount === 0
                              ? styles.paidAmount
                              : styles.remainingAmount
                          }
                        >
                          {formatToman(summary.remaining_amount)}
                        </td>
                        <td>
                          <div className={styles.actions}>
                            {!summary.all_items_paid ? (
                              <>
                                <select
                                  aria-label={`روش پرداخت فاکتور ${invoice.id}`}
                                  value={methods[invoice.id] ?? "card"}
                                  onChange={(event) =>
                                    setMethods((current) => ({
                                      ...current,
                                      [invoice.id]: event.target
                                        .value as AccountingPaymentType,
                                    }))
                                  }
                                  disabled={isBusy}
                                >
                                  {PAYMENT_METHODS.map((method) => (
                                    <option key={method.value} value={method.value}>
                                      {method.label}
                                    </option>
                                  ))}
                                </select>
                                <button
                                  type="button"
                                  className={styles.settleButton}
                                  onClick={() => settle(invoice.id)}
                                  disabled={isBusy}
                                >
                                  {isBusy ? "…" : "تسویه"}
                                </button>
                              </>
                            ) : (
                              <>
                                <span className={styles.paidBadge}>تسویه‌شده</span>
                                <button
                                  type="button"
                                  className={styles.undoButton}
                                  onClick={() => undoSettlement(row)}
                                  disabled={isBusy}
                                >
                                  لغو تسویه
                                </button>
                                <button
                                  type="button"
                                  className={styles.closeButton}
                                  onClick={() => close(row)}
                                  disabled={isBusy}
                                >
                                  {isBusy ? "…" : "بستن فاکتور"}
                                </button>
                              </>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ))}

        <p className={styles.safetyNote}>
          بستن فاکتور در سطح سرویس و PostgreSQL فقط زمانی مجاز است که همهٔ آیتم‌ها
          پرداخت شده باشند. در این برش، تسویهٔ یکجا فقط برای فاکتورهای ویزیت خالص
          فعال است.
        </p>
      </main>
    </div>
  );
}
