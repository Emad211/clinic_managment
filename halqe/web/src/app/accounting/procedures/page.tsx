"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import {
  ApiError,
  apiAddAccountingProcedureItems,
  apiGetAccountingProcedureTariffs,
  apiGetAccountingShiftStaff,
  apiGetAccountingStaff,
  apiGetOpenAccountingInvoices,
  apiSetAccountingShiftStaff,
  type AccountingInvoiceDTO,
  type AccountingProcedureTariffDTO,
  type AccountingShiftStaffDTO,
  type AccountingStaffDTO,
} from "@/lib/api";
import { formatJalali, formatToman, toFarsiDigits } from "@/lib/jalali";
import { useAuth } from "@/hooks/useAuth";
import Nav from "@/components/Nav";
import styles from "./procedures.module.css";

const SUPPORTED_VERSIONS = new Set([
  "halqe_visit_v1",
  "halqe_visit_nursing_v1",
  "halqe_visit_procedure_v1",
]);

function errorText(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

export default function AccountingProceduresPage() {
  const { ready, logout } = useAuth();
  const pathname = usePathname();

  const [invoices, setInvoices] = useState<AccountingInvoiceDTO[]>([]);
  const [tariffs, setTariffs] = useState<AccountingProcedureTariffDTO[]>([]);
  const [staff, setStaff] = useState<AccountingStaffDTO[]>([]);
  const [selectedInvoiceId, setSelectedInvoiceId] = useState<number | null>(null);
  const [shiftStaff, setShiftStaff] = useState<AccountingShiftStaffDTO | null>(null);
  const [doctorId, setDoctorId] = useState("");
  const [nurseId, setNurseId] = useState("");
  const [tariffId, setTariffId] = useState("");
  const [manualName, setManualName] = useState("");
  const [manualPrice, setManualPrice] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [performerType, setPerformerType] = useState<"doctor" | "nurse">("doctor");
  const [notes, setNotes] = useState("");
  const [loading, setLoading] = useState(true);
  const [staffLoading, setStaffLoading] = useState(false);
  const [savingStaff, setSavingStaff] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [accessDenied, setAccessDenied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const supportedInvoices = useMemo(
    () => invoices.filter((invoice) => SUPPORTED_VERSIONS.has(invoice.pricing_version)),
    [invoices],
  );
  const selectedInvoice = useMemo(
    () => supportedInvoices.find((invoice) => invoice.id === selectedInvoiceId) ?? null,
    [supportedInvoices, selectedInvoiceId],
  );
  const doctors = useMemo(
    () => staff.filter((item) => item.staff_type === "doctor"),
    [staff],
  );
  const nurses = useMemo(
    () => staff.filter((item) => item.staff_type === "nurse"),
    [staff],
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [invoiceRows, tariffRows, staffRows] = await Promise.all([
        apiGetOpenAccountingInvoices(200, 0),
        apiGetAccountingProcedureTariffs(),
        apiGetAccountingStaff(),
      ]);
      setInvoices(invoiceRows.items);
      setTariffs(tariffRows);
      setStaff(staffRows);
      const supported = invoiceRows.items.filter((invoice) =>
        SUPPORTED_VERSIONS.has(invoice.pricing_version),
      );
      setSelectedInvoiceId((current) =>
        current && supported.some((invoice) => invoice.id === current)
          ? current
          : supported[0]?.id ?? null,
      );
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
      setError(errorText(err, "دریافت اطلاعات پروسیجر ناموفق بود."));
    } finally {
      setLoading(false);
    }
  }, [logout]);

  useEffect(() => {
    if (ready) void load();
  }, [ready, load]);

  useEffect(() => {
    if (!ready || selectedInvoiceId === null) {
      setShiftStaff(null);
      setDoctorId("");
      setNurseId("");
      return;
    }
    let cancelled = false;
    setStaffLoading(true);
    apiGetAccountingShiftStaff(selectedInvoiceId)
      .then((row) => {
        if (cancelled) return;
        setShiftStaff(row);
        setDoctorId(row?.doctor_id ? String(row.doctor_id) : "");
        setNurseId(row?.nurse_id ? String(row.nurse_id) : "");
        if (!row?.doctor_id && row?.nurse_id) setPerformerType("nurse");
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          logout();
          return;
        }
        setError(errorText(err, "دریافت کادر شیفت ناموفق بود."));
      })
      .finally(() => {
        if (!cancelled) setStaffLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [ready, selectedInvoiceId, logout]);

  function chooseTariff(value: string) {
    setTariffId(value);
    const tariff = tariffs.find((item) => String(item.id) === value);
    if (tariff) {
      setManualName(tariff.name);
      setManualPrice(String(tariff.unit_price));
    } else {
      setManualName("");
      setManualPrice("");
    }
  }

  async function saveShiftStaff() {
    if (selectedInvoiceId === null) {
      setError("ابتدا یک فاکتور را انتخاب کنید.");
      return;
    }
    if (!doctorId && !nurseId) {
      setError("حداقل یک پزشک یا پرستار را انتخاب کنید.");
      return;
    }
    setSavingStaff(true);
    setError(null);
    setNotice(null);
    try {
      const row = await apiSetAccountingShiftStaff(
        selectedInvoiceId,
        doctorId ? Number(doctorId) : null,
        nurseId ? Number(nurseId) : null,
      );
      setShiftStaff(row);
      if (!row.doctor_id && row.nurse_id) setPerformerType("nurse");
      setNotice("کادر درمان این تاریخ و شیفت ذخیره شد.");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setError(errorText(err, "ذخیرهٔ کادر شیفت ناموفق بود."));
    } finally {
      setSavingStaff(false);
    }
  }

  async function submitProcedure(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selectedInvoiceId === null) {
      setError("ابتدا یک فاکتور را انتخاب کنید.");
      return;
    }
    if (!shiftStaff) {
      setError("ابتدا کادر درمان شیفت را ذخیره کنید.");
      return;
    }
    if (performerType === "doctor" && !shiftStaff.doctor_id) {
      setError("برای انجام‌دهندهٔ پزشک، پزشک شیفت باید تعیین شده باشد.");
      return;
    }
    if (performerType === "nurse" && !shiftStaff.nurse_id) {
      setError("برای انجام‌دهندهٔ پرستار، پرستار شیفت باید تعیین شده باشد.");
      return;
    }

    const numericQuantity = Number(quantity);
    if (!Number.isInteger(numericQuantity) || numericQuantity < 1 || numericQuantity > 100) {
      setError("تعداد پروسیجر باید بین ۱ و ۱۰۰ باشد.");
      return;
    }

    const selectedTariffId = tariffId ? Number(tariffId) : null;
    const numericPrice = Number(manualPrice);
    if (!selectedTariffId) {
      if (!manualName.trim()) {
        setError("نام پروسیجر الزامی است.");
        return;
      }
      if (!Number.isInteger(numericPrice) || numericPrice <= 0) {
        setError("قیمت پروسیجر باید عدد صحیح و بیشتر از صفر باشد.");
        return;
      }
    }

    setSubmitting(true);
    setError(null);
    setNotice(null);
    try {
      const result = await apiAddAccountingProcedureItems(
        selectedInvoiceId,
        [
          {
            tariff_id: selectedTariffId,
            name: selectedTariffId ? null : manualName.trim(),
            unit_price: selectedTariffId ? null : numericPrice,
            quantity: numericQuantity,
            performer_type: performerType,
          },
        ],
        notes.trim() || null,
      );
      setInvoices((current) =>
        current.map((invoice) =>
          invoice.id === selectedInvoiceId
            ? {
                ...invoice,
                pricing_version: result.pricing_version,
                total_amount: result.financials.total_amount,
              }
            : invoice,
        ),
      );
      setQuantity("1");
      setNotes("");
      setNotice(
        `${toFarsiDigits(result.procedure_ids.length)} پروسیجر ثبت شد؛ ` +
          `مبلغ قابل پرداخت ${formatToman(result.financials.total_amount)} است.`,
      );
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setError(errorText(err, "ثبت پروسیجر ناموفق بود."));
    } finally {
      setSubmitting(false);
    }
  }

  if (!ready) return null;

  return (
    <div className={styles.layout}>
      <Nav
        currentPath={pathname ?? "/accounting/procedures"}
        pageTitle="پروسیجرها"
        onLogout={logout}
      />
      <main className={styles.main} id="main-content">
        <header className={styles.header}>
          <div>
            <h1>ثبت پروسیجر</h1>
            <p>ثبت انجام‌دهنده، قیمت خام و سهم ثابت بیمار/بیمه روی فاکتور باز</p>
          </div>
          <div className={styles.headerActions}>
            <Link href="/accounting" className={styles.secondaryLink}>پذیرش</Link>
            <Link href="/accounting/nursing" className={styles.secondaryLink}>پرستاری</Link>
            <Link href="/accounting/payments" className={styles.secondaryLink}>تسویه</Link>
            <button type="button" onClick={load} disabled={loading}>تازه‌سازی</button>
          </div>
        </header>

        {accessDenied && (
          <section className={styles.errorBox} role="alert">
            این بخش فقط برای پذیرش و مدیران حسابداری در دسترس است.
          </section>
        )}
        {error && <div className={styles.errorBox} role="alert">{error}</div>}
        {notice && <div className={styles.noticeBox} role="status" aria-live="polite">{notice}</div>}

        {!accessDenied && (loading ? (
          <div className={styles.stateBox} role="status">در حال بارگذاری…</div>
        ) : supportedInvoices.length === 0 ? (
          <div className={styles.stateBox}>فاکتور قابل استفاده‌ای وجود ندارد.</div>
        ) : (
          <>
            <section className={styles.invoicePicker}>
              <div>
                <h2>فاکتور فعال</h2>
                <p>فاکتورهای legacy از این مسیر قابل تغییر نیستند.</p>
              </div>
              <select
                value={selectedInvoiceId ?? ""}
                onChange={(event) => {
                  setSelectedInvoiceId(Number(event.target.value));
                  setError(null);
                  setNotice(null);
                }}
                aria-label="انتخاب فاکتور باز"
              >
                {supportedInvoices.map((invoice) => (
                  <option key={invoice.id} value={invoice.id}>
                    #{toFarsiDigits(invoice.id)} — {invoice.patient_full_name} — {formatToman(invoice.total_amount)}
                  </option>
                ))}
              </select>
            </section>

            {selectedInvoice && (
              <div className={styles.summaryGrid}>
                <div><span>بیمار</span><strong>{selectedInvoice.patient_full_name}</strong></div>
                <div><span>بیمه</span><strong>{selectedInvoice.insurance_type || "—"}</strong></div>
                <div><span>تاریخ</span><strong>{formatJalali(selectedInvoice.work_date)}</strong></div>
                <div><span>شیفت</span><strong>{selectedInvoice.shift || "—"}</strong></div>
                <div><span>جمع فعلی</span><strong>{formatToman(selectedInvoice.total_amount)}</strong></div>
              </div>
            )}

            <section className={styles.card}>
              <div className={styles.cardHeader}>
                <div>
                  <h2>کادر درمان شیفت</h2>
                  <p>فقط انجام‌دهندهٔ واقعی روی ردیف پروسیجر ذخیره می‌شود.</p>
                </div>
                {staffLoading && <span>در حال دریافت…</span>}
              </div>
              <div className={styles.staffGrid}>
                <label>
                  پزشک
                  <select value={doctorId} onChange={(event) => setDoctorId(event.target.value)}>
                    <option value="">بدون پزشک</option>
                    {doctors.map((item) => <option key={item.id} value={item.id}>{item.full_name}</option>)}
                  </select>
                </label>
                <label>
                  پرستار
                  <select value={nurseId} onChange={(event) => setNurseId(event.target.value)}>
                    <option value="">بدون پرستار</option>
                    {nurses.map((item) => <option key={item.id} value={item.id}>{item.full_name}</option>)}
                  </select>
                </label>
                <button
                  type="button"
                  className={styles.primaryButton}
                  onClick={saveShiftStaff}
                  disabled={savingStaff || selectedInvoiceId === null}
                >
                  {savingStaff ? "…" : "ذخیرهٔ کادر شیفت"}
                </button>
              </div>
              {shiftStaff && (
                <p className={styles.staffStatus}>
                  کادر ثبت‌شده: {shiftStaff.doctor_name || "بدون پزشک"}، {shiftStaff.nurse_name || "بدون پرستار"}
                </p>
              )}
            </section>

            <form onSubmit={submitProcedure} className={styles.card}>
              <div className={styles.cardHeader}>
                <div>
                  <h2>مشخصات پروسیجر</h2>
                  <p>تعرفهٔ کاتالوگ را انتخاب کنید یا قیمت دستی production را وارد کنید.</p>
                </div>
              </div>
              <div className={styles.twoColumns}>
                <label>
                  تعرفه
                  <select value={tariffId} onChange={(event) => chooseTariff(event.target.value)}>
                    <option value="">ورود دستی</option>
                    {tariffs.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name} — {formatToman(item.unit_price)}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  انجام‌دهنده
                  <select
                    value={performerType}
                    onChange={(event) => setPerformerType(event.target.value as "doctor" | "nurse")}
                  >
                    <option value="doctor">پزشک</option>
                    <option value="nurse">پرستار</option>
                  </select>
                </label>
              </div>
              <div className={styles.threeColumns}>
                <label>
                  نام پروسیجر
                  <input
                    value={manualName}
                    onChange={(event) => {
                      setManualName(event.target.value);
                      setTariffId("");
                    }}
                    disabled={Boolean(tariffId)}
                  />
                </label>
                <label>
                  قیمت واحد (تومان)
                  <input
                    value={manualPrice}
                    onChange={(event) => {
                      setManualPrice(event.target.value);
                      setTariffId("");
                    }}
                    inputMode="numeric"
                    dir="ltr"
                    disabled={Boolean(tariffId)}
                  />
                </label>
                <label>
                  تعداد
                  <input
                    value={quantity}
                    onChange={(event) => setQuantity(event.target.value)}
                    inputMode="numeric"
                    dir="ltr"
                  />
                </label>
              </div>
              <label>
                یادداشت
                <textarea value={notes} onChange={(event) => setNotes(event.target.value)} rows={3} />
              </label>
              <div className={styles.submitRow}>
                <p>
                  پروسیجر پرستار فقط با پوشش صریح بیمه سهم بیمار صفر دارد؛ پروسیجر پزشک با قیمت کامل ثبت می‌شود.
                </p>
                <button
                  type="submit"
                  className={styles.primaryButton}
                  disabled={submitting || selectedInvoiceId === null || !shiftStaff}
                >
                  {submitting ? "در حال ثبت…" : "ثبت پروسیجر"}
                </button>
              </div>
            </form>
          </>
        ))}
      </main>
    </div>
  );
}
