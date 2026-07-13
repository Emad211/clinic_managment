"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import {
  ApiError,
  apiAddAccountingNursingItems,
  apiGetAccountingConsumableTariffs,
  apiGetAccountingNursingServices,
  apiGetAccountingShiftStaff,
  apiGetAccountingStaff,
  apiGetOpenAccountingInvoices,
  apiSetAccountingShiftStaff,
  type AccountingConsumableTariffDTO,
  type AccountingInvoiceDTO,
  type AccountingNursingServiceDTO,
  type AccountingShiftStaffDTO,
  type AccountingStaffDTO,
} from "@/lib/api";
import { formatJalali, formatToman, toFarsiDigits } from "@/lib/jalali";
import { useAuth } from "@/hooks/useAuth";
import Nav from "@/components/Nav";
import styles from "./nursing.module.css";

const SUPPORTED_VERSIONS = new Set([
  "halqe_visit_v1",
  "halqe_visit_nursing_v1",
]);

interface ConsumableDraft {
  tariffId: string;
  name: string;
  category: "drug" | "supply";
  quantity: string;
  unitPrice: string;
  patientProvided: boolean;
  isException: boolean;
}

const EMPTY_CONSUMABLE: ConsumableDraft = {
  tariffId: "",
  name: "",
  category: "supply",
  quantity: "",
  unitPrice: "",
  patientProvided: false,
  isException: false,
};

