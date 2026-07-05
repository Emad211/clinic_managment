"use client";

import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import { useParams, usePathname } from "next/navigation";
import {
  apiGetRecord,
  apiGetSuggestions,
  getScreeningTimeline,
  listAllergies,
  type ClinicalRecordDTO,
  type SuggestionsResponseDTO,
  type ScreeningTimelineResponse,
  type AllergyDTO,
  type ControlDTO,
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
import { ClinicalSummaryStrip } from "@/components/ClinicalSummaryStrip";
import { PerDiseaseIndicators } from "@/components/PerDiseaseIndicators";
import { TabBar, TabPanel, type TabDef } from "@/components/TabBar";
import { AllergiesBanner, Allergies } from "@/components/Allergies";
import styles from "./record.module.css";

// ────────────────────────────────────────────────────────────
// فاز ۱ — Safety cockpit. The page is orchestration + composition:
//   - it OWNS every fetch (record / suggestions / screening / allergies) and
//     feeds the presentational sub-components in @/components.
//   - the sticky SuggestionsPanel stays OUTSIDE the tabs (a clinical decision is
//     never hidden behind a tab); the AllergiesBanner stays ABOVE the tabs.
//   - tabbed content (Overview / Trends / Meds / Record) keeps its DOM mounted
//     (TabPanel hides via `hidden`), so form/list state survives tab switches.
//   - every new field is OPTIONAL end-to-end (graceful fallback) so an older
//     backend degrades silently instead of crashing.
// ────────────────────────────────────────────────────────────

type TabKey = "overview" | "trends" | "meds" | "record";
const TAB_ID_PREFIX = "patient-cockpit";

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

  // Allergies — page owns the fetch; banner (above tabs) + section (record tab).
  const [allergies, setAllergies] = useState<AllergyDTO[]>([]);

  // Register-visit form visibility + encounter list refresh trigger
  const [showVisitForm, setShowVisitForm] = useState(false);
  const [encounterRefreshKey, setEncounterRefreshKey] = useState(0);

  // Active tab (default: overview). DOM of every panel is kept mounted.
  const [activeTab, setActiveTab] = useState<TabKey>("overview");

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

  // Fetch allergies (independent — graceful on error; empty list ⇒ no banner)
  const fetchAllergies = useCallback(async () => {
    if (!uuid) return;
    try {
      const data = await listAllergies(uuid);
      setAllergies(data);
    } catch {
      // Allergies endpoint absent / errored → treat as none. Never crash the page.
      setAllergies([]);
    }
  }, [uuid]);

  // Gate fetches on auth readiness
  useEffect(() => {
    if (!ready) return;
    // Fire all requests in parallel
    fetchRecord();
    fetchSuggestions();
    fetchScreeningTimeline();
    fetchAllergies();
    // Stable useCallback refs; re-run only on ready change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);

  // Map condition_code → control state (for the badge next to each condition).
  // Declared BEFORE the auth early-return so hook order stays stable (rules-of-hooks).
  const controlByCode = useMemo<Record<string, ControlDTO>>(() => {
    const map: Record<string, ControlDTO> = {};
    for (const d of record?.per_disease ?? []) {
      map[d.condition_code] = d.control;
    }
    return map;
  }, [record?.per_disease]);

  // Auth guard: render nothing while useAuth is checking/redirecting
  if (!ready) return null;

  /** Called when a visit is successfully registered: refresh record + suggestions + encounters list. */
  function handleVisitSuccess() {
    setShowVisitForm(false);
    setEncounterRefreshKey((k) => k + 1);
    fetchRecord();
    fetchSuggestions();
  }

  /**
   * Called after a successful verify/reject of a self-reported vital:
   * refetch the record (so the item leaves the inbox / changes state) and the
   * suggestions (an approved vital may enter the clinical engine).
   */
  function handleVitalReviewed() {
    fetchRecord();
    fetchSuggestions();
  }

  const demo = record?.demographics;

  // Tab defs — the «پرونده» tab carries a counter for pending self-reports
  // (the same work the VerificationInbox surfaces) so it is visible without opening.
  const pendingReviewCount = (record?.recent_vitals ?? []).filter(
    (v) => v.source === "patient_self" && !v.verified && v.rejected_at === null,
  ).length;

  const tabs: TabDef<TabKey>[] = [
    { key: "overview", label: "نمای‌کلی" },
    { key: "trends", label: "روند" },
    { key: "meds", label: "داروها" },
    { key: "record", label: "پرونده", count: pendingReviewCount },
  ];

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

          {/* Patient header — spans full width, sticky-safety identity + badges */}
          <PatientHeader demo={demo} control={record.control} risk={record.risk} />

          {/* Allergy banner — ABOVE the tabs, outside tab content, only if allergies exist.
              Rendered conditionally so the grid row collapses when there are none. */}
          {allergies.length > 0 && (
            <div className={styles.bannerSlot}>
              <AllergiesBanner allergies={allergies} />
            </div>
          )}

          {/* Left column: tabbed clinical record */}
          <div className={styles.recordColumn} role="region" aria-label="پرونده بالینی">

            <TabBar
              tabs={tabs}
              active={activeTab}
              onChange={setActiveTab}
              ariaLabel="بخش‌های پرونده"
              idPrefix={TAB_ID_PREFIX}
            />

            {/* ── Tab: نمای‌کلی ── */}
            <TabPanel idPrefix={TAB_ID_PREFIX} tabKey="overview" active={activeTab}>
              <div className={styles.tabStack}>
                <ClinicalSummaryStrip
                  control={record.control}
                  risk={record.risk}
                  openFollowupsCount={record.open_followups_count}
                  refillDueCount={record.refill_due_count}
                />

                <PerDiseaseIndicators perDisease={record.per_disease} />

                {/* Register visit — quick action */}
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
              </div>
            </TabPanel>

            {/* ── Tab: روند ── (charts are Phase 2; table today) */}
            <TabPanel idPrefix={TAB_ID_PREFIX} tabKey="trends" active={activeTab}>
              <div className={styles.tabStack}>
                <section className={`${styles.card} ${styles.section}`} aria-label="ویتال‌های اخیر">
                  <h2 className={styles.sectionTitle}>ویتال‌های اخیر</h2>
                  <RecentVitalsTable vitals={record.recent_vitals} />
                </section>
              </div>
            </TabPanel>

            {/* ── Tab: داروها ── */}
            <TabPanel idPrefix={TAB_ID_PREFIX} tabKey="meds" active={activeTab}>
              <div className={styles.tabStack}>
                <ActiveMedications medications={record.active_medications} />
              </div>
            </TabPanel>

            {/* ── Tab: پرونده ── */}
            <TabPanel idPrefix={TAB_ID_PREFIX} tabKey="record" active={activeTab}>
              <div className={styles.tabStack}>
                <ActiveConditions
                  conditions={record.active_conditions}
                  controlByCode={controlByCode}
                />

                {/* Verification inbox — renders only when a pending self-report exists */}
                <VerificationInbox
                  vitals={record.recent_vitals}
                  uuid={uuid}
                  onReviewed={handleVitalReviewed}
                />

                {/* Recent encounters list */}
                <section className={`${styles.card} ${styles.section}`} aria-label="ویزیت‌های اخیر">
                  <h2 className={styles.sectionTitle}>ویزیت‌های اخیر</h2>
                  <EncountersList uuid={uuid} refreshKey={encounterRefreshKey} />
                </section>

                {/* Screening timeline — only when data is available */}
                {screeningTimeline && (
                  <ScreeningTimeline
                    framing={screeningTimeline.framing}
                    items={screeningTimeline.items}
                  />
                )}

                {/* Allergies — full section (list + add/delete) */}
                <Allergies uuid={uuid} allergies={allergies} onChanged={fetchAllergies} />

                {/* Public patient card — share link + copy + gated SMS */}
                <PatientCardShare uuid={uuid} />
              </div>
            </TabPanel>

          </div>

          {/* Right column: suggestions — sticky, OUTSIDE the tabs */}
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
