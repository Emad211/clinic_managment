"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useParams, usePathname } from "next/navigation";
import Link from "next/link";
import {
  apiGetRecord,
  apiGetSuggestions,
  getScreeningTimeline,
  type ClinicalRecordDTO,
  type SuggestionsResponseDTO,
  type ScreeningTimelineResponse,
  ApiError,
} from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";
import Nav from "@/components/Nav";
import { SuggestionsPanel } from "@/components/SuggestionsPanel";
import { ScreeningTimeline } from "@/components/ScreeningTimeline";
import { VerificationInbox, RecentVitalsTable } from "@/components/VitalsReview";
import { PatientCardShare } from "@/components/PatientCardShare";
import { PatientHeader } from "@/components/PatientHeader";
import { ActiveConditions } from "@/components/ActiveConditions";
import { ActiveMedications } from "@/components/ActiveMedications";
import { RegisterVisitForm } from "@/components/encounter/RegisterVisitForm";
import { EncountersList } from "@/components/encounter/EncountersList";
import styles from "./record.module.css";

// ────────────────────────────────────────────────────────────
// Sub-components extracted to @/components (cleanup step 9):
//   PatientHeader, ActiveConditions, ActiveMedications,
//   encounter/RegisterVisitForm, encounter/EncountersList,
//   encounter/encounter-labels. RuleCard + SuggestionsPanel were
//   already extracted earlier. This page is now orchestration + composition.
// ────────────────────────────────────────────────────────────

// ────────────────────────────────────────────────────────────
// Main page
// ────────────────────────────────────────────────────────────

