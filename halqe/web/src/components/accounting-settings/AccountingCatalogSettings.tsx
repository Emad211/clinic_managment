"use client";

import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import { ApiError } from "@/lib/api";
import {
  apiDeleteAccountingExclusion,
  apiSaveAccountingCatalogItem,
  apiSaveAccountingExclusion,
  type AccountingAdminCatalogItemDTO,
  type AccountingAdminConfigurationDTO,
  type AccountingCatalogType,
} from "@/lib/api/accounting-admin";
import { formatToman, toFarsiDigits } from "@/lib/jalali";
import styles from "@/app/accounting/settings/settings.module.css";

interface Props {
  config: AccountingAdminConfigurationDTO;
  onChanged: (message: string) => Promise<void> | void;
  onError: (message: string | null) => void;
}

const LABELS: Record<AccountingCatalogType, string> = {
  nursing: "خدمات پرستاری",
  procedure: "پروسیجرها",
  consumable: "مصرفی‌ها و داروها",
};

const EMPTY_ITEM = {
  id: null as number | null,
  name: "",
  price: "0",
  category: "supply" as "drug" | "supply",
  is_active: true,
};

const EMPTY_EXCLUSION = {
  id: null as number | null,
  insurance_type: "",
  nursing_service_id: "",
  note: "",
};

function integer(value: string): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.trunc(parsed) : 0;
}

