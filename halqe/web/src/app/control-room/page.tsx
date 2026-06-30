"use client";

/**
 * Control Room — read-only prioritized triage view (MVP step 84).
 *
 * Read-only by design: this page only GETs (panel + conversion). There is NO
 * state-changing action here — cohort filtering is client-side on the ids the
 * panel already returns. Revenue is gated server-side via panel.show_value
 * (manager-only); we never read the role claim for that gate.
 *
 * a11y: red-flag chips use icon + text + colour (not colour alone); the control
 * badge is four-state with always-on Persian text; conversion rates are hidden
 * entirely when the sample is too small (honesty over decoration).
 */

import { useEffect, useState, useCallback } from "react";
import { usePathname } from "next/navigation";
import {
  apiGetControlRoom,
  apiGetConversion,
  type ControlRoomPanel,
  type ControlRoomPatient,
  type ControlRoomFlag,
  type ConversionMetric,
  ApiError,
} from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";
import { formatJalali, formatToman, toFarsiDigits } from "@/lib/jalali";
import Nav from "@/components/Nav";
import styles from "./control-room.module.css";

// ────────────────────────────────────────────────────────────
// Display helpers (pure)
// ────────────────────────────────────────────────────────────

// Control status → four-state badge display. Always carries Persian text so the
// colour is never the sole signal (colour-blind safe).
interface ControlDisplay {
  key: "uncontrolled" | "borderline" | "controlled" | "unknown";
  label: string;
  icon: string;
}
const CONTROL_MAP: Record<string, ControlDisplay> = {
  uncontrolled: { key: "uncontrolled", label: "خارج از کنترل", icon: "✕" },
  borderline: { key: "borderline", label: "مرزی", icon: "▲" },
  controlled: { key: "controlled", label: "تحتِ کنترل", icon: "✓" },
  unknown: { key: "unknown", label: "نامشخص", icon: "?" },
};
function controlDisplay(control: string): ControlDisplay {
  return CONTROL_MAP[control] ?? CONTROL_MAP.unknown;
}

// Severity chip display — distinguished by icon SHAPE + text, not colour alone.
interface SeverityChip {
  label: string;
  ariaLabel: string;
  icon: string;
}
function dangerChip(flag: ControlRoomFlag): SeverityChip {
  const valueText = toFarsiDigits(flag.value);
  return {
    label: `${flag.label} (${valueText})`,
    ariaLabel: `خطر: ${flag.label} با مقدار ${valueText}`,
    icon: "⚠",
  };
}
function warnChip(flag: ControlRoomFlag): SeverityChip {
  const valueText = toFarsiDigits(flag.value);
  return {
    label: `${flag.label} (${valueText})`,
    ariaLabel: `هشدار: ${flag.label} با مقدار ${valueText}`,
    icon: "●",
  };
}

// Defensive breakdown render: OpenAPI does not guarantee a [label, points] tuple.
interface BreakdownItem {
  label: string;
  points: number;
}
function parseBreakdown(breakdown: unknown[]): BreakdownItem[] {
  if (!Array.isArray(breakdown)) return [];
  const out: BreakdownItem[] = [];
  for (const it of breakdown) {
    if (Array.isArray(it) && it.length === 2) {
      const label = typeof it[0] === "string" ? it[0] : String(it[0]);
      const points = typeof it[1] === "number" ? it[1] : Number(it[1]);
      if (!Number.isNaN(points)) out.push({ label, points });
    }
  }
  // Sort descending by points
  return out.sort((a, b) => b.points - a.points);
}

// Format a percentage rate (0..100) as Persian digits + ٪.
function formatRate(rate: number): string {
  // Round to 1 decimal, drop trailing .0
  const rounded = Math.round(rate * 10) / 10;
  return `${toFarsiDigits(rounded)}٪`;
}

// ────────────────────────────────────────────────────────────
// Page
// ────────────────────────────────────────────────────────────

const ALL_COHORT_KEY = "__all__";

