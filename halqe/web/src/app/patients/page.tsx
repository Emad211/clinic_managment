"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  apiGetPatients,
  clearToken,
  getToken,
  type EnrolledPatient,
} from "@/lib/api";
import { ApiError } from "@/lib/api";
import { formatJalali } from "@/lib/jalali";
import styles from "./patients.module.css";

const PAGE_SIZE = 20;

export default function PatientsPage() {
  const router = useRouter();
  const [patients, setPatients] = useState<EnrolledPatient[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchPage = useCallback(
    async (pageOffset: number) => {
      setLoading(true);
      setError(null);
      try {
        const data = await apiGetPatients(PAGE_SIZE, pageOffset);
        setPatients(data.items);
        setTotal(data.total);
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          clearToken();
          router.push("/login");
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
    [router],
  );

  useEffect(() => {
    // Guard: redirect to login if no token
    if (!getToken()) {
      router.push("/login");
      return;
    }
    fetchPage(0);
  }, [fetchPage, router]);

  function handleLogout() {
    clearToken();
    router.push("/login");
  }

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

  return (
    <div className={styles.layout}>
      {/* Top navigation */}
      <header className={styles.topbar} role="banner">
        <span className={styles.topbarBrand}>حلقه</span>
        <nav className={styles.topbarNav} aria-label="ناوبری اصلی">
          <span className={styles.topbarPageTitle}>لیست بیماران</span>
        </nav>
        <button
          onClick={handleLogout}
          className={styles.logoutBtn}
          aria-label="خروج از سامانه"
        >
          خروج
        </button>
      </header>

      {/* Main content */}
      <main className={styles.main} id="main-content">
        <div className={styles.pageHeader}>
          <h1 className={styles.pageTitle}>بیماران ثبت‌نام‌شده</h1>
          {!loading && !error && (
            <span className={styles.totalBadge}>
              مجموع: {total} بیمار
            </span>
          )}
        </div>

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

        {/* Empty state */}
        {!loading && !error && patients.length === 0 && (
          <div className={styles.stateBox} role="status">
            هیچ بیماری ثبت‌نام نشده است.
          </div>
        )}

        {/* Patient table */}
        {!loading && !error && patients.length > 0 && (
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
                  {patients.map((p) => (
                    <tr key={p.link_id} className={styles.tableRow}>
                      <td className={styles.nameCell}>
                        {p.full_name ?? (
                          <span className="text-muted">بدون نام</span>
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

            {/* Pagination */}
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
                صفحهٔ {currentPage} از {totalPages}
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
          </>
        )}
      </main>
    </div>
  );
}
