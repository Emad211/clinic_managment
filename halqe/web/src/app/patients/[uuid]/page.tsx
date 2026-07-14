"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { useParams, usePathname } from "next/navigation";
import {
  apiGetRecord,
  apiGetStructuredPatientRecord,
  apiGetSuggestions,
  getScreeningTimeline,
  listAllergies,
  type ClinicalRecordDTO,
  type StructuredPatientRecordDTO,
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
import { MedicationRecordPanel } from "@/components/MedicationRecordPanel";
import { StructuredPatientRecordPanel } from "@/components/StructuredPatientRecordPanel";
import { RegisterVisitForm } from "@/components/encounter/RegisterVisitForm";
import { EncountersList } from "@/components/encounter/EncountersList";
import { ClinicalSummaryStrip } from "@/components/ClinicalSummaryStrip";
import { PerDiseaseIndicators } from "@/components/PerDiseaseIndicators";
import { TabBar, TabPanel, type TabDef } from "@/components/TabBar";
import { AllergiesBanner, Allergies } from "@/components/Allergies";
import styles from "./record.module.css";

/**
 * Patient safety cockpit + the full descriptive record migrated from
 * specialist_clinic. Suggestions remain outside the tabs; the structured record
 * is a separate request so a supplementary endpoint failure never hides the
 * existing cockpit.
 */
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

  const [structuredRecord, setStructuredRecord] = useState<StructuredPatientRecordDTO | null>(null);
  const [structuredLoading, setStructuredLoading] = useState(true);
  const [structuredError, setStructuredError] = useState<string | null>(null);

  const [suggestions, setSuggestions] = useState<SuggestionsResponseDTO | null>(null);
  const [suggestionsLoading, setSuggestionsLoading] = useState(true);
  const [suggestionsError, setSuggestionsError] = useState<string | null>(null);
  const [screeningTimeline, setScreeningTimeline] = useState<ScreeningTimelineResponse | null>(null);
  const [allergies, setAllergies] = useState<AllergyDTO[]>([]);

  const [showVisitForm, setShowVisitForm] = useState(false);
  const [encounterRefreshKey, setEncounterRefreshKey] = useState(0);
  const [activeTab, setActiveTab] = useState<TabKey>("overview");

  const fetchRecord = useCallback(async () => {
    if (!uuid) return;
    setRecordLoading(true);
    setRecordError(null);
    try {
      setRecord(await apiGetRecord(uuid));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setRecordError(
        err instanceof ApiError ? `خطا: ${err.message}` : "بارگذاری پرونده ناموفق بود.",
      );
    } finally {
      setRecordLoading(false);
    }
  }, [uuid, logout]);

  const fetchStructuredRecord = useCallback(async () => {
    if (!uuid) return;
    setStructuredLoading(true);
    setStructuredError(null);
    try {
      setStructuredRecord(await apiGetStructuredPatientRecord(uuid));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setStructuredError(
        err instanceof ApiError
          ? `خطا در پروندهٔ ساختاریافته: ${err.message}`
          : "بارگذاری پروندهٔ ساختاریافته ناموفق بود.",
      );
    } finally {
      setStructuredLoading(false);
    }
  }, [uuid, logout]);

  const fetchSuggestions = useCallback(async () => {
    if (!uuid) return;
    setSuggestionsLoading(true);
    setSuggestionsError(null);
    try {
      setSuggestions(await apiGetSuggestions(uuid));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setSuggestionsError(
        err instanceof ApiError ? `خطا: ${err.message}` : "بارگذاری پیشنهادات ناموفق بود.",
      );
    } finally {
      setSuggestionsLoading(false);
    }
  }, [uuid, logout]);

  const fetchScreeningTimeline = useCallback(async () => {
    if (!uuid) return;
    try {
      setScreeningTimeline(await getScreeningTimeline(uuid));
    } catch {
      setScreeningTimeline(null);
    }
  }, [uuid]);

  const fetchAllergies = useCallback(async () => {
    if (!uuid) return;
    try {
      setAllergies(await listAllergies(uuid));
    } catch {
      setAllergies([]);
    }
  }, [uuid]);

  useEffect(() => {
    if (!ready) return;
    void fetchRecord();
    void fetchStructuredRecord();
    void fetchSuggestions();
    void fetchScreeningTimeline();
    void fetchAllergies();
  }, [
    ready,
    fetchRecord,
    fetchStructuredRecord,
    fetchSuggestions,
    fetchScreeningTimeline,
    fetchAllergies,
  ]);

  const controlByCode = useMemo<Record<string, ControlDTO>>(() => {
    const map: Record<string, ControlDTO> = {};
    for (const item of record?.per_disease ?? []) {
      map[item.condition_code] = item.control;
    }
    return map;
  }, [record?.per_disease]);

  if (!ready) return null;

  function handleVisitSuccess() {
    setShowVisitForm(false);
    setEncounterRefreshKey((key) => key + 1);
    void fetchRecord();
    void fetchStructuredRecord();
    void fetchSuggestions();
  }

  function handleVitalReviewed() {
    void fetchRecord();
    void fetchStructuredRecord();
    void fetchSuggestions();
  }

  const demo = record?.demographics;
  const pendingReviewCount = (record?.recent_vitals ?? []).filter(
    (vital) =>
      vital.source === "patient_self" &&
      !vital.verified &&
      vital.rejected_at === null,
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

      {recordLoading && (
        <main className={styles.main} id="main-content" aria-label="محتوای اصلی">
          <div className={styles.stateBox} role="status" aria-live="polite">
            <span className={styles.spinner} aria-hidden="true" />
            در حال بارگذاری پرونده…
          </div>
        </main>
      )}

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

      {!recordLoading && !recordError && record && (
        <main className={styles.main} id="main-content" aria-label="محتوای اصلی">
          <PatientHeader demo={demo} control={record.control} risk={record.risk} />

          {allergies.length > 0 && (
            <div className={styles.bannerSlot}>
              <AllergiesBanner allergies={allergies} />
            </div>
          )}

          <div className={styles.recordColumn} role="region" aria-label="پرونده بالینی">
            <TabBar
              tabs={tabs}
              active={activeTab}
              onChange={setActiveTab}
              ariaLabel="بخش‌های پرونده"
              idPrefix={TAB_ID_PREFIX}
            />

            <TabPanel idPrefix={TAB_ID_PREFIX} tabKey="overview" active={activeTab}>
              <div className={styles.tabStack}>
                <ClinicalSummaryStrip
                  control={record.control}
                  risk={record.risk}
                  openFollowupsCount={record.open_followups_count}
                  refillDueCount={record.refill_due_count}
                />
                <PerDiseaseIndicators perDisease={record.per_disease} />
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

            <TabPanel idPrefix={TAB_ID_PREFIX} tabKey="trends" active={activeTab}>
              <div className={styles.tabStack}>
                <section className={`${styles.card} ${styles.section}`} aria-label="ویتال‌های اخیر">
                  <h2 className={styles.sectionTitle}>ویتال‌های اخیر</h2>
                  <RecentVitalsTable vitals={record.recent_vitals} />
                </section>
              </div>
            </TabPanel>

            <TabPanel idPrefix={TAB_ID_PREFIX} tabKey="meds" active={activeTab}>
              <div className={styles.tabStack}>
                <ActiveMedications medications={record.active_medications} />
                <MedicationRecordPanel
                  uuid={uuid}
                  record={structuredRecord}
                  loading={structuredLoading}
                  error={structuredError}
                  onChanged={fetchStructuredRecord}
                />
              </div>
            </TabPanel>

            <TabPanel idPrefix={TAB_ID_PREFIX} tabKey="record" active={activeTab}>
              <div className={styles.tabStack}>
                <ActiveConditions
                  conditions={record.active_conditions}
                  controlByCode={controlByCode}
                />

                <StructuredPatientRecordPanel
                  uuid={uuid}
                  record={structuredRecord}
                  loading={structuredLoading}
                  error={structuredError}
                  onChanged={async () => {
                    await fetchStructuredRecord();
                    await fetchRecord();
                    await fetchSuggestions();
                  }}
                />

                <VerificationInbox
                  vitals={record.recent_vitals}
                  uuid={uuid}
                  onReviewed={handleVitalReviewed}
                />

                <section className={`${styles.card} ${styles.section}`} aria-label="ویزیت‌های اخیر">
                  <h2 className={styles.sectionTitle}>ویزیت‌های اخیر</h2>
                  <EncountersList uuid={uuid} refreshKey={encounterRefreshKey} />
                </section>

                {screeningTimeline && (
                  <ScreeningTimeline
                    framing={screeningTimeline.framing}
                    items={screeningTimeline.items}
                  />
                )}

                <Allergies uuid={uuid} allergies={allergies} onChanged={fetchAllergies} />
                <PatientCardShare uuid={uuid} />
              </div>
            </TabPanel>
          </div>

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
