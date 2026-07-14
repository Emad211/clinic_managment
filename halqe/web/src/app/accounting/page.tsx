"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { usePathname } from "next/navigation";
import {
  ApiError,
  apiCloseAccountingInvoice,
  apiGetOpenAccountingInvoices,
  apiGetVisitTariffs,
  apiOpenVisitInvoice,
  apiSearchAccountingPatients,
  type AccountingInvoiceDTO,
  type VisitTariffDTO,
} from "@/lib/api";
import { formatJalali, formatToman, toFarsiDigits } from "@/lib/jalali";
import { useAuth } from "@/hooks/useAuth";
import Nav from "@/components/Nav";
import styles from "./accounting.module.css";

interface FormState {
  name: string;
  familyName: string;
  nationalId: string;
  phone: string;
  isForeign: boolean;
  insuranceType: string;
  supplementaryInsurance: string;
  notes: string;
}

const EMPTY_FORM: FormState = {
  name: "",
  familyName: "",
  nationalId: "",
  phone: "",
  isForeign: false,
  insuranceType: "",
  supplementaryInsurance: "",
  notes: "",
};

function errorText(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

export default function AccountingPage() {
  const { ready, logout } = useAuth();
  const pathname = usePathname();

  const [tariffs, setTariffs] = useState<VisitTariffDTO[]>([]);
  const [invoices, setInvoices] = useState<AccountingInvoiceDTO[]>([]);
  const [total, setTotal] = useState(0);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [lookingUp, setLookingUp] = useState(false);
  const [patientNotice, setPatientNotice] = useState<string | null>(null);
  const [closing, setClosing] = useState<Record<number, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [accessDenied, setAccessDenied] = useState(false);

  const primaryTariffs = useMemo(
    () => tariffs.filter((item) => !item.is_supplementary),
    [tariffs],
  );
  const supplementaryTariffs = useMemo(
    () => tariffs.filter((item) => item.is_supplementary),
    [tariffs],
  );

  const fetchAccounting = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [tariffRows, invoiceRows] = await Promise.all([
        apiGetVisitTariffs(),
        apiGetOpenAccountingInvoices(100, 0),
      ]);
      setTariffs(tariffRows);
      setInvoices(invoiceRows.items);
      setTotal(invoiceRows.total);
      setAccessDenied(false);
      setForm((current) => ({
        ...current,
        insuranceType:
          current.insuranceType ||
          tariffRows.find((item) => item.is_base_tariff)?.insurance_type ||
          tariffRows.find((item) => !item.is_supplementary)?.insurance_type ||
          "",
      }));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      if (err instanceof ApiError && err.status === 403) {
        setAccessDenied(true);
        return;
      }
      setError(errorText(err, "دریافت اطلاعات حسابداری ناموفق بود."));
    } finally {
      setLoading(false);
    }
  }, [logout]);

  useEffect(() => {
    if (!ready) return;
    fetchAccounting();
  }, [ready, fetchAccounting]);

  function updateField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((current) => ({ ...current, [key]: value }));
    if (key === "nationalId") setPatientNotice(null);
  }

  async function lookupPatient() {
    const nationalId = form.nationalId.trim();
    setPatientNotice(null);
    setError(null);
    if (nationalId.length !== 10) {
      setPatientNotice("برای جست‌وجو، کد ملی ده‌رقمی را وارد کنید.");
      return;
    }

    setLookingUp(true);
    try {
      const matches = await apiSearchAccountingPatients(nationalId, 10);
      const patient = matches.find((item) => item.national_id === nationalId);
      if (!patient) {
        setPatientNotice("بیمار قبلی پیدا نشد؛ یک بیمار جدید ثبت خواهد شد.");
        return;
      }
      setForm((current) => ({
        ...current,
        name: patient.name,
        familyName: patient.family_name,
        phone: patient.phone_number ?? "",
        insuranceType: patient.insurance_type || current.insuranceType,
      }));
      setPatientNotice(`پروندهٔ ${patient.full_name} پیدا و در فرم بارگذاری شد.`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setError(errorText(err, "جست‌وجوی بیمار ناموفق بود."));
    } finally {
      setLookingUp(false);
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSuccess(null);

    if (!form.name.trim() || !form.familyName.trim()) {
      setError("نام و نام خانوادگی بیمار الزامی است.");
      return;
    }
    if (!form.isForeign && !form.nationalId.trim()) {
      setError("کد ملی برای بیمار ایرانی الزامی است.");
      return;
    }
    if (!form.insuranceType) {
      setError("نوع بیمه را انتخاب کنید.");
      return;
    }

    setSubmitting(true);
    try {
      const created = await apiOpenVisitInvoice({
        patient: {
          name: form.name.trim(),
          family_name: form.familyName.trim(),
          national_id: form.isForeign ? null : form.nationalId.trim(),
          phone_number: form.phone.trim() || null,
          is_foreign: form.isForeign,
        },
        insurance_type: form.insuranceType,
        supplementary_insurance: form.supplementaryInsurance || null,
        notes: form.notes.trim() || null,
      });
      setInvoices((current) => [created, ...current]);
      setTotal((current) => current + 1);
      setSuccess(`فاکتور شمارهٔ ${toFarsiDigits(created.id)} با موفقیت باز شد.`);
      setPatientNotice(null);
      setForm((current) => ({
        ...EMPTY_FORM,
        insuranceType: current.insuranceType,
      }));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setError(errorText(err, "بازکردن فاکتور ناموفق بود."));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleClose(invoiceId: number, patientName: string) {
    const confirmed = window.confirm(
      `فاکتور بیمار «${patientName}» بسته شود؟ پس از بستن، ویرایش این برش مجاز نیست.`,
    );
    if (!confirmed) return;

    setError(null);
    setSuccess(null);
    setClosing((current) => ({ ...current, [invoiceId]: true }));
    try {
      await apiCloseAccountingInvoice(invoiceId);
      setInvoices((current) => current.filter((item) => item.id !== invoiceId));
      setTotal((current) => Math.max(0, current - 1));
      setSuccess(`فاکتور شمارهٔ ${toFarsiDigits(invoiceId)} بسته شد.`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setError(errorText(err, "بستن فاکتور ناموفق بود."));
    } finally {
      setClosing((current) => ({ ...current, [invoiceId]: false }));
    }
  }

  if (!ready) return null;

  return (
    <div className={styles.layout}>
      <Nav
        currentPath={pathname ?? "/accounting"}
        pageTitle="حسابداری و پذیرش"
        onLogout={logout}
      />

      <main className={styles.main} id="main-content">
        <header className={styles.header}>
          <div>
            <h1>حسابداری و پذیرش</h1>
            <p>ثبت بیمار، بازکردن فاکتور ویزیت و مدیریت فاکتورهای باز</p>
          </div>
          <div className={styles.counter} aria-label={`${total} فاکتور باز`}>
            <strong>{toFarsiDigits(total)}</strong>
            <span>فاکتور باز</span>
          </div>
        </header>

        {accessDenied && (
          <section className={styles.accessDenied} role="alert">
            این بخش فقط برای پذیرش و مدیران حسابداری در دسترس است.
          </section>
        )}

        {!accessDenied && (
          <>
            {error && (
              <div className={styles.errorBox} role="alert">
                {error}
              </div>
            )}
            {success && (
              <div className={styles.successBox} role="status" aria-live="polite">
                {success}
              </div>
            )}

            <div className={styles.grid}>
              <section className={styles.card} aria-labelledby="new-invoice-title">
                <div className={styles.cardHeader}>
                  <h2 id="new-invoice-title">فاکتور ویزیت جدید</h2>
                  <span>ثبت و بازکردن اتمیک</span>
                </div>

                <form onSubmit={handleSubmit} className={styles.form}>
                  <div className={styles.twoColumns}>
                    <label>
                      نام
                      <input
                        value={form.name}
                        onChange={(event) => updateField("name", event.target.value)}
                        autoComplete="given-name"
                        required
                      />
                    </label>
                    <label>
                      نام خانوادگی
                      <input
                        value={form.familyName}
                        onChange={(event) =>
                          updateField("familyName", event.target.value)
                        }
                        autoComplete="family-name"
                        required
                      />
                    </label>
                  </div>

                  <div className={styles.twoColumns}>
                    <div className={styles.fieldGroup}>
                      <div className={styles.fieldHeader}>
                        <label htmlFor="accounting-national-id">کد ملی</label>
                        <button
                          type="button"
                          className={styles.lookupButton}
                          onClick={lookupPatient}
                          disabled={
                            lookingUp ||
                            form.isForeign ||
                            form.nationalId.trim().length !== 10
                          }
                        >
                          {lookingUp ? "…" : "یافتن بیمار"}
                        </button>
                      </div>
                      <input
                        id="accounting-national-id"
                        value={form.nationalId}
                        onChange={(event) =>
                          updateField("nationalId", event.target.value)
                        }
                        inputMode="numeric"
                        dir="ltr"
                        maxLength={10}
                        disabled={form.isForeign}
                        required={!form.isForeign}
                      />
                    </div>
                    <label>
                      شماره همراه
                      <input
                        value={form.phone}
                        onChange={(event) => updateField("phone", event.target.value)}
                        inputMode="tel"
                        dir="ltr"
                        maxLength={11}
                        autoComplete="tel"
                      />
                    </label>
                  </div>

                  {patientNotice && (
                    <p className={styles.patientNotice} aria-live="polite">
                      {patientNotice}
                    </p>
                  )}

                  <label className={styles.checkboxLabel}>
                    <input
                      type="checkbox"
                      checked={form.isForeign}
                      onChange={(event) => {
                        updateField("isForeign", event.target.checked);
                        if (event.target.checked) updateField("nationalId", "");
                      }}
                    />
                    بیمار غیرایرانی است
                  </label>

                  <div className={styles.twoColumns}>
                    <label>
                      بیمه پایه
                      <select
                        value={form.insuranceType}
                        onChange={(event) => {
                          updateField("insuranceType", event.target.value);
                          if (event.target.value === "آزاد") {
                            updateField("supplementaryInsurance", "");
                          }
                        }}
                        required
                      >
                        <option value="">انتخاب کنید</option>
                        {primaryTariffs.map((tariff) => (
                          <option key={tariff.id} value={tariff.insurance_type}>
                            {tariff.insurance_type} — {formatToman(tariff.tariff_price)}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      بیمه تکمیلی
                      <select
                        value={form.supplementaryInsurance}
                        onChange={(event) =>
                          updateField("supplementaryInsurance", event.target.value)
                        }
                        disabled={form.insuranceType === "آزاد"}
                      >
                        <option value="">ندارد</option>
                        {supplementaryTariffs.map((tariff) => (
                          <option key={tariff.id} value={tariff.insurance_type}>
                            {tariff.insurance_type} — {formatToman(tariff.tariff_price)}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>

                  <label>
                    یادداشت پذیرش
                    <textarea
                      rows={3}
                      value={form.notes}
                      onChange={(event) => updateField("notes", event.target.value)}
                      placeholder="اختیاری"
                    />
                  </label>

                  <button
                    className={styles.primaryButton}
                    type="submit"
                    disabled={submitting || primaryTariffs.length === 0}
                  >
                    {submitting ? "در حال ثبت…" : "بازکردن فاکتور"}
                  </button>
                </form>
              </section>

              <section className={styles.card} aria-labelledby="open-invoices-title">
                <div className={styles.cardHeader}>
                  <h2 id="open-invoices-title">فاکتورهای باز</h2>
                  <button
                    type="button"
                    className={styles.refreshButton}
                    onClick={fetchAccounting}
                    disabled={loading}
                  >
                    تازه‌سازی
                  </button>
                </div>

                {loading ? (
                  <div className={styles.stateBox} role="status">
                    در حال بارگذاری…
                  </div>
                ) : invoices.length === 0 ? (
                  <div className={styles.stateBox}>فاکتور بازی وجود ندارد.</div>
                ) : (
                  <div className={styles.tableWrap}>
                    <table>
                      <thead>
                        <tr>
                          <th>شماره</th>
                          <th>بیمار</th>
                          <th>بیمه</th>
                          <th>تاریخ</th>
                          <th>مبلغ</th>
                          <th>عملیات</th>
                        </tr>
                      </thead>
                      <tbody>
                        {invoices.map((invoice) => (
                          <tr key={invoice.id}>
                            <td>{toFarsiDigits(invoice.id)}</td>
                            <td>
                              <strong>{invoice.patient_full_name}</strong>
                              <small dir="ltr">{invoice.phone_number || "—"}</small>
                            </td>
                            <td>
                              {invoice.insurance_type || "—"}
                              {invoice.supplementary_insurance && (
                                <small>{invoice.supplementary_insurance}</small>
                              )}
                            </td>
                            <td>{formatJalali(invoice.work_date || invoice.opened_at)}</td>
                            <td>{formatToman(invoice.total_amount)}</td>
                            <td>
                              <button
                                type="button"
                                className={styles.closeButton}
                                disabled={closing[invoice.id]}
                                onClick={() =>
                                  handleClose(invoice.id, invoice.patient_full_name)
                                }
                                aria-label={`بستن فاکتور ${invoice.id} بیمار ${invoice.patient_full_name}`}
                              >
                                {closing[invoice.id] ? "…" : "بستن"}
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            </div>

            <p className={styles.safetyNote}>
              در این برش فقط فاکتور ویزیت بسته می‌شود. بستن فاکتور دارای تزریق،
              پروسیجر یا مصرفی تا انتقال و آزمون کامل قواعد مالی آن‌ها عمداً مسدود است.
            </p>
          </>
        )}
      </main>
    </div>
  );
}
