"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";

import { ApiError } from "@/lib/api";
import {
  apiGetAccountingAdminConfiguration,
  type AccountingAdminConfigurationDTO,
} from "@/lib/api/accounting-admin";
import { toFarsiDigits } from "@/lib/jalali";
import { useAuth } from "@/hooks/useAuth";
import Nav from "@/components/Nav";
import { AccountingStaffSettings } from "@/components/accounting-settings/AccountingStaffSettings";
import { AccountingInsuranceSettings } from "@/components/accounting-settings/AccountingInsuranceSettings";
import { AccountingCatalogSettings } from "@/components/accounting-settings/AccountingCatalogSettings";
import { AccountingPayrollSettings } from "@/components/accounting-settings/AccountingPayrollSettings";
import styles from "./settings.module.css";


type Workspace = "staff" | "insurance" | "catalogs" | "payroll";

const WORKSPACES: Array<{ key: Workspace; label: string; hint: string }> = [
  { key: "staff", label: "کادر درمان", hint: "پزشک و پرستار" },
  { key: "insurance", label: "بیمه و تعرفه", hint: "سهم بیمار و پوشش" },
  { key: "catalogs", label: "خدمات و استثنا", hint: "کاتالوگ مالی" },
  { key: "payroll", label: "حقوق و درصدها", hint: "قرارداد کادر" },
];

function errorText(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

export default function AccountingSettingsPage() {
  const { ready, logout } = useAuth();
  const pathname = usePathname();
  const [config, setConfig] = useState<AccountingAdminConfigurationDTO | null>(null);
  const [workspace, setWorkspace] = useState<Workspace>("staff");
  const [loading, setLoading] = useState(true);
  const [accessDenied, setAccessDenied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setConfig(await apiGetAccountingAdminConfiguration());
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
      setError(errorText(err, "دریافت تنظیمات حسابداری ناموفق بود."));
    } finally {
      setLoading(false);
    }
  }, [logout]);

  useEffect(() => {
    if (ready) void load();
  }, [ready, load]);

  const metrics = useMemo(() => {
    if (!config) return { staff: 0, tariffs: 0, catalogs: 0, payroll: 0 };
    return {
      staff: config.staff.filter((item) => item.is_active).length,
      tariffs: config.visit_tariffs.filter((item) => item.is_active).length,
      catalogs: Object.values(config.catalogs)
        .flat()
        .filter((item) => item.is_active).length,
      payroll: config.payroll_settings.length,
    };
  }, [config]);

  async function changed(message: string) {
    await load();
    setNotice(message);
  }

  if (!ready) return null;

  return (
    <div className={styles.layout}>
      <Nav
        currentPath={pathname ?? "/accounting/settings"}
        pageTitle="مرکز تنظیمات مالی"
        onLogout={logout}
      />
      <main className={styles.main} id="main-content">
        <header className={styles.hero}>
          <div>
            <span className={styles.eyebrow}>ACCOUNTING CONTROL CENTER</span>
            <h1>مرکز تنظیمات حسابداری</h1>
            <p>
              کادر، بیمه، تعرفه و قرارداد حقوق را در یک مسیر audit‌شده مدیریت
              کنید. تغییرات روی فاکتورهای آینده اثر دارند و snapshotهای تاریخی
              بازنویسی نمی‌شوند.
            </p>
          </div>
          <div className={styles.heroActions}>
            <Link href="/accounting" className={styles.secondaryLink}>
              بازگشت به پذیرش
            </Link>
            <button type="button" onClick={load} disabled={loading}>
              تازه‌سازی
            </button>
          </div>
        </header>

        {accessDenied && (
          <section className={styles.errorBox} role="alert">
            این مرکز فقط برای مدیر یا ادمین قابل دسترسی است.
          </section>
        )}
        {error && <div className={styles.errorBox} role="alert">{error}</div>}
        {notice && (
          <div className={styles.noticeBox} role="status" aria-live="polite">
            {notice}
          </div>
        )}

        {!accessDenied && (
          <>
            <section className={styles.metrics} aria-label="خلاصه تنظیمات">
              <article><span>کادر فعال</span><strong>{toFarsiDigits(metrics.staff)}</strong><small>پزشک و پرستار</small></article>
              <article><span>تعرفه فعال</span><strong>{toFarsiDigits(metrics.tariffs)}</strong><small>پایه و تکمیلی</small></article>
              <article><span>خدمت فعال</span><strong>{toFarsiDigits(metrics.catalogs)}</strong><small>سه کاتالوگ مالی</small></article>
              <article><span>قرارداد حقوق</span><strong>{toFarsiDigits(metrics.payroll)}</strong><small>تنظیم‌شده</small></article>
            </section>

            <nav className={styles.workspaceNav} aria-label="بخش‌های تنظیمات">
              {WORKSPACES.map((item) => (
                <button
                  type="button"
                  key={item.key}
                  className={workspace === item.key ? styles.workspaceActive : ""}
                  onClick={() => { setWorkspace(item.key); setNotice(null); }}
                  aria-current={workspace === item.key ? "page" : undefined}
                >
                  <strong>{item.label}</strong><span>{item.hint}</span>
                </button>
              ))}
            </nav>

            {loading ? (
              <div className={styles.stateBox} role="status">در حال دریافت تنظیمات…</div>
            ) : config ? (
              <section className={styles.workspace}>
                {workspace === "staff" && <AccountingStaffSettings config={config} onChanged={changed} onError={setError} />}
                {workspace === "insurance" && <AccountingInsuranceSettings config={config} onChanged={changed} onError={setError} />}
                {workspace === "catalogs" && <AccountingCatalogSettings config={config} onChanged={changed} onError={setError} />}
                {workspace === "payroll" && <AccountingPayrollSettings config={config} onChanged={changed} onError={setError} />}
              </section>
            ) : null}
          </>
        )}
      </main>
    </div>
  );
}
