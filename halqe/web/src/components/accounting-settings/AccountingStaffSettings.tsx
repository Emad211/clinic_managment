"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { ApiError } from "@/lib/api";
import {
  apiSaveAccountingStaff,
  type AccountingAdminConfigurationDTO,
  type AccountingAdminStaffDTO,
} from "@/lib/api/accounting-admin";
import styles from "@/app/accounting/settings/settings.module.css";

interface Props {
  config: AccountingAdminConfigurationDTO;
  onChanged: (message: string) => Promise<void> | void;
  onError: (message: string | null) => void;
}

const EMPTY = {
  id: null as number | null,
  full_name: "",
  staff_type: "doctor" as "doctor" | "nurse",
  is_active: true,
};

export function AccountingStaffSettings({ config, onChanged, onError }: Props) {
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    onError(null);
    try {
      await apiSaveAccountingStaff(form);
      setForm(EMPTY);
      await onChanged("کادر درمان با audit ذخیره شد.");
    } catch (error) {
      onError(error instanceof ApiError ? error.message : "ذخیره کادر ناموفق بود.");
    } finally {
      setBusy(false);
    }
  }

  function edit(item: AccountingAdminStaffDTO) {
    setForm({
      id: item.id,
      full_name: item.full_name,
      staff_type: item.staff_type,
      is_active: item.is_active,
    });
  }

  return (
    <div className={styles.workspaceGrid}>
      <form className={styles.formCard} onSubmit={submit}>
        <div className={styles.cardHeader}>
          <div>
            <h2>{form.id ? "ویرایش کادر" : "افزودن کادر"}</h2>
            <p>غیرفعال‌سازی به‌جای حذف، سوابق مالی را حفظ می‌کند.</p>
          </div>
          {form.id && (
            <button type="button" onClick={() => setForm(EMPTY)}>فرم جدید</button>
          )}
        </div>
        <label>
          نام و نام خانوادگی
          <input
            value={form.full_name}
            onChange={(event) => setForm((current) => ({ ...current, full_name: event.target.value }))}
            required
          />
        </label>
        <label>
          نقش
          <select
            value={form.staff_type}
            onChange={(event) => setForm((current) => ({ ...current, staff_type: event.target.value as "doctor" | "nurse" }))}
          >
            <option value="doctor">پزشک</option>
            <option value="nurse">پرستار</option>
          </select>
        </label>
        <label className={styles.check}>
          <input
            type="checkbox"
            checked={form.is_active}
            onChange={(event) => setForm((current) => ({ ...current, is_active: event.target.checked }))}
          />
          فعال
        </label>
        <button className={styles.primaryButton} disabled={busy}>
          {busy ? "در حال ذخیره…" : "ذخیره کادر"}
        </button>
      </form>

      <div className={styles.listCard}>
        <div className={styles.cardHeader}>
          <div><h2>کادر درمان</h2><p>{config.staff.length} رکورد</p></div>
        </div>
        <div className={styles.rowList}>
          {config.staff.map((item) => (
            <article key={item.id} className={!item.is_active ? styles.inactiveRow : ""}>
              <div>
                <strong>{item.full_name}</strong>
                <span>{item.staff_type === "doctor" ? "پزشک" : "پرستار"} · {item.is_active ? "فعال" : "غیرفعال"}</span>
              </div>
              <button type="button" onClick={() => edit(item)}>ویرایش</button>
            </article>
          ))}
          {config.staff.length === 0 && <div className={styles.empty}>کادر درمانی تعریف نشده است.</div>}
        </div>
      </div>
    </div>
  );
}
