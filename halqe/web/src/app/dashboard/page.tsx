"use client";

import { useEffect, useState, useCallback } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import {
  apiGetPatients,
  apiGetWorklist,
  getRole,
  ApiError,
} from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";
import { toFarsiDigits } from "@/lib/jalali";
import Nav from "@/components/Nav";
import styles from "./dashboard.module.css";

// ─────────────────────────────────────────────────────────────
// Stat card — shows a label + numeric value with loading/error states
// ─────────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  loading,
  error,
  warn,
}: {
  label: string;
  value: number | null;
  loading: boolean;
  error: string | null;
  warn?: boolean;
}) {
  return (
    <div className={styles.statCard} role="region" aria-label={label}>
      <span className={styles.statLabel}>{label}</span>
      {loading && (
        <span className={styles.statLoading} aria-label="در حال بارگذاری" aria-live="polite">
          <span className={styles.spinner} aria-hidden="true" />
        </span>
      )}
      {!loading && error && (
        <span className={styles.statError} role="alert">{error}</span>
      )}
      {!loading && !error && value !== null && (
        <span
          className={`${styles.statValue}${warn ? ` ${styles.statValueWarn}` : ""}`}
          aria-label={`${toFarsiDigits(value)} ${label}`}
        >
          {toFarsiDigits(value)}
        </span>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Nav card — a link card to a main section
// ─────────────────────────────────────────────────────────────

function NavCard({
  href,
  icon,
  title,
  desc,
}: {
  href: string;
  icon: string;
  title: string;
  desc: string;
}) {
  return (
    <Link href={href} className={styles.navCard}>
      <span className={styles.navCardIcon} aria-hidden="true">
        {icon}
      </span>
      <span className={styles.navCardTitle}>{title}</span>
      <span className={styles.navCardDesc}>{desc}</span>
    </Link>
  );
}

// ─────────────────────────────────────────────────────────────
// Dashboard page
// ─────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const { ready, logout } = useAuth();
  const pathname = usePathname();

  // Role gate — hydration-safe (start null, resolve in effect, never in render).
  // Pattern mirrors manager/outcomes/page.tsx.
  const [role, setRole] = useState<string | null>(null);

  // Stats state
  const [patientsTotal, setPatientsTotal] = useState<number | null>(null);
  const [patientsLoading, setPatientsLoading] = useState(true);
  const [patientsError, setPatientsError] = useState<string | null>(null);

  const [worklistTotal, setWorklistTotal] = useState<number | null>(null);
  const [worklistLoading, setWorklistLoading] = useState(true);
  const [worklistError, setWorklistError] = useState<string | null>(null);

  // Fetch patients total (limit=1 is enough — we only need `total`)
  const fetchPatients = useCallback(async () => {
    setPatientsLoading(true);
    setPatientsError(null);
    try {
      const data = await apiGetPatients(1, 0);
      setPatientsTotal(data.total);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setPatientsError("خطا در دریافت");
    } finally {
      setPatientsLoading(false);
    }
  }, [logout]);

  // Fetch open worklist total (default filter = open/due)
  const fetchWorklist = useCallback(async () => {
    setWorklistLoading(true);
    setWorklistError(null);
    try {
      // No status param → backend default = open + due tasks
      const data = await apiGetWorklist({ limit: 1, offset: 0 });
      setWorklistTotal(data.total);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setWorklistError("خطا در دریافت");
    } finally {
      setWorklistLoading(false);
    }
  }, [logout]);

  // Fire data fetches only once the auth guard has confirmed a valid token
  useEffect(() => {
    if (!ready) return;
    setRole(getRole());
    fetchPatients();
    fetchWorklist();
  }, [ready, fetchPatients, fetchWorklist]);

  const isManager = role === "manager";

  // Auth guard: render nothing while useAuth is checking/redirecting
  if (!ready) return null;

  return (
    <div className={styles.layout}>
      <Nav
        currentPath={pathname ?? "/dashboard"}
        onLogout={logout}
      />

      <main className={styles.main} id="main-content" aria-label="داشبورد حلقه">

        {/* Hero / brand heading */}
        <div className={styles.hero} role="banner">
          <h1 className={styles.heroTitle}>حلقه</h1>
          <p className={styles.heroSub}>سامانهٔ هوشمند مراقبت از بیماران مزمن</p>
        </div>

        {/* First action of the day — role-aware, full-width. No fabricated
            numbers: just a label + a link to the right starting surface. */}
        <Link
          href={isManager ? "/control-room" : "/queue"}
          className={styles.primaryAction}
          aria-label={
            isManager
              ? "اتاقِ کنترل — بیمارانِ پراولویت"
              : "صف ویزیتِ امروز"
          }
        >
          <span className={styles.primaryActionEyebrow}>اقدامِ اولِ روز</span>
          <span className={styles.primaryActionTitle}>
            {isManager ? "اتاقِ کنترل — بیمارانِ پراولویت" : "صف ویزیتِ امروز"}
          </span>
          <span className={styles.primaryActionDesc}>
            {isManager
              ? "کوهورتِ اولویت‌بندی‌شده برای تماس و پیگیری"
              : "بیمارانِ در صفِ ویزیتِ امروز را ببینید"}
          </span>
        </Link>

        {/* Stats */}
        <p className={styles.sectionHeading} aria-hidden="true">خلاصهٔ وضعیت</p>
        <div className={styles.statsRow}>
          <StatCard
            label="بیماران ثبت‌نام‌شده"
            value={patientsTotal}
            loading={patientsLoading}
            error={patientsError}
          />
          <StatCard
            label="پیگیری‌های سررسیدشده"
            value={worklistTotal}
            loading={worklistLoading}
            error={worklistError}
            warn={worklistTotal !== null && worklistTotal > 0}
          />
        </div>

        {/* Navigation cards */}
        <p className={styles.sectionHeading} aria-hidden="true">دسترسی سریع</p>
        <nav className={styles.navCardRow} aria-label="دسترسی سریع به بخش‌ها">
          <NavCard
            href="/patients"
            icon="◈"
            title="بیماران"
            desc="مشاهده و جستجوی پرونده‌های بیماران مزمن"
          />
          <NavCard
            href="/worklist"
            icon="◉"
            title="پیگیری‌ها"
            desc="لیست پیگیری‌های باز و سررسیدشده"
          />
        </nav>

        {/* Manager-only block — rendered only for managers. Guarded on the
            resolved role so it never flashes for staff (role === null → hidden). */}
        {isManager && (
          <section className={styles.managerSection} aria-label="مدیریت">
            <p className={styles.sectionHeading}>مدیریت</p>
            <nav className={styles.navCardRow} aria-label="ابزارهای مدیریتی">
              <NavCard
                href="/control-room"
                icon="◎"
                title="اتاقِ کنترل"
                desc="کوهورتِ پراولویت برای تماس و پیگیری"
              />
              <NavCard
                href="/manager/outcomes"
                icon="◧"
                title="گزارشِ outcome"
                desc="گزارش‌های توصیفیِ فعالیت و وضعیتِ بیماران"
              />
              <NavCard
                href="/manager/engagement"
                icon="◍"
                title="صفِ تعامل"
                desc="پیکربندیِ رویداد و صفِ پیام‌ها"
              />
            </nav>
          </section>
        )}

      </main>
    </div>
  );
}
