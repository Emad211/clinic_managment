"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useRouter, useParams, usePathname } from "next/navigation";
import Link from "next/link";
import {
  apiGetRecord,
  apiGetSuggestions,
  apiSuggestionAction,
  clearToken,
  getToken,
  type ClinicalRecordDTO,
  type SuggestionsResponseDTO,
  type SuggestionRuleDTO,
  ApiError,
} from "@/lib/api";
import { formatJalali } from "@/lib/jalali";
import {
  buildInitialActed,
  type ActedState,
  type ActedMap,
} from "@/lib/suggestion-utils";
import Nav from "@/components/Nav";
import styles from "./record.module.css";

// ────────────────────────────────────────────────────────────
// Severity helpers
// ────────────────────────────────────────────────────────────

const SEVERITY_LABEL: Record<string, string> = {
  urgent: "هشدار",
  warn: "احتیاط",
  info: "توجه",
};

// ────────────────────────────────────────────────────────────
// Sub-component: single rule card
// ────────────────────────────────────────────────────────────

function RuleCard({
  rule,
  uuid,
  acted,
  onAct,
}: {
  rule: SuggestionRuleDTO;
  uuid: string;
  acted: ActedState | undefined;
  onAct: (ruleCode: string, action: "accept" | "dismiss") => void;
}) {
  const [busy, setBusy] = useState(false);

  async function handleAction(action: "accept" | "dismiss") {
    if (busy || acted) return;
    setBusy(true);
    try {
      await apiSuggestionAction(uuid, rule.rule_code, action);
      onAct(rule.rule_code, action);
    } catch {
      // silent fail — the button re-enables so user can retry
    } finally {
      setBusy(false);
    }
  }

  return (
    <article
      className={styles.ruleCard}
      data-severity={rule.severity}
      aria-label={rule.title}
    >
      <div className={styles.ruleHeader}>
        <h4 className={styles.ruleTitle}>{rule.title}</h4>
        <span
          className={styles.severityBadge}
          data-severity={rule.severity}
          aria-label={`شدت: ${SEVERITY_LABEL[rule.severity] ?? rule.severity}`}
        >
          {SEVERITY_LABEL[rule.severity] ?? rule.severity}
        </span>
      </div>

      {rule.recommendation && (
        <p className={styles.ruleRec}>{rule.recommendation}</p>
      )}

      <div className={styles.ruleActions} role="group" aria-label="اقدام روی پیشنهاد">
        {acted === "accepted" ? (
          <span className={`${styles.actedState} ${styles.actedAccepted}`} role="status">
            تأیید شد
          </span>
        ) : acted === "dismissed" ? (
          <span className={`${styles.actedState} ${styles.actedDismissed}`} role="status">
            رد شد
          </span>
        ) : (
          <>
            <button
              className={styles.acceptBtn}
              onClick={() => handleAction("accept")}
              disabled={busy}
              aria-label={`تأیید پیشنهاد: ${rule.title}`}
            >
              {busy ? "…" : "تأیید"}
            </button>
            <button
              className={styles.dismissBtn}
              onClick={() => handleAction("dismiss")}
              disabled={busy}
              aria-label={`رد پیشنهاد: ${rule.title}`}
            >
              {busy ? "…" : "رد"}
            </button>
          </>
        )}
      </div>
    </article>
  );
}

// ────────────────────────────────────────────────────────────
// Sub-component: suggestions panel
// ────────────────────────────────────────────────────────────

