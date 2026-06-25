"use client";

/**
 * Shared top navigation bar for all protected pages.
 *
 * Usage:
 *   <Nav currentPath="/worklist" pageTitle="لیست پیگیری‌ها" onLogout={handleLogout} />
 *
 * currentPath is compared against each link's href to set aria-current and the
 * active style. pageTitle is optional — shown as a breadcrumb after the nav links.
 */

import Link from "next/link";
import styles from "./nav.module.css";

interface NavLink {
  href: string;
  label: string;
}

const NAV_LINKS: NavLink[] = [
  { href: "/dashboard", label: "داشبورد" },
  { href: "/queue", label: "صف ویزیت" },
  { href: "/patients", label: "بیماران" },
  { href: "/worklist", label: "پیگیری‌ها" },
];

/** Manager-only links — appended only when `showManagerLinks` is true. */
const MANAGER_LINKS: NavLink[] = [
  { href: "/manager/outcomes", label: "گزارشِ outcome" },
];

interface NavProps {
  /** The pathname of the current page — used to highlight the active link. */
  currentPath: string;
  /** Optional page-level title shown as a breadcrumb on the right of the nav links. */
  pageTitle?: string;
  /** Called when the user clicks خروج. */
  onLogout: () => void;
  /**
   * When true, manager-only nav links (e.g. «گزارشِ outcome») are shown.
   * The page passes this after reading the role claim — the backend still
   * enforces the manager gate on every privileged endpoint.
   */
  showManagerLinks?: boolean;
}

export default function Nav({ currentPath, pageTitle, onLogout, showManagerLinks }: NavProps) {
  const links = showManagerLinks ? [...NAV_LINKS, ...MANAGER_LINKS] : NAV_LINKS;
  return (
    <header className={styles.topbar} role="banner">
      <Link href="/dashboard" className={styles.brand} aria-label="صفحه اصلی حلقه">
        حلقه
      </Link>

      <nav className={styles.nav} aria-label="ناوبری اصلی">
        {links.map(({ href, label }) => {
          // Mark active if the current path starts with the link's href
          // (so /patients/uuid also activates the Patients link)
          const isActive = currentPath === href || currentPath.startsWith(`${href}/`);
          return (
            <Link
              key={href}
              href={href}
              className={
                isActive
                  ? `${styles.navLink} ${styles.navLinkActive}`
                  : styles.navLink
              }
              aria-current={isActive ? "page" : undefined}
            >
              {label}
            </Link>
          );
        })}

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
