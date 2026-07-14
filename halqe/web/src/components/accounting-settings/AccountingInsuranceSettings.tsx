"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { ApiError } from "@/lib/api";
import {
  apiSaveAccountingInsuranceScheme,
  apiSaveAccountingVisitTariff,
  type AccountingAdminConfigurationDTO,
  type AccountingAdminVisitTariffDTO,
  type AccountingInsuranceSchemeDTO,
} from "@/lib/api/accounting-admin";
import { formatToman } from "@/lib/jalali";
import styles from "@/app/accounting/settings/settings.module.css";

interface Props {
  config: AccountingAdminConfigurationDTO;
  onChanged: (message: string) => Promise<void> | void;
  onError: (message: string | null) => void;
}

const EMPTY_SCHEME = {
  id: null as number | null,
  code: "",
  name: "",
  is_supplementary: false,
  is_base: false,
  is_active: true,
};
const EMPTY_TARIFF = {
  id: null as number | null,
  insurance_type: "",
  insurance_scheme_id: null as number | null,
  tariff_price: "0",
  nursing_tariff: "0",
  nursing_covers: false,
  is_active: true,
  is_supplementary: false,
  is_base_tariff: false,
};

function money(value: string): number {
  const number = Number(value);
  return Number.isFinite(number) ? Math.trunc(number) : 0;
}