export default function ControlRoomPage() {
  const { ready, logout } = useAuth();
  const pathname = usePathname();

  const [panel, setPanel] = useState<ControlRoomPanel | null>(null);
  const [conversion, setConversion] = useState<ConversionMetric | null>(null);
  const [conversionError, setConversionError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Client-side cohort filter (single-select). Default = all.
  const [activeCohort, setActiveCohort] = useState<string>(ALL_COHORT_KEY);
  // Rows expanded to show their score breakdown.
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    setConversionError(null);

    const [panelRes, convRes] = await Promise.allSettled([
      apiGetControlRoom(),
      apiGetConversion(),
    ]);

    // 401 from either → logout
    const is401 = (r: PromiseSettledResult<unknown>) =>
      r.status === "rejected" &&
      r.reason instanceof ApiError &&
      r.reason.status === 401;
    if (is401(panelRes) || is401(convRes)) {
      logout();
      return;
    }

    // Panel is load-bearing: failure = whole-page error.
    if (panelRes.status === "fulfilled") {
      setPanel(panelRes.value);
    } else {
      setError(
        panelRes.reason instanceof ApiError
          ? `خطا: ${panelRes.reason.message}`
          : "دریافت اتاقِ کنترل ناموفق بود.",
      );
      setLoading(false);
      return;
    }

    // Conversion failure is local — the rest of the page stays healthy.
    if (convRes.status === "fulfilled") {
      setConversion(convRes.value);
    } else {
      setConversion(null);
      setConversionError(
        convRes.reason instanceof ApiError
          ? `خطا در دریافت نرخ تبدیل: ${convRes.reason.message}`
          : "دریافت نرخ تبدیل ناموفق بود.",
      );
    }

    setLoading(false);
  }, [logout]);

  useEffect(() => {
    if (!ready) return;
    fetchAll();
  }, [ready, fetchAll]);

  function toggleExpanded(id: number) {
    setExpanded((prev) => ({ ...prev, [id]: !prev[id] }));
  }

  // Auth guard
  if (!ready) return null;

  // Derived view state (safe even before panel loads)
  const showValue = panel?.show_value ?? false;
  const cohorts = panel?.cohorts ?? [];
  const allPatients = panel?.patients ?? [];

  // Active cohort → id set for client-side filtering
  const activeCohortDef =
    activeCohort === ALL_COHORT_KEY
      ? null
      : cohorts.find((c) => c.key === activeCohort) ?? null;
  const filteredPatients: ControlRoomPatient[] = activeCohortDef
    ? allPatients.filter((p) => activeCohortDef.ids.includes(p.id))
    : allPatients;

  // Number of body columns (for the expanded-row colspan)
  const colCount = showValue ? 7 : 6;

  return (
    <div className={styles.layout}>
      <Nav
        currentPath={pathname ?? "/control-room"}
        pageTitle="اتاقِ کنترل"
        onLogout={logout}
      />

      <main className={styles.main} id="main-content">
        <div className={styles.pageHeader}>
          <h1 className={styles.pageTitle}>اتاقِ کنترل</h1>
          {!loading && !error && panel && (
            <span className={styles.totalBadge}>
              مجموعِ بیمارانِ پراولویت: {toFarsiDigits(panel.total)}
            </span>
          )}
        </div>

        {/* Loading */}
        {loading && (
          <div className={styles.stateBox} role="status" aria-live="polite">
            <span className={styles.spinner} aria-hidden="true" />
            در حال بارگذاری…
          </div>
        )}

        {/* Whole-page error (panel failed) */}
        {!loading && error && (
          <div className={styles.errorBox} role="alert">
            <p>{error}</p>
            <button onClick={fetchAll} className={styles.retryBtn}>
              تلاش مجدد
            </button>
          </div>
        )}

        {/* Loaded */}
        {!loading && !error && panel && (
          <>
            {/* Cohort chip filter bar */}
            <div
              className={styles.cohortBar}
              role="group"
              aria-label="فیلترِ کوهورت"
            >
              <button
                type="button"
                onClick={() => setActiveCohort(ALL_COHORT_KEY)}
                className={
                  activeCohort === ALL_COHORT_KEY
                    ? `${styles.filterBtn} ${styles.filterBtnActive}`
                    : styles.filterBtn
                }
                aria-pressed={activeCohort === ALL_COHORT_KEY}
              >
                همه ({toFarsiDigits(panel.total)})
              </button>
              {cohorts.map((c) => (
                <button
                  key={c.key}
                  type="button"
                  onClick={() => setActiveCohort(c.key)}
                  className={
                    activeCohort === c.key
                      ? `${styles.filterBtn} ${styles.filterBtnActive}`
                      : styles.filterBtn
                  }
                  aria-pressed={activeCohort === c.key}
                >
                  {c.label} ({toFarsiDigits(c.count)})
                </button>
              ))}
            </div>

            {/* Empty = good news, not an error */}
            {filteredPatients.length === 0 ? (
              <div className={styles.stateBox} role="status">
                {activeCohort === ALL_COHORT_KEY
                  ? "هیچ بیمارِ پراولویتی نیست — همه‌چیز تحتِ کنترل است."
                  : "هیچ بیماری در این کوهورت نیست."}
              </div>
            ) : (
              <div className={styles.tableWrapper}>
                <table
                  className={styles.table}
                  aria-label="بیمارانِ پراولویتِ اتاقِ کنترل"
                >
                  <thead>
                    <tr>
                      <th scope="col">بیمار</th>
                      <th scope="col">وضعیتِ کنترل</th>
                      <th scope="col">هشدارها</th>
                      <th scope="col">آخرین مراجعه</th>
                      <th scope="col">نوبتِ پیش‌رو</th>
                      {showValue && (
                        <th scope="col" className={styles.revenueCell}>
                          درآمد
                        </th>
                      )}
                      <th scope="col">اولویت</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredPatients.map((p) => {
                      const ctl = controlDisplay(p.control);
                      const breakdown = parseBreakdown(p.breakdown);
                      const isExpanded = expanded[p.id] ?? false;
                      const detailId = `breakdown-${p.id}`;

                      return [
                        <tr key={p.id} className={styles.tableRow}>
                          {/* Patient name (no PHI link — response has no uuid) */}
                          <td className={styles.nameCell}>
                            <span>{p.full_name ?? "بیمار ناشناس"}</span>
                            {p.opt_out && (
                              <span
                                className={styles.optOutChip}
                                aria-label="این بیمار از دریافتِ پیام انصراف داده است"
                              >
                                انصراف از پیام
                              </span>
                            )}
                          </td>

                          {/* Control status badge — four-state, text always present */}
                          <td>
                            <span
                              className={`${styles.controlBadge} ${
                                styles[`control_${ctl.key}`]
                              }`}
                              aria-label={`وضعیتِ کنترل: ${ctl.label}`}
                            >
                              <span aria-hidden="true">{ctl.icon}</span>{" "}
                              {ctl.label}
                            </span>
                          </td>

                          {/* Warnings: danger + warn chips (icon + text + colour) */}
                          <td>
                            <div className={styles.chipStack}>
                              {p.flags.map((f, i) => {
                                const chip = dangerChip(f);
                                return (
                                  <span
                                    key={`d-${i}`}
                                    className={`${styles.sevChip} ${styles.sevDanger}`}
                                    aria-label={chip.ariaLabel}
                                  >
                                    <span aria-hidden="true">{chip.icon}</span>{" "}
                                    {chip.label}
                                  </span>
                                );
                              })}
                              {p.warns.map((f, i) => {
                                const chip = warnChip(f);
                                return (
                                  <span
                                    key={`w-${i}`}
                                    className={`${styles.sevChip} ${styles.sevWarn}`}
                                    aria-label={chip.ariaLabel}
                                  >
                                    <span aria-hidden="true">{chip.icon}</span>{" "}
                                    {chip.label}
                                  </span>
                                );
                              })}
                              {p.flags.length === 0 &&
                                p.warns.length === 0 && (
                                  <span className="text-muted">—</span>
                                )}
                            </div>
                          </td>

                          {/* Last visit + days-ago + lapsed chip */}
                          <td>
                            {p.last_observed_at ? (
                              <>
                                <span className={styles.monoInline}>
                                  {formatJalali(p.last_observed_at)}
                                </span>
                                {p.days_since_last != null && (
                                  <span className={styles.subLine}>
                                    {toFarsiDigits(p.days_since_last)} روز پیش
                                  </span>
                                )}
                              </>
                            ) : (
                              <span className="text-muted">بدونِ سابقه</span>
                            )}
                            {p.lapsed && (
                              <span
                                className={`${styles.sevChip} ${styles.sevWarn} ${styles.lapsedChip}`}
                                aria-label="وقفه در مراقبت"
                              >
                                <span aria-hidden="true">●</span> وقفه در مراقبت
                              </span>
                            )}
                          </td>

                          {/* Upcoming appointment (bool only) */}
                          <td>
                            {p.upcoming ? (
                              <span
                                className={styles.upcomingChip}
                                aria-label="نوبت دارد"
                              >
                                <span aria-hidden="true">✓</span> نوبت دارد
                              </span>
                            ) : (
                              <span
                                className="text-muted"
                                aria-label="نوبتی ثبت نشده"
                              >
                                —
                              </span>
                            )}
                          </td>

                          {/* Revenue — manager-only column (server gate) */}
                          {showValue && (
                            <td
                              className={styles.revenueCell}
                              aria-label={
                                p.value != null
                                  ? `درآمد: ${formatToman(p.value)}`
                                  : "درآمد: ندارد"
                              }
                            >
                              {p.value != null ? formatToman(p.value) : "—"}
                            </td>
                          )}

                          {/* Priority score + «چرا؟» expand toggle */}
                          <td>
                            <div className={styles.scoreCell}>
                              <span
                                className={styles.scoreBadge}
                                aria-label={`امتیازِ اولویت: ${toFarsiDigits(p.score)}`}
                              >
                                {toFarsiDigits(p.score)}
                              </span>
                              <button
                                type="button"
                                className={styles.whyBtn}
                                onClick={() => toggleExpanded(p.id)}
                                aria-expanded={isExpanded}
                                aria-controls={detailId}
                              >
                                چرا؟
                              </button>
                            </div>
                          </td>
                        </tr>,
                        <tr
                          key={`${p.id}-detail`}
                          id={detailId}
                          className={styles.detailRow}
                          hidden={!isExpanded}
                        >
                          <td colSpan={colCount}>
                            {breakdown.length > 0 ? (
                              <ul className={styles.breakdownList}>
                                {breakdown.map((b, i) => (
                                  <li key={i} className={styles.breakdownItem}>
                                    <span>{b.label}</span>
                                    <span className={styles.breakdownPoints}>
                                      {b.points >= 0 ? "+" : ""}
                                      {toFarsiDigits(b.points)}
                                    </span>
                                  </li>
                                ))}
                              </ul>
                            ) : (
                              <span className="text-muted">
                                جزئیاتِ امتیاز در دسترس نیست.
                              </span>
                            )}
                          </td>
                        </tr>,
                      ];
                    })}
                  </tbody>
                </table>
              </div>
            )}

            {/* Conversion card — honesty over decoration */}
            <section
              className={styles.conversionCard}
              role="region"
              aria-label="نرخِ تبدیلِ پیگیری به ویزیت"
            >
              <h2 className={styles.conversionTitle}>
                نرخِ تبدیلِ پیگیری به ویزیت
              </h2>

              {conversionError ? (
                <p className={styles.conversionError} role="alert">
                  {conversionError}
                </p>
              ) : conversion == null ? (
                <p className="text-muted">—</p>
              ) : !conversion.n_sufficient ||
                conversion.overall_conversion == null ? (
                <>
                  <p className={styles.conversionHint}>
                    هنوز دادهٔ کافی برای محاسبهٔ نرخ نیست (کمتر از ۳۰).
                  </p>
                  <p className={styles.conversionFraming} role="note">
                    <span aria-hidden="true">ℹ </span>
                    {conversion.framing}
                  </p>
                </>
              ) : (
                <>
                  <dl className={styles.rateGrid}>
                    <div className={styles.rateItem}>
                      <dt>نرخِ تماسِ مؤثر</dt>
                      <dd>
                        {conversion.contact_rate != null
                          ? formatRate(conversion.contact_rate)
                          : "—"}
                      </dd>
                    </div>
                    <div className={styles.rateItem}>
                      <dt>نرخِ ویزیتِ مراجعان</dt>
                      <dd>
                        {conversion.visit_rate_of_reached != null
                          ? formatRate(conversion.visit_rate_of_reached)
                          : "—"}
                      </dd>
                    </div>
                    <div className={styles.rateItem}>
                      <dt>تبدیلِ کلی</dt>
                      <dd>{formatRate(conversion.overall_conversion)}</dd>
                    </div>
                  </dl>
                  <p className={styles.conversionFraming} role="note">
                    <span aria-hidden="true">ℹ </span>
                    {conversion.framing}
                  </p>
                </>
              )}
            </section>
          </>
        )}
      </main>
    </div>
  );
}
