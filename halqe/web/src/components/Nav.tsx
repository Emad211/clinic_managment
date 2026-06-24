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
  { href: "/patients", label: "بیماران" },
  { href: "/worklist", label: "پیگیری‌ها" },
];

interface NavProps {
  /** The pathname of the current page — used to highlight the active link. */
  currentPath: string;
  /** Optional page-level title shown as a breadcrumb on the right of the nav links. */
  pageTitle?: string;
  /** Called when the user clicks خروج. */
  onLogout: () => void;
}

export default function Nav({ currentPath, pageTitle, onLogout }: NavProps) {
  return (
    <header className={styles.topbar} role="banner">
      <Link href="/patients" className={styles.brand} aria-label="صفحه اصلی حلقه">
        حلقه
      </Link>

      <nav className={styles.nav} aria-label="ناوبری اصلی">
        {NAV_LINKS.map(({ href, label }) => {
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