export function AccountingInsuranceSettings({ config, onChanged, onError }: Props) {
  const [scheme, setScheme] = useState(EMPTY_SCHEME);
  const [tariff, setTariff] = useState(EMPTY_TARIFF);
  const [busy, setBusy] = useState<string | null>(null);

  async function saveScheme(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("scheme");
    onError(null);
    try {
      await apiSaveAccountingInsuranceScheme(scheme);
      setScheme(EMPTY_SCHEME);
      await onChanged("بیمه ذخیره شد.");
    } catch (error) {
      onError(error instanceof ApiError ? error.message : "ذخیره بیمه ناموفق بود.");
    } finally {
      setBusy(null);
    }
  }

  async function saveTariff(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("tariff");
    onError(null);
    try {
      await apiSaveAccountingVisitTariff({
        ...tariff,
        tariff_price: money(tariff.tariff_price),
        nursing_tariff: money(tariff.nursing_tariff),
      });
      setTariff(EMPTY_TARIFF);
      await onChanged("تعرفه و سیاست پوشش بیمه ذخیره شد.");
    } catch (error) {
      onError(error instanceof ApiError ? error.message : "ذخیره تعرفه ناموفق بود.");
    } finally {
      setBusy(null);
    }
  }

  function editScheme(item: AccountingInsuranceSchemeDTO) {
    setScheme({
      id: item.id,
      code: item.code,
      name: item.name,
      is_supplementary: item.is_supplementary,
      is_base: item.is_base,
      is_active: item.is_active,
    });
  }

  function editTariff(item: AccountingAdminVisitTariffDTO) {
    setTariff({
      id: item.id,
      insurance_type: item.insurance_type,
      insurance_scheme_id: item.insurance_scheme_id,
      tariff_price: String(item.tariff_price),
      nursing_tariff: String(item.nursing_tariff),
      nursing_covers: item.nursing_covers,
      is_active: item.is_active,
      is_supplementary: item.is_supplementary,
      is_base_tariff: item.is_base_tariff,
    });
  }

  return (
    <div className={styles.stack}>
      <div className={styles.workspaceGrid}>
        <form className={styles.formCard} onSubmit={saveScheme}>
          <div className={styles.cardHeader}>
            <div><h2>{scheme.id ? "ویرایش بیمه" : "تعریف بیمه"}</h2><p>کد ماشین‌خوان مستقل از نام نمایشی است.</p></div>
            {scheme.id && <button type="button" onClick={() => setScheme(EMPTY_SCHEME)}>فرم جدید</button>}
          </div>
          <div className={styles.twoColumns}>
            <label>کد<input dir="ltr" value={scheme.code} onChange={(event) => setScheme((current) => ({ ...current, code: event.target.value }))} required /></label>
            <label>نام<input value={scheme.name} onChange={(event) => setScheme((current) => ({ ...current, name: event.target.value }))} required /></label>
          </div>
          <div className={styles.checkRow}>
            <label className={styles.check}><input type="checkbox" checked={scheme.is_base} onChange={(event) => setScheme((current) => ({ ...current, is_base: event.target.checked }))} /> پایه</label>
            <label className={styles.check}><input type="checkbox" checked={scheme.is_supplementary} onChange={(event) => setScheme((current) => ({ ...current, is_supplementary: event.target.checked }))} /> تکمیلی</label>
            <label className={styles.check}><input type="checkbox" checked={scheme.is_active} onChange={(event) => setScheme((current) => ({ ...current, is_active: event.target.checked }))} /> فعال</label>
          </div>
          <button className={styles.primaryButton} disabled={busy !== null}>{busy === "scheme" ? "در حال ذخیره…" : "ذخیره بیمه"}</button>
        </form>

        <div className={styles.listCard}>
          <div className={styles.cardHeader}><div><h2>بیمه‌ها</h2><p>پایه، تکمیلی و آزاد</p></div></div>
          <div className={styles.rowList}>
            {config.insurance_schemes.map((item) => (
              <article key={item.id} className={!item.is_active ? styles.inactiveRow : ""}>
                <div><strong>{item.name}</strong><span dir="ltr">{item.code}</span></div>
                <button type="button" onClick={() => editScheme(item)}>ویرایش</button>
              </article>
            ))}
            {config.insurance_schemes.length === 0 && <div className={styles.empty}>بیمه‌ای تعریف نشده است.</div>}
          </div>
        </div>
      </div>

      <section className={styles.fullCard}>
        <div className={styles.cardHeader}>
          <div><h2>تعرفه و پوشش بیمه</h2><p>قیمت ویزیت و سیاست پرستاری فاکتورهای آینده</p></div>
          {tariff.id && <button type="button" onClick={() => setTariff(EMPTY_TARIFF)}>فرم جدید</button>}
        </div>
        <form className={styles.tariffForm} onSubmit={saveTariff}>
          <label>نام تعرفه<input value={tariff.insurance_type} onChange={(event) => setTariff((current) => ({ ...current, insurance_type: event.target.value }))} required /></label>
          <label>بیمه<select value={tariff.insurance_scheme_id ?? ""} onChange={(event) => setTariff((current) => ({ ...current, insurance_scheme_id: event.target.value ? Number(event.target.value) : null }))}><option value="">بدون اتصال</option>{config.insurance_schemes.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
          <label>تعرفه ویزیت<input inputMode="numeric" dir="ltr" value={tariff.tariff_price} onChange={(event) => setTariff((current) => ({ ...current, tariff_price: event.target.value }))} /></label>
          <label>تعرفه پرستاری<input inputMode="numeric" dir="ltr" value={tariff.nursing_tariff} onChange={(event) => setTariff((current) => ({ ...current, nursing_tariff: event.target.value }))} /></label>
          <div className={styles.checkRow}>
            <label className={styles.check}><input type="checkbox" checked={tariff.nursing_covers} onChange={(event) => setTariff((current) => ({ ...current, nursing_covers: event.target.checked }))} /> پوشش پرستاری</label>
            <label className={styles.check}><input type="checkbox" checked={tariff.is_base_tariff} onChange={(event) => setTariff((current) => ({ ...current, is_base_tariff: event.target.checked }))} /> پایه</label>
            <label className={styles.check}><input type="checkbox" checked={tariff.is_supplementary} onChange={(event) => setTariff((current) => ({ ...current, is_supplementary: event.target.checked }))} /> تکمیلی</label>
            <label className={styles.check}><input type="checkbox" checked={tariff.is_active} onChange={(event) => setTariff((current) => ({ ...current, is_active: event.target.checked }))} /> فعال</label>
          </div>
          <button className={styles.primaryButton} disabled={busy !== null}>{busy === "tariff" ? "در حال ذخیره…" : "ذخیره تعرفه"}</button>
        </form>
        <div className={styles.tableWrap}>
          <table>
            <thead><tr><th>تعرفه</th><th>ویزیت</th><th>پرستاری</th><th>پوشش</th><th>نوع</th><th /></tr></thead>
            <tbody>
              {config.visit_tariffs.map((item) => (
                <tr key={item.id}>
                  <td>{item.insurance_type}</td><td>{formatToman(item.tariff_price)}</td><td>{formatToman(item.nursing_tariff)}</td>
                  <td>{item.nursing_covers ? "دارد" : "ندارد"}</td><td>{item.is_supplementary ? "تکمیلی" : item.is_base_tariff ? "پایه" : "عادی"}</td>
                  <td><button type="button" onClick={() => editTariff(item)}>ویرایش</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
