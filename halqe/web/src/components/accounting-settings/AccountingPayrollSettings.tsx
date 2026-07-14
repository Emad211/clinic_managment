"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { ApiError } from "@/lib/api";
import {
  apiSaveAccountingPayrollSettings,
  type AccountingAdminConfigurationDTO,
  type AccountingPayrollSettingDTO,
} from "@/lib/api/accounting-admin";
import { formatToman, toFarsiDigits } from "@/lib/jalali";
import styles from "@/app/accounting/settings/settings.module.css";

interface Props {
  config: AccountingAdminConfigurationDTO;
  onChanged: (message: string) => Promise<void> | void;
  onError: (message: string | null) => void;
}

const EMPTY = {
  staff_id: "",
  base_morning: "0",
  base_evening: "0",
  base_night: "0",
  visit_fee: "0",
  injection_percent: "0",
  procedure_percent: "0",
  tax_percent: "0",
  nursing_percent: "0",
  nurse_procedure_percent: "0",
};

function integer(value: string): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.trunc(parsed) : 0;
}

function decimal(value: string): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function AccountingPayrollSettings({ config, onChanged, onError }: Props) {
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    onError(null);
    try {
      await apiSaveAccountingPayrollSettings({
        staff_id: Number(form.staff_id),
        base_morning: integer(form.base_morning),
        base_evening: integer(form.base_evening),
        base_night: integer(form.base_night),
        visit_fee: integer(form.visit_fee),
        injection_percent: decimal(form.injection_percent),
        procedure_percent: decimal(form.procedure_percent),
        tax_percent: decimal(form.tax_percent),
        nursing_percent: decimal(form.nursing_percent),
        nurse_procedure_percent: decimal(form.nurse_procedure_percent),
      });
      setForm(EMPTY);
      await onChanged("قرارداد حقوق و درصدها با audit ذخیره شد.");
    } catch (error) {
      onError(error instanceof ApiError ? error.message : "ذخیره قرارداد حقوق ناموفق بود.");
    } finally {
      setBusy(false);
    }
  }

  function edit(row: AccountingPayrollSettingDTO) {
    setForm({
      staff_id: String(row.staff_id),
      base_morning: String(row.base_morning),
      base_evening: String(row.base_evening),
      base_night: String(row.base_night),
      visit_fee: String(row.visit_fee),
      injection_percent: String(row.injection_percent),
      procedure_percent: String(row.procedure_percent),
      tax_percent: String(row.tax_percent),
      nursing_percent: String(row.nursing_percent),
      nurse_procedure_percent: String(row.nurse_procedure_percent),
    });
  }

  return (
    <div className={styles.workspaceGridWide}>
      <form className={styles.formCard} onSubmit={submit}>
        <div className={styles.cardHeader}>
          <div><h2>قرارداد حقوق</h2><p>مبالغ تومان و درصدها بین صفر تا صد</p></div>
          {form.staff_id && <button type="button" onClick={() => setForm(EMPTY)}>فرم جدید</button>}
        </div>
        <label>
          کادر درمان
          <select value={form.staff_id} onChange={(event) => setForm((current) => ({ ...current, staff_id: event.target.value }))} required>
            <option value="">انتخاب کادر</option>
            {config.staff.filter((row) => row.is_active).map((row) => (
              <option key={row.id} value={row.id}>{row.full_name} · {row.staff_type === "doctor" ? "پزشک" : "پرستار"}</option>
            ))}
          </select>
        </label>

        <div className={styles.twoColumns}>
          <label>پایه صبح<input inputMode="numeric" dir="ltr" value={form.base_morning} onChange={(event) => setForm((current) => ({ ...current, base_morning: event.target.value }))} /></label>
          <label>پایه عصر<input inputMode="numeric" dir="ltr" value={form.base_evening} onChange={(event) => setForm((current) => ({ ...current, base_evening: event.target.value }))} /></label>
          <label>پایه شب<input inputMode="numeric" dir="ltr" value={form.base_night} onChange={(event) => setForm((current) => ({ ...current, base_night: event.target.value }))} /></label>
          <label>حق ویزیت<input inputMode="numeric" dir="ltr" value={form.visit_fee} onChange={(event) => setForm((current) => ({ ...current, visit_fee: event.target.value }))} /></label>
        </div>

        <div className={styles.twoColumns}>
          <label>درصد تزریق<input inputMode="decimal" dir="ltr" value={form.injection_percent} onChange={(event) => setForm((current) => ({ ...current, injection_percent: event.target.value }))} /></label>
          <label>درصد پروسیجر<input inputMode="decimal" dir="ltr" value={form.procedure_percent} onChange={(event) => setForm((current) => ({ ...current, procedure_percent: event.target.value }))} /></label>
          <label>درصد پرستاری<input inputMode="decimal" dir="ltr" value={form.nursing_percent} onChange={(event) => setForm((current) => ({ ...current, nursing_percent: event.target.value }))} /></label>
          <label>درصد پروسیجر پرستار<input inputMode="decimal" dir="ltr" value={form.nurse_procedure_percent} onChange={(event) => setForm((current) => ({ ...current, nurse_procedure_percent: event.target.value }))} /></label>
          <label>مالیات<input inputMode="decimal" dir="ltr" value={form.tax_percent} onChange={(event) => setForm((current) => ({ ...current, tax_percent: event.target.value }))} /></label>
        </div>

        <div className={styles.financialWarning} role="note">
          تغییر درصدها روی محاسبهٔ حقوق دوره‌های آینده اثر دارد. گزارش‌های بسته‌شده و snapshotهای تاریخی بازنویسی نمی‌شوند.
        </div>
        <button className={styles.primaryButton} disabled={busy}>{busy ? "در حال ذخیره…" : "ذخیره قرارداد"}</button>
      </form>

      <div className={styles.listCard}>
        <div className={styles.cardHeader}><div><h2>قراردادهای ثبت‌شده</h2><p>ویرایش هر رکورد، audit جدید ایجاد می‌کند.</p></div></div>
        <div className={styles.rowList}>
          {config.payroll_settings.map((row) => (
            <article key={row.id}>
              <div>
                <strong>{row.staff_name || `کادر #${toFarsiDigits(row.staff_id)}`}</strong>
                <span>
                  صبح {formatToman(row.base_morning)} · ویزیت {formatToman(row.visit_fee)} · مالیات {toFarsiDigits(row.tax_percent)}٪
                </span>
              </div>
              <button type="button" onClick={() => edit(row)}>ویرایش</button>
            </article>
          ))}
          {config.payroll_settings.length === 0 && <div className={styles.empty}>قرارداد حقوقی ثبت نشده است.</div>}
        </div>
      </div>
    </div>
  );
}
