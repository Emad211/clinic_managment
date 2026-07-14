"use client";

/** Shared top navigation bar for all protected pages. */
import { useEffect, useState } from "react";
import Link from "next/link";
import { getRole } from "@/lib/api";
import styles from "./nav.module.css";

interface NavLink {
  href: string;
  label: string;
}

export const NAV_LINKS: NavLink[] = [
  { href: "/dashboard", label: "داشبورد" },
  { href: "/queue", label: "صف ویزیت" },
  { href: "/patients", label: "بیماران" },
  { href: "/worklist", label: "پیگیری‌ها" },
];

/** Accounting links mirror the reception/admin backend role gate. */
export const ACCOUNTING_LINKS: NavLink[] = [
  { href: "/accounting", label: "پذیرش" },
  { href: "/accounting/invoices", label: "فاکتورها" },
  { href: "/accounting/nursing", label: "پرستاری" },
  { href: "/accounting/procedures", label: "پروسیجر" },
  { href: "/accounting/payments", label: "تسویه" },
];

export const MANAGER_LINKS: NavLink[] = [
  { href: "/control-room", label: "اتاقِ کنترل" },
  { href: "/manager/outcomes", label: "گزارشِ outcome" },
  { href: "/manager/engagement", label: "صفِ تعامل" },
  { href: "/accounting/settings", label: "تنظیمات مالی" },
];

interface NavProps {
  currentPath: string;
  pageTitle?: string;
  onLogout: () => void;
  showManagerLinks?: boolean;
}

function renderLink({ href, label }: NavLink, currentPath: string) {
  const isAccountingRoot = href === "/accounting";
  const isActive =
    currentPath === href ||
    (!isAccountingRoot && currentPath.startsWith(`${href}/`));
  return (
    <Link
      key={href}
      href={href}
      className={
        isActive ? `${styles.navLink} ${styles.navLinkActive}` : styles.navLink
      }
      aria-current={isActive ? "page" : undefined}
    >
      {label}
    </Link>
  );
}

export default function Nav({
  currentPath,
  pageTitle,
  onLogout,
  showManagerLinks,
}: NavProps) {
  const [role, setRole] = useState<string | null>(null);
  useEffect(() => {
    setRole(getRole());
  }, []);

  const showAccounting =
    role === "admin" || role === "manager" || role === "reception";
  const showMgr =
    showManagerLinks ?? (role === "manager" || role === "admin");

  return (
    <header className={styles.topbar} role="banner">
      <Link href="/dashboard" className={styles.brand} aria-label="صفحه اصلی حلقه">
        حلقه
      </Link>

      <nav className={styles.nav} aria-label="ناوبری اصلی">
        {NAV_LINKS.map((link) => renderLink(link, currentPath))}

        {showAccounting && (
          <span className={styles.managerGroup} aria-label="حسابداری">
            {ACCOUNTING_LINKS.map((link) => renderLink(link, currentPath))}
          </span>
        )}

        {showMgr && (
          <span className={styles.managerGroup} aria-label="مدیریت">
            {MANAGER_LINKS.map((link) => renderLink(link, currentPath))}
          </span>
        )}

        {pageTitle && (
          <span className={styles.pageTitle} aria-label={`صفحهٔ جاری: ${pageTitle}`}>
            {pageTitle}
          </span>
        )}
      </nav>

      <button
        onClick={onLogout}
        className={styles.logoutBtn}
        aria-label="خروج از سامانه"
        type="button"
      >
        خروج
      </button>
    </header>
  );
}