export function AccountingCatalogSettings({ config, onChanged, onError }: Props) {
  const [catalogType, setCatalogType] = useState<AccountingCatalogType>("nursing");
  const [item, setItem] = useState(EMPTY_ITEM);
  const [exclusion, setExclusion] = useState(EMPTY_EXCLUSION);
  const [busy, setBusy] = useState<string | null>(null);

  const currentItems = config.catalogs[catalogType];
  const activeTariffs = useMemo(
    () => config.visit_tariffs.filter((row) => row.is_active && !row.is_supplementary),
    [config.visit_tariffs],
  );
  const activeNursing = useMemo(
    () => config.catalogs.nursing.filter((row) => row.is_active),
    [config.catalogs.nursing],
  );

  async function saveItem(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("catalog");
    onError(null);
    try {
      await apiSaveAccountingCatalogItem(catalogType, {
        id: item.id,
        name: item.name,
        price: integer(item.price),
        category: catalogType === "consumable" ? item.category : null,
        is_active: item.is_active,
      });
      setItem(EMPTY_ITEM);
      await onChanged(`${LABELS[catalogType]} ذخیره شد.`);
    } catch (error) {
      onError(error instanceof ApiError ? error.message : "ذخیره کاتالوگ ناموفق بود.");
    } finally {
      setBusy(null);
    }
  }

  async function saveExclusion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("exclusion");
    onError(null);
    try {
      await apiSaveAccountingExclusion({
        id: exclusion.id,
        insurance_type: exclusion.insurance_type,
        nursing_service_id: Number(exclusion.nursing_service_id),
        note: exclusion.note || null,
      });
      setExclusion(EMPTY_EXCLUSION);
      await onChanged("استثنای پوشش بیمه ذخیره شد.");
    } catch (error) {
      onError(error instanceof ApiError ? error.message : "ذخیره استثنا ناموفق بود.");
    } finally {
      setBusy(null);
    }
  }

  async function removeExclusion(id: number) {
    if (!window.confirm("این استثنای پوشش حذف شود؟ محاسبهٔ فاکتورهای آینده تغییر می‌کند.")) {
      return;
    }
    setBusy(`delete-${id}`);
    onError(null);
    try {
      await apiDeleteAccountingExclusion(id);
      await onChanged("استثنای پوشش حذف شد.");
    } catch (error) {
      onError(error instanceof ApiError ? error.message : "حذف استثنا ناموفق بود.");
    } finally {
      setBusy(null);
    }
  }

  function editItem(row: AccountingAdminCatalogItemDTO) {
    setItem({
      id: row.id,
      name: row.name,
      price: String(row.price),
      category: row.category === "drug" ? "drug" : "supply",
      is_active: row.is_active,
    });
  }

  return (
    <div className={styles.stack}>
      <div className={styles.workspaceGrid}>
        <form className={styles.formCard} onSubmit={saveItem}>
          <div className={styles.cardHeader}>
            <div>
              <h2>{item.id ? "ویرایش خدمت" : "افزودن خدمت"}</h2>
              <p>قیمت کاتالوگ فقط برای ثبت‌های آینده استفاده می‌شود.</p>
            </div>
            {item.id && <button type="button" onClick={() => setItem(EMPTY_ITEM)}>فرم جدید</button>}
          </div>
          <label>
            کاتالوگ
            <select
              value={catalogType}
              onChange={(event) => {
                setCatalogType(event.target.value as AccountingCatalogType);
                setItem(EMPTY_ITEM);
              }}
            >
              {Object.entries(LABELS).map(([key, label]) => (
                <option key={key} value={key}>{label}</option>
              ))}
            </select>
          </label>
          <label>نام<input value={item.name} onChange={(event) => setItem((current) => ({ ...current, name: event.target.value }))} required /></label>
          <label>قیمت (تومان)<input inputMode="numeric" dir="ltr" value={item.price} onChange={(event) => setItem((current) => ({ ...current, price: event.target.value }))} /></label>
          {catalogType === "consumable" && (
            <label>
              دسته
              <select value={item.category} onChange={(event) => setItem((current) => ({ ...current, category: event.target.value as "drug" | "supply" }))}>
                <option value="supply">مصرفی</option>
                <option value="drug">دارو</option>
              </select>
            </label>
          )}
          <label className={styles.check}><input type="checkbox" checked={item.is_active} onChange={(event) => setItem((current) => ({ ...current, is_active: event.target.checked }))} /> فعال</label>
          <button className={styles.primaryButton} disabled={busy !== null}>{busy === "catalog" ? "در حال ذخیره…" : "ذخیره خدمت"}</button>
        </form>

        <div className={styles.listCard}>
          <div className={styles.cardHeader}>
            <div><h2>{LABELS[catalogType]}</h2><p>{toFarsiDigits(currentItems.length)} مورد</p></div>
          </div>
          <div className={styles.rowList}>
            {currentItems.map((row) => (
              <article key={row.id} className={!row.is_active ? styles.inactiveRow : ""}>
                <div>
                  <strong>{row.name}</strong>
                  <span>{formatToman(row.price)}{row.category ? ` · ${row.category === "drug" ? "دارو" : "مصرفی"}` : ""}</span>
                </div>
                <button type="button" onClick={() => editItem(row)}>ویرایش</button>
              </article>
            ))}
            {currentItems.length === 0 && <div className={styles.empty}>موردی در این کاتالوگ تعریف نشده است.</div>}
          </div>
        </div>
      </div>

      <section className={styles.fullCard}>
        <div className={styles.cardHeader}>
          <div><h2>استثناهای پوشش پرستاری</h2><p>خدماتی که بیمار با وجود پوشش بیمه پرداخت می‌کند</p></div>
        </div>
        <form className={styles.exclusionForm} onSubmit={saveExclusion}>
          <label>
            بیمه
            <select value={exclusion.insurance_type} onChange={(event) => setExclusion((current) => ({ ...current, insurance_type: event.target.value }))} required>
              <option value="">انتخاب بیمه</option>
              {activeTariffs.map((row) => <option key={row.id} value={row.insurance_type}>{row.insurance_type}</option>)}
            </select>
          </label>
          <label>
            خدمت
            <select value={exclusion.nursing_service_id} onChange={(event) => setExclusion((current) => ({ ...current, nursing_service_id: event.target.value }))} required>
              <option value="">انتخاب خدمت</option>
              {activeNursing.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}
            </select>
          </label>
          <label>توضیح<input value={exclusion.note} onChange={(event) => setExclusion((current) => ({ ...current, note: event.target.value }))} /></label>
          <button className={styles.primaryButton} disabled={busy !== null}>{busy === "exclusion" ? "در حال ثبت…" : "ثبت استثنا"}</button>
        </form>
        <div className={styles.rowList}>
          {config.exclusions.map((row) => (
            <article key={row.id}>
              <div><strong>{row.insurance_type}</strong><span>{row.service_name || `خدمت #${toFarsiDigits(row.nursing_service_id)}`}{row.note ? ` · ${row.note}` : ""}</span></div>
              <button type="button" className={styles.dangerButton} onClick={() => removeExclusion(row.id)} disabled={busy !== null}>{busy === `delete-${row.id}` ? "…" : "حذف"}</button>
            </article>
          ))}
          {config.exclusions.length === 0 && <div className={styles.empty}>استثنای پوششی ثبت نشده است.</div>}
        </div>
      </section>
    </div>
  );
}
