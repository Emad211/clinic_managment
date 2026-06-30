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

import { useEffect, useState } from "react";
import Link from "next/link";
import { getRole } from "@/lib/api";
import styles from "./nav.module.css";

interface NavLink {
  href: string;
  label: string;
}

/** Links every authenticated user sees, regardless of role. */
export const NAV_LINKS: NavLink[] = [
  { href: "/dashboard", label: "داشبورد" },
  { href: "/queue", label: "صف ویزیت" },
  { href: "/patients", label: "بیماران" },
  { href: "/worklist", label: "پیگیری‌ها" },
];

/**
 * Manager-only links — appended only for managers (role claim) or when a page
 * explicitly passes `showManagerLinks`. Reversible UX call (step 86): اتاقِ کنترل
 * is a manager-facing cohort-targeting view, so it lives here, not in NAV_LINKS.
 */
export const MANAGER_LINKS: NavLink[] = [
  { href: "/control-room", label: "اتاقِ کنترل" },
  { href: "/manager/outcomes", label: "گزارشِ outcome" },
  { href: "/manager/engagement", label: "صفِ تعامل" },
];

interface NavProps {
  /** The pathname of the current page — used to highlight the active link. */
  currentPath: string;
  /** Optional page-level title shown as a breadcrumb on the right of the nav links. */
  pageTitle?: string;
  /** Called when the user clicks خروج. */
  onLogout: () => void;
  /**
   * Optional OVERRIDE for the manager-link visibility.
   *   - undefined (default) → Nav reads the role claim itself and shows the
   *     manager group when role === "manager".
   *   - explicit true/false → forces visibility (backwards-compatible with the
   *     two manager pages that still pass `showManagerLinks`).
   * The backend still enforces the manager gate on every privileged endpoint;
   * this only governs link visibility.
   */
  showManagerLinks?: boolean;
}

/** Render one nav link with active/aria-current handling. */
function renderLink(
  { href, label }: NavLink,
  currentPath: string,
) {
  // Mark active if the current path starts with the link's href
  // (so /patients/uuid also activates the Patients link)
  const isActive = currentPath === href || currentPath.startsWith(`${href}/`);
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

export default function Nav({ currentPath, pageTitle, onLogout, showManagerLinks }: NavProps) {
  // Hydration-safe role read: never call getRole() in the render body (it reads
  // localStorage → would mismatch SSR). Start null, resolve in an effect.
  const [role, setRole] = useState<string | null>(null);
  useEffect(() => {
    setRole(getRole());
  }, []);

  // Explicit prop wins; otherwise derive from the role claim.
  const showMgr = showManagerLinks ?? role === "manager";

  return (
    <header className={styles.topbar} role="banner">
      <Link href="/dashboard" className={styles.brand} aria-label="صفحه اصلی حلقه">
        حلقه
      </Link>

      <nav className={styles.nav} aria-label="ناوبری اصلی">
        {NAV_LINKS.map((link) => renderLink(link, currentPath))}

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