function SuggestionsPanel({
  uuid,
  suggestions,
  suggestionsLoading,
  suggestionsError,
}: {
  uuid: string;
  suggestions: SuggestionsResponseDTO | null;
  suggestionsLoading: boolean;
  suggestionsError: string | null;
}) {
  // Per-rule acted state: seeded from server prior_action on load,
  // then updated optimistically after user acts (no full-page reload).
  const [acted, setActed] = useState<ActedMap>({});

  // Track which suggestions object we last seeded from, so we only
  // rebuild the initial map when a genuinely new suggestions payload
  // arrives (not on every render).
  const seededForRef = useRef<SuggestionsResponseDTO | null>(null);

  useEffect(() => {
    if (suggestions && suggestions !== seededForRef.current) {
      seededForRef.current = suggestions;
      setActed((prev) => {
        // Merge server prior_action into local state, but don't overwrite
        // any action the physician has already taken in this session.
        const fromServer = buildInitialActed(suggestions);
        return { ...fromServer, ...prev };
      });
    }
  }, [suggestions]);

  function handleAct(ruleCode: string, action: "accept" | "dismiss") {
    setActed((prev) => ({
      ...prev,
      [ruleCode]: action === "accept" ? "accepted" : "dismissed",
    }));
  }

  return (
    <aside className={`${styles.card} ${styles.suggestionsPanel}`} aria-label="پیشنهادات بالینی">
      <h2 className={styles.suggestionsPanelTitle}>پیشنهادات بالینی</h2>

      {suggestionsLoading && (
        <div className={styles.suggestionsLoading} role="status" aria-live="polite">
          <span className={styles.spinner} aria-hidden="true" />
          در حال بارگذاری پیشنهادات…
        </div>
      )}

      {!suggestionsLoading && suggestionsError && (
        <p className={styles.ruleRec} role="alert" style={{ color: "var(--color-danger)" }}>
          {suggestionsError}
        </p>
      )}

      {!suggestionsLoading && !suggestionsError && suggestions && (
        <>
          {/* Framing banner — always visible, carries the "تأیید با پزشک" obligation */}
          <div className={styles.framingBanner} role="note" aria-label="این صفحه فقط پیشنهاد است">
            <span className={styles.framingIcon} aria-hidden="true">!</span>
            {suggestions.framing}
          </div>

          {suggestions.has_redflag && (
            <div className={styles.redflagStrip} role="alert">
              <span aria-hidden="true">!</span>
              پرچم قرمز: هشدار فوری وجود دارد
            </div>
          )}

          <p className={styles.suggestionsCount}>
            {suggestions.count} پیشنهاد فعال
          </p>

          {suggestions.sections.length === 0 && (
            <p className={styles.emptyNote}>هیچ پیشنهادی یافت نشد.</p>
          )}

          {suggestions.sections.map((sec) => (
            <section key={sec.key} className={styles.suggestionSection} aria-label={sec.label}>
              <h3 className={styles.suggestionSectionLabel}>{sec.label}</h3>
              {sec.rules.map((rule) => (
                <RuleCard
                  key={rule.rule_code}
                  rule={rule}
                  uuid={uuid}
                  acted={acted[rule.rule_code]}
                  onAct={handleAct}
                />
              ))}
            </section>
          ))}
        </>
      )}

      {!suggestionsLoading && !suggestionsError && !suggestions && (
        <p className={styles.emptyNote}>داده‌ای موجود نیست.</p>
      )}
    </aside>
  );
}

// ────────────────────────────────────────────────────────────
// Main page
// ────────────────────────────────────────────────────────────

