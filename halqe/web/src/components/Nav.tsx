"use client";

/** Responsive, role-aware application navigation for the unified Halqe panel. */
import { useEffect, useState } from "react";
import Link from "next/link";
import { getRole } from "@/lib/api";
import styles from "./nav.module.css";

interface NavLink {
  href: string;
  label: string;
  hint?: string;
}

export const NAV_LINKS: NavLink[] = [
  { href: "/dashboard", label: "داشبورد", hint: "نمای کلی" },
  { href: "/queue", label: "صف ویزیت", hint: "جریان پزشک" },
  { href: "/patients", label: "بیماران", hint: "پرونده‌ها" },
  { href: "/worklist", label: "پیگیری‌ها", hint: "کارهای باز" },
];

export const ACCOUNTING_LINKS: NavLink[] = [
  { href: "/accounting", label: "پذیرش", hint: "بیمار و ویزیت" },
  { href: "/accounting/invoices", label: "فاکتورها", hint: "مشاهده و اصلاح" },
  { href: "/accounting/nursing", label: "پرستاری", hint: "خدمت و مصرفی" },
  { href: "/accounting/procedures", label: "پروسیجر", hint: "پزشک و پرستار" },
  { href: "/accounting/payments", label: "تسویه", hint: "پرداخت و بستن" },
];

export const MANAGER_LINKS: NavLink[] = [
  { href: "/control-room", label: "اتاقِ کنترل", hint: "اولویت‌بندی جمعیت" },
  { href: "/manager/outcomes", label: "گزارشِ outcome", hint: "نتایج درمان" },
  { href: "/manager/engagement", label: "صفِ تعامل", hint: "تأیید و ارسال" },
  { href: "/accounting/reports", label: "گزارش‌های مالی", hint: "درآمد و عملکرد" },
  { href: "/accounting/payroll", label: "محاسبه حقوق", hint: "شیفت و سهم خدمات" },
  { href: "/accounting/settings", label: "تنظیمات مالی", hint: "تعرفه و قرارداد" },
];

interface NavProps {
  currentPath: string;
  pageTitle?: string;
  onLogout: () => void;
  showManagerLinks?: boolean;
}

function isLinkActive(href: string, currentPath: string): boolean {
  const isAccountingRoot = href === "/accounting";
  return currentPath === href || (!isAccountingRoot && currentPath.startsWith(`${href}/`));
}

function NavItem({ link, currentPath, onNavigate }: {
  link: NavLink;
  currentPath: string;
  onNavigate: () => void;
}) {
  const active = isLinkActive(link.href, currentPath);
  return (
    <Link
      href={link.href}
      className={active ? `${styles.navLink} ${styles.navLinkActive}` : styles.navLink}
      aria-current={active ? "page" : undefined}
      onClick={onNavigate}
    >
      <span>{link.label}</span>
      {link.hint && <small>{link.hint}</small>}
    </Link>
  );
}

function NavGroup({ label, ariaLabel, links, currentPath, onNavigate }: {
  label: string;
  ariaLabel: string;
  links: NavLink[];
  currentPath: string;
  onNavigate: () => void;
}) {
  const active = links.some((link) => isLinkActive(link.href, currentPath));
  return (
    <details className={styles.group} aria-label={ariaLabel}>
      <summary className={active ? `${styles.groupSummary} ${styles.groupActive}` : styles.groupSummary}>
        <span>{label}</span>
        <span className={styles.chevron} aria-hidden="true">⌄</span>
      </summary>
      <div className={styles.groupPanel}>
        {links.map((link) => (
          <NavItem key={link.href} link={link} currentPath={currentPath} onNavigate={onNavigate} />
        ))}
      </div>
    </details>
  );
}

export default function Nav({ currentPath, pageTitle, onLogout, showManagerLinks }: NavProps) {
  const [role, setRole] = useState<string | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    setRole(getRole());
  }, []);

  useEffect(() => {
    setMobileOpen(false);
  }, [currentPath]);

  const showAccounting = role === "admin" || role === "manager" || role === "reception";
  const showMgr = showManagerLinks ?? (role === "manager" || role === "admin");
  const closeMobile = () => setMobileOpen(false);

  return (
    <header className={styles.topbar} role="banner">
      <div className={styles.headerRow}>
        <Link href="/dashboard" className={styles.brand} aria-label="صفحه اصلی حلقه">
          <span className={styles.brandMark} aria-hidden="true">ح</span>
          <span className={styles.brandText}>
            <strong>حلقه</strong>
            <small>سامانه یکپارچه درمانگاه</small>
          </span>
        </Link>

        {pageTitle && (
          <span className={styles.pageTitle} aria-label={`صفحهٔ جاری: ${pageTitle}`}>
            {pageTitle}
          </span>
        )}

        <button
          type="button"
          className={styles.menuButton}
          aria-expanded={mobileOpen}
          aria-controls="halqe-main-navigation"
          onClick={() => setMobileOpen((open) => !open)}
        >
          <span aria-hidden="true">☰</span>
          منو
        </button>

        <button onClick={onLogout} className={styles.logoutBtn} aria-label="خروج از سامانه" type="button">
          خروج
        </button>
      </div>

      <nav
        id="halqe-main-navigation"
        className={mobileOpen ? `${styles.nav} ${styles.navOpen}` : styles.nav}
        aria-label="ناوبری اصلی"
      >
        <div className={styles.primaryLinks} aria-label="عملیات روزانه">
          {NAV_LINKS.map((link) => (
            <NavItem key={link.href} link={link} currentPath={currentPath} onNavigate={closeMobile} />
          ))}
        </div>

        {showAccounting && (
          <NavGroup label="حسابداری" ariaLabel="حسابداری" links={ACCOUNTING_LINKS} currentPath={currentPath} onNavigate={closeMobile} />
        )}

        {showMgr && (
          <NavGroup label="مدیریت" ariaLabel="مدیریت" links={MANAGER_LINKS} currentPath={currentPath} onNavigate={closeMobile} />
        )}
      </nav>
    </header>
  );
}