export default function PatientDetailPage() {
  const { ready, logout } = useAuth();
  const params = useParams<{ uuid: string }>();
  const pathname = usePathname();
  const uuid = params?.uuid ?? "";

  const [record, setRecord] = useState<ClinicalRecordDTO | null>(null);
  const [recordLoading, setRecordLoading] = useState(true);
  const [recordError, setRecordError] = useState<string | null>(null);

  const [suggestions, setSuggestions] = useState<SuggestionsResponseDTO | null>(null);
  const [suggestionsLoading, setSuggestionsLoading] = useState(true);
  const [suggestionsError, setSuggestionsError] = useState<string | null>(null);

  const [screeningTimeline, setScreeningTimeline] = useState<ScreeningTimelineResponse | null>(null);

  // Register-visit form visibility + encounter list refresh trigger
  const [showVisitForm, setShowVisitForm] = useState(false);
  const [encounterRefreshKey, setEncounterRefreshKey] = useState(0);

  // Fetch record
  const fetchRecord = useCallback(async () => {
    if (!uuid) return;
    setRecordLoading(true);
    setRecordError(null);
    try {
      const data = await apiGetRecord(uuid);
      setRecord(data);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setRecordError(
        err instanceof ApiError
          ? `خطا: ${err.message}`
          : "بارگذاری پرونده ناموفق بود.",
      );
    } finally {
      setRecordLoading(false);
    }
  }, [uuid, logout]);

  // Fetch suggestions (independent of record — runs in parallel)
  const fetchSuggestions = useCallback(async () => {
    if (!uuid) return;
    setSuggestionsLoading(true);
    setSuggestionsError(null);
    try {
      const data = await apiGetSuggestions(uuid);
      setSuggestions(data);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setSuggestionsError(
        err instanceof ApiError
          ? `خطا: ${err.message}`
          : "بارگذاری پیشنهادات ناموفق بود.",
      );
    } finally {
      setSuggestionsLoading(false);
    }
  }, [uuid, logout]);

  // Fetch screening timeline (independent — runs in parallel; graceful on 404/error)
  const fetchScreeningTimeline = useCallback(async () => {
    if (!uuid) return;
    try {
      const data = await getScreeningTimeline(uuid);
      setScreeningTimeline(data);
    } catch {
      // Screening timeline is supplementary — silently omit on error.
      // Backend may return 404 if no screenings are configured; that is not an error.
      setScreeningTimeline(null);
    }
  }, [uuid]);

  // Gate fetches on auth readiness
  useEffect(() => {
    if (!ready) return;
    // Fire all three requests in parallel
    fetchRecord();
    fetchSuggestions();
    fetchScreeningTimeline();
    // Stable useCallback refs; re-run only on ready change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);

  // Auth guard: render nothing while useAuth is checking/redirecting
  if (!ready) return null;

  /** Called when a visit is successfully registered: refresh both record + suggestions + encounters list. */
  function handleVisitSuccess() {
    setShowVisitForm(false);
    // Bump refresh key to re-fetch the encounters list
    setEncounterRefreshKey((k) => k + 1);
    // Also refresh the record (new vitals) and suggestions (new clinical state)
    fetchRecord();
    fetchSuggestions();
  }

  /**
   * Called after a successful verify/reject of a self-reported vital:
   * refetch the record (so the item leaves the inbox / changes state) and the
   * suggestions (an approved vital may enter the clinical engine). Does NOT
   * touch the visit form or the encounter list.
   */
  function handleVitalReviewed() {
    fetchRecord();
    fetchSuggestions();
  }

  const demo = record?.demographics;

  return (
    <div className={styles.layout}>
      <Nav
        currentPath={pathname ?? `/patients/${uuid}`}
        pageTitle={demo?.full_name ?? undefined}
        onLogout={logout}
      />

      {/* Loading state */}
      {recordLoading && (
        <main className={styles.main} id="main-content" aria-label="محتوای اصلی">
          <div className={styles.stateBox} role="status" aria-live="polite">
            <span className={styles.spinner} aria-hidden="true" />
            در حال بارگذاری پرونده…
          </div>
        </main>
      )}

      {/* Error state */}
      {!recordLoading && recordError && (
        <main className={styles.main} id="main-content">
          <div className={styles.errorBox} role="alert">
            <p>{recordError}</p>
            <button onClick={fetchRecord} className={styles.retryBtn}>
              تلاش مجدد
            </button>
          </div>
        </main>
      )}

      {/* Record loaded */}
      {!recordLoading && !recordError && record && (
        <main className={styles.main} id="main-content" aria-label="محتوای اصلی">

          {/* Patient header — spans full width */}
          <PatientHeader demo={demo} />

          {/* Left column: clinical record */}
          <div className={styles.recordColumn} role="region" aria-label="پرونده بالینی">

            {/* Register visit — button + inline form */}
            <div className={styles.visitSection}>
              {!showVisitForm ? (
                <button
                  className={styles.registerVisitBtn}
                  onClick={() => setShowVisitForm(true)}
                  aria-expanded={false}
                  aria-controls="register-visit-form"
                >
                  + ثبت ویزیت
                </button>
              ) : (
                <div id="register-visit-form">
                  <RegisterVisitForm
                    uuid={uuid}
                    onSuccess={handleVisitSuccess}
                    onClose={() => setShowVisitForm(false)}
                  />
                </div>
              )}
            </div>

            {/* Active conditions */}
            <ActiveConditions conditions={record.active_conditions} />

            {/* Active medications */}
            <ActiveMedications medications={record.active_medications} />

            {/* Verification inbox — صندوقِ تأیید دادهٔ خوداظهار.
                Renders ONLY when there is at least one pending self-report
                (the component returns null otherwise — no empty section). */}
            <VerificationInbox
              vitals={record.recent_vitals}
              uuid={uuid}
              onReviewed={handleVitalReviewed}
            />

            {/* Recent vitals (three-state aware) */}
            <section className={`${styles.card} ${styles.section}`} aria-label="ویتال‌های اخیر">
              <h2 className={styles.sectionTitle}>ویتال‌های اخیر</h2>
              <RecentVitalsTable vitals={record.recent_vitals} />
            </section>

            {/* Recent encounters list */}
            <section className={`${styles.card} ${styles.section}`} aria-label="ویزیت‌های اخیر">
              <h2 className={styles.sectionTitle}>ویزیت‌های اخیر</h2>
              <EncountersList uuid={uuid} refreshKey={encounterRefreshKey} />
            </section>

            {/* Screening timeline — only render when data is available */}
            {screeningTimeline && (
              <ScreeningTimeline
                framing={screeningTimeline.framing}
                items={screeningTimeline.items}
              />
            )}

            {/* کارتِ عمومیِ بیمار — صدورِ لینک + کپی + دکمهٔ SMSِ گِیت‌شده (قدم ۴۸) */}
            <PatientCardShare uuid={uuid} />

          </div>

          {/* Right column: suggestions */}
          <div className={styles.suggestionsColumn}>
            <SuggestionsPanel
              uuid={uuid}
              suggestions={suggestions}
              suggestionsLoading={suggestionsLoading}
              suggestionsError={suggestionsError}
            />
          </div>

        </main>
      )}
    </div>
  );
}
