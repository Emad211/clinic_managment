"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { useParams, usePathname } from "next/navigation";
import Link from "next/link";
import {
  ApiError,
  apiAddAccountingVisitToInvoice,
  apiDeleteAccountingInvoiceItem,
  apiGetAccountingInvoiceDetail,
  type AccountingInvoiceWorkbenchDTO,
  type AccountingWorkbenchItemDTO,
} from "@/lib/api";
import { formatJalali, formatToman, toFarsiDigits } from "@/lib/jalali";
import { useAuth } from "@/hooks/useAuth";
import Nav from "@/components/Nav";
import styles from "./invoice-detail.module.css";

const MUTABLE_VERSIONS = new Set([
  "halqe_visit_v1",
  "halqe_visit_nursing_v1",
  "halqe_visit_procedure_v1",
]);

const ITEM_LABELS: Record<string, string> = {
  visit: "ویزیت",
  injection: "خدمت پرستاری",
  procedure: "پروسیجر",
  consumable: "مصرفی",
};

const PAYMENT_LABELS: Record<string, string> = {
  cash: "نقد",
  card: "کارت",
  insurance: "بیمه",
  supplementary: "بیمهٔ تکمیلی",
};

function errorText(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

function quantityText(item: AccountingWorkbenchItemDTO): string {
  if (item.quantity === 1) return "۱";
  return toFarsiDigits(item.quantity.toLocaleString("en-US", { maximumFractionDigits: 3 }));
}

export default function AccountingInvoiceDetailPage() {
  const { ready, logout } = useAuth();
  const pathname = usePathname();
  const params = useParams<{ invoiceId: string }>();
  const invoiceId = useMemo(() => Number(params.invoiceId), [params.invoiceId]);

  const [detail, setDetail] = useState<AccountingInvoiceWorkbenchDTO | null>(null);
  const [visitNotes, setVisitNotes] = useState("");
  const [loading, setLoading] = useState(true);
  const [addingVisit, setAddingVisit] = useState(false);
  const [deleting, setDeleting] = useState<Record<string, boolean>>({});
  const [accessDenied, setAccessDenied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const mutable = Boolean(
    detail &&
      detail.invoice.status === "open" &&
      MUTABLE_VERSIONS.has(detail.invoice.pricing_version),
  );

  const load = useCallback(async () => {
    if (!Number.isInteger(invoiceId) || invoiceId <= 0) {
      setError("شناسهٔ فاکتور نامعتبر است.");
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await apiGetAccountingInvoiceDetail(invoiceId);
      setDetail(response);
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
      setError(errorText(err, "دریافت جزئیات فاکتور ناموفق بود."));
    } finally {
      setLoading(false);
    }
  }, [invoiceId, logout]);

  useEffect(() => {
    if (ready) void load();
  }, [ready, load]);

  async function addVisit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!mutable) return;
    setAddingVisit(true);
    setError(null);
    setNotice(null);
    try {
      const response = await apiAddAccountingVisitToInvoice(
        invoiceId,
        visitNotes.trim() || null,
      );
      setDetail(response);
      setVisitNotes("");
      setNotice("ویزیت جدید با تعرفهٔ فعلی فاکتور ثبت شد.");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setError(errorText(err, "ثبت ویزیت جدید ناموفق بود."));
    } finally {
      setAddingVisit(false);
    }
  }

  async function removeItem(item: AccountingWorkbenchItemDTO) {
    if (!mutable) return;
    if (
      !window.confirm(
        `${ITEM_LABELS[item.item_type] ?? item.item_type} «${item.description}» حذف شود؟ ` +
          "رکورد پرداخت همان آیتم نیز پاک می‌شود.",
      )
    ) {
      return;
    }
    const key = `${item.item_type}:${item.item_id}`;
    setDeleting((current) => ({ ...current, [key]: true }));
    setError(null);
    setNotice(null);
    try {
      const response = await apiDeleteAccountingInvoiceItem(
        invoiceId,
        item.item_type,
        item.item_id,
      );
      setDetail(response.detail);
      setNotice("آیتم حذف و مبلغ فاکتور به‌صورت اتمیک باز‌محاسبه شد.");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setError(errorText(err, "حذف آیتم ناموفق بود."));
    } finally {
      setDeleting((current) => ({ ...current, [key]: false }));
    }
  }

  if (!ready) return null;

  return (
    <div className={styles.layout}>
      <Nav
        currentPath={pathname ?? `/accounting/invoices/${invoiceId}`}
        pageTitle="جزئیات فاکتور"
        onLogout={logout}
      />
      <main className={styles.main} id="main-content">
        <header className={styles.header}>
          <div>
            <h1>
              جزئیات فاکتور {Number.isFinite(invoiceId) ? `#${toFarsiDigits(invoiceId)}` : ""}
            </h1>
            <p>نمای یکپارچهٔ آیتم‌ها، سهم بیمار و وضعیت پرداخت</p>
          </div>
          <div className={styles.headerActions}>
            <Link href="/accounting/invoices" className={styles.secondaryLink}>فاکتورهای باز</Link>
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
        {notice && <div className={styles.noticeBox} role="status" aria-live="polite">{notice}</div>}

        {!accessDenied && (loading ? (
          <div className={styles.stateBox} role="status">در حال بارگذاری…</div>
        ) : detail ? (
          <>
            <section className={styles.invoiceCard}>
              <div className={styles.invoiceTitleRow}>
                <div>
                  <h2>{detail.invoice.patient_full_name}</h2>
                  <p dir="ltr">{detail.invoice.phone_number || "—"}</p>
                </div>
                <div className={styles.badges}>
                  <span className={detail.invoice.status === "open" ? styles.openBadge : styles.closedBadge}>
                    {detail.invoice.status === "open" ? "باز" : "بسته"}
                  </span>
                  <span className={styles.versionBadge}>{detail.invoice.pricing_version}</span>
                </div>
              </div>
              <div className={styles.metaGrid}>
                <div><span>تاریخ کاری</span><strong>{formatJalali(detail.invoice.work_date || detail.invoice.opened_at)}</strong></div>
                <div><span>شیفت</span><strong>{detail.invoice.shift || "—"}</strong></div>
                <div><span>بیمه</span><strong>{detail.invoice.insurance_type || "—"}</strong></div>
                <div><span>تکمیلی</span><strong>{detail.invoice.supplementary_insurance || "—"}</strong></div>
                <div><span>ثبت‌کننده</span><strong>{detail.invoice.opened_by_name || detail.invoice.opened_by || "—"}</strong></div>
              </div>
            </section>

            {!mutable && (
              <div className={styles.readOnlyBox} role="note">
                {detail.invoice.status === "closed"
                  ? "فاکتور بسته است و فقط برای مشاهده نمایش داده می‌شود."
                  : "این فاکتور legacy است؛ موتور جدید اجازهٔ اصلاح ارقام تاریخی آن را ندارد."}
              </div>
            )}

            <section className={styles.financialGrid} aria-label="خلاصه مالی">
              <div><span>جمع سهم بیمار</span><strong>{formatToman(detail.financials.total_amount)}</strong></div>
              <div><span>پرداخت‌شده</span><strong>{formatToman(detail.financials.paid_amount)}</strong></div>
              <div><span>مانده</span><strong>{formatToman(detail.financials.remaining_amount)}</strong></div>
              <div>
                <span>وضعیت</span>
                <strong>{detail.financials.all_items_paid ? "تسویه‌شده" : "تسویه‌نشده"}</strong>
              </div>
            </section>

            <section className={styles.itemsCard} aria-labelledby="items-title">
              <div className={styles.sectionHeader}>
                <div>
                  <h2 id="items-title">آیتم‌های فاکتور</h2>
                  <p>{toFarsiDigits(detail.items.length)} ردیف</p>
                </div>
              </div>
              {detail.items.length === 0 ? (
                <div className={styles.emptyText}>آیتمی در این فاکتور وجود ندارد.</div>
              ) : (
                <div className={styles.tableWrap}>
                  <table>
                    <thead>
                      <tr>
                        <th>نوع / شرح</th>
                        <th>تعداد</th>
                        <th>قیمت ثبت‌شده</th>
                        <th>سهم بیمار</th>
                        <th>سهم بیمه</th>
                        <th>انجام‌دهنده</th>
                        <th>پرداخت</th>
                        <th>عملیات</th>
                      </tr>
                    </thead>
                    <tbody>
                      {detail.items.map((item) => {
                        const key = `${item.item_type}:${item.item_id}`;
                        return (
                          <tr key={key}>
                            <td>
                              <strong>{ITEM_LABELS[item.item_type] ?? item.item_type}</strong>
                              <span>{item.description}</span>
                              <small>{formatJalali(item.occurred_at)}</small>
                              {item.notes && <small>{item.notes}</small>}
                            </td>
                            <td>{quantityText(item)}</td>
                            <td>{formatToman(item.recorded_amount)}</td>
                            <td>{formatToman(item.patient_amount)}</td>
                            <td>
                              {formatToman(item.insurance_amount)}
                              {item.covered_by_insurance && <small className={styles.coveredText}>پوشش‌دار</small>}
                            </td>
                            <td>{item.performer_name || "—"}</td>
                            <td>
                              <span className={item.is_paid ? styles.paidBadge : styles.unpaidBadge}>
                                {item.is_paid
                                  ? `پرداخت‌شده${item.payment_type ? ` — ${PAYMENT_LABELS[item.payment_type] ?? item.payment_type}` : ""}`
                                  : "پرداخت‌نشده"}
                              </span>
                            </td>
                            <td>
                              {mutable ? (
                                <button
                                  type="button"
                                  className={styles.deleteButton}
                                  onClick={() => removeItem(item)}
                                  disabled={Boolean(deleting[key])}
                                  aria-label={`حذف ${item.description}`}
                                >
                                  {deleting[key] ? "…" : "حذف"}
                                </button>
                              ) : "—"}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            {mutable && (
              <form className={styles.addVisitCard} onSubmit={addVisit}>
                <div>
                  <h2>افزودن ویزیت جدید</h2>
                  <p>تعرفه از بیمهٔ snapshot فاکتور و پزشک از کادر همان شیفت گرفته می‌شود.</p>
                </div>
                <label>
                  یادداشت اختیاری
                  <input
                    value={visitNotes}
                    onChange={(event) => setVisitNotes(event.target.value)}
                    placeholder="توضیح ویزیت دوم"
                  />
                </label>
                <button type="submit" className={styles.primaryButton} disabled={addingVisit}>
                  {addingVisit ? "در حال ثبت…" : "افزودن ویزیت"}
                </button>
              </form>
            )}
          </>
        ) : null)}
      </main>
    </div>
  );
}
