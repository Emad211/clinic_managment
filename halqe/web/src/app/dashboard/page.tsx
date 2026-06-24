"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter, usePathname } from "next/navigation";
import Link from "next/link";
import {
  apiGetPatients,
  apiGetWorklist,
  clearToken,
  getToken,
  ApiError,
} from "@/lib/api";
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
  const router = useRouter();
  const pathname = usePathname();

  // Stats state
  const [patientsTotal, setPatientsTotal] = useState<number | null>(null);
  const [patientsLoading, setPatientsLoading] = useState(true);
  const [patientsError, setPatientsError] = useState<string | null>(null);

  const [worklistTotal, setWorklistTotal] = useState<number | null>(null);
  const [worklistLoading, setWorklistLoading] = useState(true);
  const [worklistError, setWorklistError] = useState<string | null>(null);

  const handle401 = useCallback(() => {
    clearToken();
    router.push("/login");
  }, [router]);

  function handleLogout() {
    clearToken();
    router.push("/login");
  }

  // Fetch patients total (limit=1 is enough — we only need `total`)
  const fetchPatients = useCallback(async () => {
    setPatientsLoading(true);
    setPatientsError(null);
    try {
      const data = await apiGetPatients(1, 0);
      setPatientsTotal(data.total);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        handle401();
        return;
      }
      setPatientsError("خطا در دریافت");
    } finally {
      setPatientsLoading(false);
    }
  }, [handle401]);

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
        handle401();
        return;
      }
      setWorklistError("خطا در دریافت");
    } finally {
      setWorklistLoading(false);
    }
  }, [handle401]);

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    // Fire both in parallel
    fetchPatients();
    fetchWorklist();
  }, [fetchPatients, fetchWorklist, router]);

  return (
    <div className={styles.layout}>
      <Nav
        currentPath={pathname ?? "/dashboard"}
        onLogout={handleLogout}
      />

      <main className={styles.main} id="main-content" aria-label="داشبورد حلقه">

        {/* Hero / brand heading */}
        <div className={styles.hero} role="banner">
          <h1 className={styles.heroTitle}>حلقه</h1>
          <p className={styles.heroSub}>سامانهٔ هوشمند مراقبت از بیماران مزمن</p>
        </div>

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

      </main>
    </div>
  );
}
