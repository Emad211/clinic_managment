"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import {
  ApiError,
  apiGetRecord,
  apiGetRecordData,
  apiGetRecordVitals,
  listAllergies,
  type AllergyDTO,
  type ClinicalRecordDTO,
  type PatientRecordDataDTO,
  type RecordVitalDTO,
} from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";
import Nav from "@/components/Nav";
import { PatientHeader } from "@/components/PatientHeader";
import { Allergies, AllergiesBanner } from "@/components/Allergies";
import { RecordCoreEditor } from "@/components/record/RecordCoreEditor";
import { RecordMedicationManager } from "@/components/record/RecordMedicationManager";
import { RecordMeasurementsEditor } from "@/components/record/RecordMeasurementsEditor";
import styles from "./page.module.css";

export default function FullPatientRecordPage() {
  const { ready, logout } = useAuth();
  const params = useParams<{ uuid: string }>();
  const pathname = usePathname();
  const uuid = params?.uuid ?? "";

  const [cockpit, setCockpit] = useState<ClinicalRecordDTO | null>(null);
  const [recordData, setRecordData] = useState<PatientRecordDataDTO | null>(null);
  const [vitals, setVitals] = useState<RecordVitalDTO[]>([]);
  const [allergies, setAllergies] = useState<AllergyDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchAll = useCallback(
    async (initial = false) => {
      if (!uuid) return;
      if (initial) setLoading(true);
      else setRefreshing(true);
      setError(null);
      try {
        const [cockpitData, completeRecord, vitalHistory, allergyRows] = await Promise.all([
          apiGetRecord(uuid),
          apiGetRecordData(uuid),
          apiGetRecordVitals(uuid),
          listAllergies(uuid),
        ]);
        setCockpit(cockpitData);
        setRecordData(completeRecord);
        setVitals(vitalHistory);
        setAllergies(allergyRows);
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          logout();
          return;
        }
        setError(
          err instanceof ApiError
            ? err.message
            : "بارگذاری پروندهٔ تخصصی ناموفق بود.",
        );
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [uuid, logout],
  );

  const fetchAllergies = useCallback(async () => {
    if (!uuid) return;
    try {
      setAllergies(await listAllergies(uuid));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) logout();
    }
  }, [uuid, logout]);

  useEffect(() => {
    if (!ready) return;
    fetchAll(true);
  }, [ready, fetchAll]);

  if (!ready) return null;

  return (
    <div className={styles.layout}>
      <Nav
        currentPath={pathname ?? `/patients/${uuid}/record`}
        pageTitle={cockpit?.demographics?.full_name ?? "پرونده تخصصی"}
        onLogout={logout}
      />

      <main className={styles.main} id="main-content">
        <div className={styles.toolbar}>
          <Link className={styles.backLink} href={`/patients/${uuid}`}>
            بازگشت به کاکپیت ایمنی و پیشنهادها
          </Link>
          <button
            className={styles.refreshButton}
            type="button"
            disabled={refreshing}
            onClick={() => fetchAll(false)}
          >
            {refreshing ? "در حال تازه‌سازی…" : "تازه‌سازی کامل پرونده"}
          </button>
        </div>

        {loading && (
          <div className={styles.state} role="status" aria-live="polite">
            در حال بارگذاری پروندهٔ تخصصی…
          </div>
        )}

        {!loading && error && (
          <div className={styles.error} role="alert">
            <p>{error}</p>
            <button className={styles.retryButton} type="button" onClick={() => fetchAll(true)}>
              تلاش مجدد
            </button>
          </div>
        )}

        {!loading && !error && cockpit && recordData && (
          <>
            <PatientHeader
              demo={cockpit.demographics}
              control={cockpit.control}
              risk={cockpit.risk}
            />

            {allergies.length > 0 && <AllergiesBanner allergies={allergies} />}

            <section className={styles.intro} aria-labelledby="full-record-title">
              <h1 id="full-record-title">پروندهٔ تخصصی کامل</h1>
              <p>
                سوابق، بیماری‌ها، داروها، آزمایش‌ها، علائم حیاتی، معاینه و سبک زندگی
                در این صفحه ثبت می‌شوند. پیشنهادهای تصمیم‌یار همچنان در کاکپیت بیمار
                نمایش داده می‌شوند و تصمیم نهایی با پزشک است.
              </p>
            </section>

            <div className={styles.safetyNote} role="note">
              دادهٔ خوداظهاری بیمار از این صفحه حذف نمی‌شود و ابتدا باید در کاکپیت
              تأیید یا رد شود. حساسیت‌ها نیز بالای همهٔ فرم‌ها نمایش داده می‌شوند.
            </div>

            <RecordCoreEditor uuid={uuid} data={recordData} onChanged={() => fetchAll(false)} />
            <RecordMedicationManager uuid={uuid} data={recordData} onChanged={() => fetchAll(false)} />
            <RecordMeasurementsEditor
              uuid={uuid}
              data={recordData}
              vitals={vitals}
              onChanged={() => fetchAll(false)}
            />

            <section className={styles.allergySection} aria-label="مدیریت حساسیت‌ها">
              <Allergies uuid={uuid} allergies={allergies} onChanged={fetchAllergies} />
            </section>
          </>
        )}
      </main>
    </div>
  );
}