function errorText(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

export default function AccountingNursingPage() {
  const { ready, logout } = useAuth();
  const pathname = usePathname();

  const [invoices, setInvoices] = useState<AccountingInvoiceDTO[]>([]);
  const [services, setServices] = useState<AccountingNursingServiceDTO[]>([]);
  const [consumableTariffs, setConsumableTariffs] = useState<
    AccountingConsumableTariffDTO[]
  >([]);
  const [staff, setStaff] = useState<AccountingStaffDTO[]>([]);
  const [selectedInvoiceId, setSelectedInvoiceId] = useState<number | null>(null);
  const [shiftStaff, setShiftStaff] = useState<AccountingShiftStaffDTO | null>(null);
  const [doctorId, setDoctorId] = useState("");
  const [nurseId, setNurseId] = useState("");
  const [quantities, setQuantities] = useState<Record<number, string>>({});
  const [consumable, setConsumable] = useState<ConsumableDraft>(EMPTY_CONSUMABLE);
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
      const [invoiceRows, serviceRows, consumableRows, staffRows] = await Promise.all([
        apiGetOpenAccountingInvoices(200, 0),
        apiGetAccountingNursingServices(),
        apiGetAccountingConsumableTariffs(),
        apiGetAccountingStaff(),
      ]);
      setInvoices(invoiceRows.items);
      setServices(serviceRows);
      setConsumableTariffs(consumableRows);
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
      setError(errorText(err, "دریافت اطلاعات خدمات پرستاری ناموفق بود."));
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

  function setServiceQuantity(serviceId: number, value: string) {
    if (value && !/^\d{0,3}$/.test(value)) return;
    setQuantities((current) => ({ ...current, [serviceId]: value }));
  }

  function chooseConsumableTariff(value: string) {
    const tariff = consumableTariffs.find((item) => String(item.id) === value);
    if (!tariff) {
      setConsumable((current) => ({ ...current, tariffId: value }));
      return;
    }
    setConsumable((current) => ({
      ...current,
      tariffId: value,
      name: tariff.name,
      category: tariff.category,
      unitPrice: String(tariff.default_price),
    }));
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

  async function submitItems(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selectedInvoiceId === null) {
      setError("ابتدا یک فاکتور را انتخاب کنید.");
      return;
    }
    if (!shiftStaff) {
      setError("ابتدا کادر درمان شیفت را ذخیره کنید.");
      return;
    }

    const selectedServices = services
      .map((service) => ({
        service_id: service.id,
        quantity: Number(quantities[service.id] || 0),
      }))
      .filter((item) => item.quantity > 0);

    const hasConsumableFields = Boolean(
      consumable.name.trim() || consumable.quantity || consumable.unitPrice,
    );
    const consumables = [];
    if (hasConsumableFields) {
      const quantity = Number(consumable.quantity);
      const unitPrice = Number(consumable.unitPrice);
      if (!consumable.name.trim()) {
        setError("نام مصرفی الزامی است.");
        return;
      }
      if (!Number.isFinite(quantity) || quantity <= 0) {
        setError("تعداد مصرفی باید بیشتر از صفر باشد.");
        return;
      }
      if (!Number.isInteger(unitPrice) || unitPrice < 0) {
        setError("قیمت مصرفی باید یک عدد صحیح و نامنفی باشد.");
        return;
      }
      consumables.push({
        name: consumable.name.trim(),
        category: consumable.category,
        quantity,
        unit_price: unitPrice,
        patient_provided: consumable.patientProvided,
        is_exception: consumable.isException,
      });
    }

    if (selectedServices.length === 0 && consumables.length === 0) {
      setError("حداقل یک خدمت پرستاری یا مصرفی انتخاب کنید.");
      return;
    }

    setSubmitting(true);
    setError(null);
    setNotice(null);
    try {
      const result = await apiAddAccountingNursingItems(selectedInvoiceId, {
        services: selectedServices,
        consumables,
        notes: notes.trim() || null,
      });
      setQuantities({});
      setConsumable(EMPTY_CONSUMABLE);
      setNotes("");
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
      setNotice(
        `${toFarsiDigits(result.injection_ids.length)} خدمت پرستاری و ` +
          `${toFarsiDigits(result.consumable_ids.length)} مصرفی ثبت شد؛ ` +
          `مبلغ قابل پرداخت ${formatToman(result.financials.total_amount)} است.`,
      );
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setError(errorText(err, "ثبت خدمات پرستاری ناموفق بود."));
    } finally {
      setSubmitting(false);
    }
  }

  if (!ready) return null;

  return (
    <div className={styles.layout}>
      <Nav
        currentPath={pathname ?? "/accounting/nursing"}
        pageTitle="خدمات پرستاری"
        onLogout={logout}
      />
      <main className={styles.main} id="main-content">
        <header className={styles.header}>
          <div>
            <h1>خدمات پرستاری و مصرفی‌ها</h1>
            <p>ثبت کادر شیفت، خدمات پوشش‌دار و اقلام مصرفی روی فاکتور باز</p>
          </div>
          <div className={styles.headerActions}>
            <Link href="/accounting" className={styles.secondaryLink}>
              پذیرش
            </Link>
            <Link href="/accounting/payments" className={styles.secondaryLink}>
              تسویه
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
              در حال بارگذاری…
            </div>
          ) : supportedInvoices.length === 0 ? (
            <div className={styles.stateBox}>
              فاکتور قابل ارتقا به موتور خدمات پرستاری وجود ندارد.
            </div>
          ) : (
            <>
              <section className={styles.invoicePicker} aria-labelledby="invoice-title">
                <div>
                  <h2 id="invoice-title">فاکتور فعال</h2>
                  <p>فقط فاکتورهای ساخته‌شده با موتور جدید قابل انتخاب‌اند.</p>
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
                  <div><span>تاریخ کاری</span><strong>{formatJalali(selectedInvoice.work_date)}</strong></div>
                  <div><span>شیفت</span><strong>{selectedInvoice.shift || "—"}</strong></div>
                  <div><span>جمع فعلی</span><strong>{formatToman(selectedInvoice.total_amount)}</strong></div>
                </div>
              )}

              <section className={styles.card} aria-labelledby="staff-title">
                <div className={styles.cardHeader}>
                  <div>
                    <h2 id="staff-title">کادر درمان شیفت</h2>
                    <p>این انتخاب برای همهٔ آیتم‌های جدید همان تاریخ و شیفت استفاده می‌شود.</p>
                  </div>
                  {staffLoading && <span>در حال دریافت…</span>}
                </div>
                <div className={styles.staffGrid}>
                  <label>
                    پزشک
                    <select value={doctorId} onChange={(event) => setDoctorId(event.target.value)}>
                      <option value="">بدون پزشک</option>
                      {doctors.map((item) => (
                        <option key={item.id} value={item.id}>{item.full_name}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    پرستار
                    <select value={nurseId} onChange={(event) => setNurseId(event.target.value)}>
                      <option value="">بدون پرستار</option>
                      {nurses.map((item) => (
                        <option key={item.id} value={item.id}>{item.full_name}</option>
                      ))}
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

              <form onSubmit={submitItems} className={styles.form}>
                <section className={styles.card} aria-labelledby="services-title">
                  <div className={styles.cardHeader}>
                    <div>
                      <h2 id="services-title">خدمات پرستاری</h2>
                      <p>قیمت و پوشش بیمه از کاتالوگ حسابداری خوانده می‌شود.</p>
                    </div>
                  </div>
                  {services.length === 0 ? (
                    <p className={styles.emptyText}>خدمت فعالی تعریف نشده است.</p>
                  ) : (
                    <div className={styles.serviceList}>
                      {services.map((service) => (
                        <label key={service.id} className={styles.serviceRow}>
                          <span>
                            <strong>{service.service_name}</strong>
                            <small>{formatToman(service.unit_price)} برای هر واحد</small>
                          </span>
                          <input
                            value={quantities[service.id] ?? ""}
                            onChange={(event) => setServiceQuantity(service.id, event.target.value)}
                            inputMode="numeric"
                            min={0}
                            max={100}
                            placeholder="تعداد"
                            aria-label={`تعداد ${service.service_name}`}
                          />
                        </label>
                      ))}
                    </div>
                  )}
                </section>

                <section className={styles.card} aria-labelledby="consumable-title">
                  <div className={styles.cardHeader}>
                    <div>
                      <h2 id="consumable-title">مصرفی یا دارو</h2>
                      <p>یک قلم را از کاتالوگ انتخاب کنید یا مشخصات را دستی وارد کنید.</p>
                    </div>
                  </div>
                  <div className={styles.twoColumns}>
                    <label>
                      قلم کاتالوگ
                      <select value={consumable.tariffId} onChange={(event) => chooseConsumableTariff(event.target.value)}>
                        <option value="">ورود دستی</option>
                        {consumableTariffs.map((item) => (
                          <option key={item.id} value={item.id}>
                            {item.name} — {formatToman(item.default_price)}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      نام قلم
                      <input
                        value={consumable.name}
                        onChange={(event) => setConsumable((current) => ({ ...current, name: event.target.value, tariffId: "" }))}
                      />
                    </label>
                  </div>
                  <div className={styles.threeColumns}>
                    <label>
                      دسته
                      <select
                        value={consumable.category}
                        onChange={(event) => setConsumable((current) => ({
                          ...current,
                          category: event.target.value as "drug" | "supply",
                        }))}
                      >
                        <option value="supply">لوازم</option>
                        <option value="drug">دارو</option>
                      </select>
                    </label>
                    <label>
                      تعداد
                      <input
                        value={consumable.quantity}
                        onChange={(event) => setConsumable((current) => ({ ...current, quantity: event.target.value }))}
                        inputMode="decimal"
                        dir="ltr"
                        placeholder="مثلاً ۲ یا ۰.۵"
                      />
                    </label>
                    <label>
                      قیمت واحد (تومان)
                      <input
                        value={consumable.unitPrice}
                        onChange={(event) => setConsumable((current) => ({ ...current, unitPrice: event.target.value }))}
                        inputMode="numeric"
                        dir="ltr"
                      />
                    </label>
                  </div>
                  <div className={styles.checks}>
                    <label>
                      <input
                        type="checkbox"
                        checked={consumable.patientProvided}
                        onChange={(event) => setConsumable((current) => ({ ...current, patientProvided: event.target.checked }))}
                      />
                      قلم را بیمار آورده است
                    </label>
                    <label>
                      <input
                        type="checkbox"
                        checked={consumable.isException}
                        onChange={(event) => setConsumable((current) => ({ ...current, isException: event.target.checked }))}
                      />
                      قلم استثنا / خارج از کاتالوگ
                    </label>
                  </div>
                </section>

                <section className={styles.card} aria-labelledby="notes-title">
                  <label id="notes-title">
                    یادداشت مشترک
                    <textarea
                      value={notes}
                      onChange={(event) => setNotes(event.target.value)}
                      rows={3}
                      placeholder="توضیح اختیاری برای آیتم‌های این ثبت"
                    />
                  </label>
                  <div className={styles.submitRow}>
                    <p>
                      آیتم‌های ثبت‌شده تا زمان تسویه اجازهٔ بستن فاکتور را نمی‌دهند.
                    </p>
                    <button
                      type="submit"
                      className={styles.primaryButton}
                      disabled={submitting || selectedInvoiceId === null || !shiftStaff}
                    >
                      {submitting ? "در حال ثبت…" : "ثبت خدمات و مصرفی‌ها"}
                    </button>
                  </div>
                </section>
              </form>
            </>
          ))}
      </main>
    </div>
  );
}