export default function PatientDetailPage() {
  const router = useRouter();
  const params = useParams<{ uuid: string }>();
  const pathname = usePathname();
  const uuid = params?.uuid ?? "";

  const [record, setRecord] = useState<ClinicalRecordDTO | null>(null);
  const [recordLoading, setRecordLoading] = useState(true);
  const [recordError, setRecordError] = useState<string | null>(null);

  const [suggestions, setSuggestions] = useState<SuggestionsResponseDTO | null>(null);
  const [suggestionsLoading, setSuggestionsLoading] = useState(true);
  const [suggestionsError, setSuggestionsError] = useState<string | null>(null);

  // Handle 401 uniformly
  const handle401 = useCallback(() => {
    clearToken();
    router.push("/login");
  }, [router]);

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
        handle401();
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
  }, [uuid, handle401]);

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
        handle401();
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
  }, [uuid, handle401]);

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    // Fire both requests in parallel
    fetchRecord();
    fetchSuggestions();
  }, [fetchRecord, fetchSuggestions, router]);

  function handleLogout() {
    clearToken();
    router.push("/login");
  }

  const demo = record?.demographics;

  return (
    <div className={styles.layout}>
      <Nav
        currentPath={pathname ?? `/patients/${uuid}`}
        pageTitle={demo?.full_name ?? undefined}
        onLogout={handleLogout}
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
          <div className={`${styles.card} ${styles.patientHeader}`} role="region" aria-label="مشخصات بیمار">
            <h1 className={styles.patientName}>
              {demo?.full_name ?? "بیمار ناشناس"}
            </h1>
            <dl className={styles.patientMeta}>
              {demo?.national_id && (
                <div className={styles.metaItem}>
                  <dt className={styles.metaLabel}>کد ملی</dt>
                  <dd className={styles.metaValueMono}>{demo.national_id}</dd>
                </div>
              )}
              {demo?.phone_number && (
                <div className={styles.metaItem}>
                  <dt className={styles.metaLabel}>تلفن</dt>
                  <dd className={styles.metaValueMono}>{demo.phone_number}</dd>
                </div>
              )}
              {demo?.birthdate && (
                <div className={styles.metaItem}>
                  <dt className={styles.metaLabel}>تاریخ تولد</dt>
                  <dd className={styles.metaValue}>{formatJalali(demo.birthdate)}</dd>
                </div>
              )}
              {demo?.gender && (
                <div className={styles.metaItem}>
                  <dt className={styles.metaLabel}>جنسیت</dt>
                  <dd className={styles.metaValue}>{demo.gender}</dd>
                </div>
              )}
            </dl>
          </div>

          {/* Left column: clinical record */}
          <div className={styles.recordColumn} role="region" aria-label="پرونده بالینی">

            {/* Active conditions */}
            <section className={`${styles.card} ${styles.section}`} aria-label="بیماری‌های فعال">
              <h2 className={styles.sectionTitle}>بیماری‌های مزمن فعال</h2>
              {record.active_conditions.length === 0 ? (
                <p className={styles.emptyNote}>هیچ بیماری مزمن فعالی ثبت نشده است.</p>
              ) : (
                <ul className={styles.conditionList} aria-label="فهرست بیماری‌های فعال">
                  {record.active_conditions.map((c) => (
                    <li key={c.id} className={styles.conditionItem}>
                      <span className={styles.conditionName}>
                        {c.condition_name ?? c.condition_code ?? "بیماری ثبت‌شده"}
                      </span>
                      <span className={styles.conditionMeta}>
                        {c.stage && `مرحله: ${c.stage} · `}
                        {c.onset_date && `شروع: ${formatJalali(c.onset_date)}`}
                        {c.notes && ` · ${c.notes}`}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {/* Active medications */}
            <section className={`${styles.card} ${styles.section}`} aria-label="داروهای فعال">
              <h2 className={styles.sectionTitle}>داروهای فعال</h2>
              {record.active_medications.length === 0 ? (
                <p className={styles.emptyNote}>هیچ دارویی ثبت نشده است.</p>
              ) : (
                <div className={styles.tableWrapper}>
                  <table className={styles.table} aria-label="لیست داروهای فعال">
                    <thead>
                      <tr>
                        <th scope="col">نام دارو</th>
                        <th scope="col">دوز</th>
                        <th scope="col">برنامه</th>
                        <th scope="col">کلاس دارویی</th>
                        <th scope="col">شروع</th>
                      </tr>
                    </thead>
                    <tbody>
                      {record.active_medications.map((m) => (
                        <tr key={m.id} className={styles.tableRow}>
                          <td style={{ fontWeight: 600 }}>{m.drug_name}</td>
                          <td>{m.dose ?? "—"}</td>
                          <td>{m.schedule ?? "—"}</td>
                          <td>{m.drug_class ?? "—"}</td>
                          <td>{m.start_date ? formatJalali(m.start_date) : "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            {/* Recent vitals */}
            <section className={`${styles.card} ${styles.section}`} aria-label="ویتال‌های اخیر">
              <h2 className={styles.sectionTitle}>ویتال‌های اخیر</h2>
              {record.recent_vitals.length === 0 ? (
                <p className={styles.emptyNote}>هیچ ویتالی ثبت نشده است.</p>
              ) : (
                <div className={styles.tableWrapper}>
                  <table className={styles.table} aria-label="جدول ویتال‌های اخیر">
                    <thead>
                      <tr>
                        <th scope="col">نوع</th>
                        <th scope="col">مقدار</th>
                        <th scope="col">واحد</th>
                        <th scope="col">تاریخ اندازه‌گیری</th>
                        <th scope="col">منبع</th>
                      </tr>
                    </thead>
                    <tbody>
                      {record.recent_vitals.map((v) => (
                        <tr key={v.id} className={styles.tableRow}>
                          <td className={styles.vitalType}>{v.type}</td>
                          <td className={styles.vitalValue}>{v.value}</td>
                          <td>{v.unit ?? "—"}</td>
                          <td>{formatJalali(v.measured_at)}</td>
                          <td>{v.source ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
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
