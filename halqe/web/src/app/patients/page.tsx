"use client";

import { useEffect, useState, useCallback } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import {
  apiGetPatients,
  ApiError,
  type EnrolledPatient,
} from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";
import { formatJalali, toFarsiDigits } from "@/lib/jalali";
import Nav from "@/components/Nav";
import styles from "./patients.module.css";

const PAGE_SIZE = 20;

/**
 * Normalize a string for search comparison:
 * - Lowercase
 * - Persian/Arabic-Indic digits (۰–۹ and ٠–٩) → ASCII 0–9
 * This lets a user type either Persian or Latin digits and match either form.
 */
function normalizeForSearch(s: string): string {
  return s
    .toLowerCase()
    // Eastern Arabic-Indic (۰–۹, U+06F0–U+06F9)
    .replace(/[۰-۹]/g, (c) => String(c.charCodeAt(0) - 0x06f0))
    // Arabic-Indic (٠–٩, U+0660–U+0669)
    .replace(/[٠-٩]/g, (c) => String(c.charCodeAt(0) - 0x0660));
}

export default function PatientsPage() {
  const { ready, logout } = useAuth();
  const pathname = usePathname();

  const [patients, setPatients] = useState<EnrolledPatient[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Client-side search state — filters the current fetched page
  const [search, setSearch] = useState("");

  const fetchPage = useCallback(
    async (pageOffset: number) => {
      setLoading(true);
      setError(null);
      setSearch(""); // clear search on page navigation
      try {
        const data = await apiGetPatients(PAGE_SIZE, pageOffset);
        setPatients(data.items);
        setTotal(data.total);
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          logout();
          return;
        }
        setError(
          err instanceof ApiError
            ? `خطا: ${err.message}`
            : "دریافت لیست بیماران ناموفق بود.",
        );
      } finally {
        setLoading(false);
      }
    },
    [logout],
  );

  // Fire only once auth guard confirms a valid token
  useEffect(() => {
    if (!ready) return;
    fetchPage(0);
  }, [ready, fetchPage]);

  // Auth guard: render nothing while useAuth is checking/redirecting
  if (!ready) return null;

  function handlePrev() {
    const newOffset = Math.max(0, offset - PAGE_SIZE);
    setOffset(newOffset);
    fetchPage(newOffset);
  }

  function handleNext() {
    const newOffset = offset + PAGE_SIZE;
    if (newOffset < total) {
      setOffset(newOffset);
      fetchPage(newOffset);
    }
  }

  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  // Client-side filter over the current page's items
  const normalizedSearch = normalizeForSearch(search.trim());
  const filtered: EnrolledPatient[] =
    normalizedSearch === ""
      ? patients
      : patients.filter((p) => {
          const name = normalizeForSearch(p.full_name ?? "");
          const nid = normalizeForSearch(p.national_id ?? "");
          const phone = normalizeForSearch(p.phone_number ?? "");
          return (
            name.includes(normalizedSearch) ||
            nid.includes(normalizedSearch) ||
            phone.includes(normalizedSearch)
          );
        });

  const hasPatients = patients.length > 0;
  const searchActive = normalizedSearch !== "";
  const noSearchResults = searchActive && filtered.length === 0;

  return (
    <div className={styles.layout}>
      <Nav
        currentPath={pathname ?? "/patients"}
        onLogout={logout}
      />

      {/* Main content */}
      <main className={styles.main} id="main-content">
        <div className={styles.pageHeader}>
          <h1 className={styles.pageTitle}>بیماران ثبت‌نام‌شده</h1>
          {!loading && !error && (
            <span className={styles.totalBadge}>
              مجموع: {toFarsiDigits(total)} بیمار
            </span>
          )}
        </div>

        {/* Search box — shown whenever we have data (or just finished loading) */}
        {!error && (
          <div className={styles.searchRow}>
            <label htmlFor="patient-search" className={styles.searchLabel}>
              جستجو
            </label>
            <input
              id="patient-search"
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="جستجو در نام، کد ملی، شماره تماس… (در این صفحه)"
              aria-label="جستجو در بیماران — نام، کد ملی یا شماره تماس"
              className={styles.searchInput}
              disabled={loading}
              dir="rtl"
            />
          </div>
        )}

        {/* Loading state */}
        {loading && (
          <div className={styles.stateBox} role="status" aria-live="polite">
            <span className={styles.spinner} aria-hidden="true" />
            در حال بارگذاری…
          </div>
        )}

        {/* Error state */}
        {!loading && error && (
          <div className={styles.errorBox} role="alert">
            <p>{error}</p>
            <button
              onClick={() => fetchPage(offset)}
              className={styles.retryBtn}
            >
              تلاش مجدد
            </button>
          </div>
        )}

        {/* Empty state — no patients at all (distinct from no-search-results) */}
        {!loading && !error && !hasPatients && (
          <div className={styles.stateBox} role="status">
            هیچ بیماری ثبت‌نام نشده است.
          </div>
        )}

        {/* No search results — patients exist but filter returned nothing */}
        {!loading && !error && hasPatients && noSearchResults && (
          <div className={styles.noResultsBox} role="status" aria-live="polite">
            نتیجه‌ای برای «{search}» یافت نشد.
          </div>
        )}

        {/* Patient table */}
        {!loading && !error && filtered.length > 0 && (
          <>
            <div className={styles.tableWrapper}>
              <table className={styles.table} aria-label="لیست بیماران">
                <thead>
                  <tr>
                    <th scope="col">نام و نام خانوادگی</th>
                    <th scope="col">کد ملی</th>
                    <th scope="col">شماره تماس</th>
                    <th scope="col">تاریخ ثبت‌نام</th>
                    <th scope="col">وضعیت</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((p) => (
                    <tr key={p.link_id} className={styles.tableRow}>
                      <td className={styles.nameCell}>
                        {p.patient_uuid ? (
                          <Link href={`/patients/${p.patient_uuid}`}>
                            {p.full_name ?? <span className="text-muted">بدون نام</span>}
                          </Link>
                        ) : (
                          p.full_name ?? <span className="text-muted">بدون نام</span>
                        )}
                      </td>
                      <td className={styles.monoCell}>
                        {p.national_id ?? "—"}
                      </td>
                      <td className={styles.monoCell}>
                        {p.phone_number ?? "—"}
                      </td>
                      <td>{formatJalali(p.enrolled_at)}</td>
                      <td>
                        <span
                          className={
                            p.is_active ? styles.badgeActive : styles.badgeInactive
                          }
                          aria-label={p.is_active ? "فعال" : "غیرفعال"}
                        >
                          {p.is_active ? "فعال" : "غیرفعال"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination — shown only when not actively searching (search covers full page) */}
            {!searchActive && (
              <nav
                className={styles.pagination}
                aria-label="صفحه‌بندی"
              >
                <button
                  onClick={handleNext}
                  disabled={offset + PAGE_SIZE >= total}
                  className={styles.pageBtn}
                  aria-label="صفحه بعد"
                >
                  بعدی
                </button>
                <span className={styles.pageInfo} aria-live="polite">
                  صفحهٔ {toFarsiDigits(currentPage)} از {toFarsiDigits(totalPages)}
                </span>
                <button
                  onClick={handlePrev}
                  disabled={offset === 0}
                  className={styles.pageBtn}
                  aria-label="صفحه قبل"
                >
                  قبلی
                </button>
              </nav>
            )}
          </>
        )}
      </main>
    </div>
  );
}
