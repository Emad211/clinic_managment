"use client";

/**
 * Manager Outcomes dashboard — /manager/outcomes  (cluster K, step 50).
 *
 * Manager-only descriptive analytics. Two STRICTLY-separated regions:
 *   A) «فعالیت و پذیرشِ ما» (process)  — acceptance, funnel, lapsed→return.
 *   B) «وضعیتِ بیماران» (descriptive)  — cohort-outcome, control-trend.
 *
 * HONESTY RULES (locked by the clinical-data-scientist gathering):
 *   - A global non-causal banner sits at the top.
 *   - Process metrics and patient-state outcomes NEVER share a card/chart
 *     (combining them would imply causality the data cannot support).
 *   - Every NULL value renders the shared "دادهٔ ناکافی" copy — NEVER 0/خطا/empty.
 *   - All visuals are offline (CSS bars + inline SVG) — no chart library.
 */

import { useEffect, useState, useCallback } from "react";
import { usePathname } from "next/navigation";
import {
  getRole,
  getSuggestionStats,
  getConversion,
  getCohortOutcomes,
  getLapsedReturn,
  getControlTrend,
  ApiError,
  type SuggestionStatsResponse,
  type ConversionResponse,
  type CohortOutcomesResponse,
  type CohortCondition,
  type CohortMetric,
  type CohortWindow,
  type LapsedReturnResponse,
  type ControlTrendResponse,
  type ControlTrendBucket,
} from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";
import { toFarsiDigits, formatJalali } from "@/lib/jalali";
import Nav from "@/components/Nav";
import styles from "./outcomes.module.css";

// ─────────────────────────────────────────────────────────────
// Shared NULL formatter — the single source of truth for the
// "insufficient data" copy. NEVER returns 0 / empty / error text.
// ─────────────────────────────────────────────────────────────

/** Persian copy shown wherever a rate/mean/delta is null. */
function insufficientText(minN: number): string {
  return `دادهٔ ناکافی برای نتیجه‌گیری (حداقل: ${toFarsiDigits(minN)})`;
}

/** Render a percentage value (0–100) in Persian digits, or the NULL copy. */
function PercentOrInsufficient({
  value,
  minN,
}: {
  value: number | null;
  minN: number;
}) {
  if (value === null || value === undefined) {
    return <span className={styles.insufficient}>{insufficientText(minN)}</span>;
  }
  return (
    <span className={styles.metricValue}>
      {toFarsiDigits(Math.round(value * 10) / 10)}
      <span className={styles.metricUnit}>٪</span>
    </span>
  );
}

/** Round to one decimal and convert to Persian digits (signed). */
function faNumber(n: number): string {
  const r = Math.round(n * 10) / 10;
  return toFarsiDigits(r);
}

// ─────────────────────────────────────────────────────────────
// CSS percentage bar (0–100). Null → hatched grey track, no fill.
// ─────────────────────────────────────────────────────────────

function PercentBar({
  value,
  ok,
  label,
}: {
  value: number | null;
  ok?: boolean;
  label: string;
}) {
  if (value === null || value === undefined) {
    return (
      <div
        className={`${styles.barTrack} ${styles.barTrackNull}`}
        role="img"
        aria-label={`${label}: دادهٔ ناکافی`}
      />
    );
  }
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div
      className={styles.barTrack}
      role="img"
      aria-label={`${label}: ${faNumber(pct)} درصد`}
    >
      <div
        className={`${styles.barFill}${ok ? ` ${styles.barFillOk}` : ""}`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Region A — Process: acceptance, funnel, lapsed→return
// ─────────────────────────────────────────────────────────────

function AcceptanceCard({ data }: { data: SuggestionStatsResponse }) {
  // Aggregate an overall acceptance across all rules that have a reliable rate.
  const reliable = data.rules.filter(
    (r) => r.acceptance_rate_of_acted !== null,
  );
  const totalAccepted = data.rules.reduce((s, r) => s + r.n_accepted, 0);
  const totalActed = data.rules.reduce((s, r) => s + r.n_acted, 0);
  const overall =
    totalActed >= data.min_n_for_rate
      ? (totalAccepted / totalActed) * 100
      : null;

  return (
    <div className={styles.card} role="region" aria-label="پذیرشِ پیشنهادها">
      <span className={styles.cardTitle}>پذیرشِ پیشنهادهای بالینی</span>
      <span className={styles.cardSub}>
        از میانِ پیشنهادهایی که پزشک رویشان اقدام کرده، چه نسبتی را پذیرفته است.
      </span>
      <PercentOrInsufficient value={overall} minN={data.min_n_for_rate} />
      <PercentBar value={overall} label="نرخِ پذیرش" />
      <span className={styles.metricCaption}>
        {overall !== null
          ? `${toFarsiDigits(totalAccepted)} پذیرفته از ${toFarsiDigits(totalActed)} اقدام`
          : `قواعدِ دارای نرخِ معتبر: ${toFarsiDigits(reliable.length)} از ${toFarsiDigits(data.rules.length)}`}
      </span>
      <p className={styles.cardFraming}>{data.framing}</p>
    </div>
  );
}

function FunnelCard({ data }: { data: ConversionResponse }) {
  const rows: { label: string; value: number | null }[] = [
    { label: "نرخِ تماسِ موفق", value: data.contact_rate },
    { label: "تبدیل به ویزیت (از تماس‌شده‌ها)", value: data.visit_rate_of_reached },
    { label: "تبدیلِ کلی به ویزیت", value: data.overall_conversion },
  ];
  // The funnel's min-n is its eligibility threshold (30) — surfaced as window_days
  // is the lookback, not the min-n; the backend uses 30 eligible as the gate.
  const minN = 30;
  return (
    <div
      className={styles.card}
      role="region"
      aria-label="قیفِ پیگیری به ویزیت"
    >
      <span className={styles.cardTitle}>قیفِ پیگیری ← ویزیت</span>
      <span className={styles.cardSub}>
        از پیگیری‌های واجدِ شرایط (سررسیدِ حداقل {toFarsiDigits(data.window_days)}
        ‌روزه)، چه نسبتی به تماس و سپس ویزیت رسیده است.
      </span>
      {rows.map((row) => (
        <div className={styles.funnelRow} key={row.label}>
          <div className={styles.funnelLabel}>
            <span>{row.label}</span>
            {row.value !== null ? (
              <span className={styles.funnelPct}>{faNumber(row.value)}٪</span>
            ) : null}
          </div>
          {row.value !== null ? (
            <PercentBar value={row.value} label={row.label} />
          ) : (
            <span className={styles.insufficient}>{insufficientText(minN)}</span>
          )}
        </div>
      ))}
      <span className={styles.metricCaption}>
        واجدِ شرایط: {toFarsiDigits(data.generated_eligible)} پیگیری
      </span>
      <p className={styles.cardFraming}>{data.framing}</p>
    </div>
  );
}

function LapsedReturnCard({ data }: { data: LapsedReturnResponse }) {
  return (
    <div
      className={styles.card}
      role="region"
      aria-label="بازگشتِ بیمارانِ غیبت‌کرده"
    >
      <span className={styles.cardTitle}>بازگشتِ بیمارانِ غیبت‌کرده</span>
      <span className={styles.cardSub}>
        از بیمارانی که بیش از {toFarsiDigits(data.lapse_window_days)} روز مراجعه
        نکرده بودند، چه نسبتی ظرفِ {toFarsiDigits(data.return_window_days)} روز
        بازگشتند.
      </span>
      <PercentOrInsufficient value={data.return_rate} minN={data.min_n} />
      <PercentBar value={data.return_rate} label="نرخِ بازگشت" />
      <span className={styles.metricCaption}>
        {data.return_rate !== null
          ? `${toFarsiDigits(data.returned)} بازگشته از ${toFarsiDigits(data.denominator)} غیبت‌کرده`
          : `جامعهٔ آماری: ${toFarsiDigits(data.denominator)} بیمار`}
      </span>
      <p className={styles.cardFraming}>{data.framing}</p>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Region B — Patient state (descriptive): cohort-outcome, control-trend
// ─────────────────────────────────────────────────────────────

/** Format a cohort window (mean + paired delta), honouring NULL. */
function CohortWindowCells({
  win,
  minN,
  direction,
}: {
  win: CohortWindow;
  minN: number;
  direction: string;
}) {
  // mean cell
  const meanCell =
    win.mean === null ? (
      <span className={styles.nullCell}>{insufficientText(minN)}</span>
    ) : (
      <span className={styles.numCell}>{faNumber(win.mean)}</span>
    );
  // delta cell — signed; arrow indicates improvement vs the indicator direction
  const deltaCell =
    win.delta === null ? (
      <span className={styles.nullCell}>{insufficientText(minN)}</span>
    ) : (
      <span className={styles.numCell}>
        {win.delta > 0 ? "+" : ""}
        {faNumber(win.delta)}
      </span>
    );
  return (
    <>
      <td>{meanCell}</td>
      <td>
        {deltaCell}
        {win.delta !== null && (
          <span className={styles.metricCaption}>
            {" "}
            (n={toFarsiDigits(win.n_paired)})
          </span>
        )}
      </td>
    </>
  );
}

function CohortMetricRow({
  metric,
  minN,
}: {
  metric: CohortMetric;
  minN: number;
}) {
  return (
    <tr>
      <td>
        {metric.metric_key}
        {metric.unit ? (
          <span className={styles.metricCaption}> ({metric.unit})</span>
        ) : null}
      </td>
      <td className={styles.numCell}>{toFarsiDigits(metric.n_baseline)}</td>
      <CohortWindowCells win={metric.m3} minN={minN} direction={metric.direction} />
      <CohortWindowCells win={metric.m6} minN={minN} direction={metric.direction} />
    </tr>
  );
}

function CohortConditionBlock({
  cond,
  minN,
}: {
  cond: CohortCondition;
  minN: number;
}) {
  return (
    <div className={styles.conditionGroup}>
      <div className={styles.conditionTitle}>{cond.condition_label}</div>
      <div className={styles.conditionMeta}>
        کلِ بیماران: {toFarsiDigits(cond.n_cohort)} · دارای پایه:{" "}
        {toFarsiDigits(cond.n_baseline)}
      </div>
      {cond.reason === "cohort_too_small" || cond.metrics === null ? (
        <span className={styles.insufficient}>{insufficientText(minN)}</span>
      ) : (
        <div className={styles.tableWrapper}>
          <table className={styles.table} aria-label={`شاخص‌های ${cond.condition_label}`}>
            <thead>
              <tr>
                <th scope="col">شاخص</th>
                <th scope="col">پایه (n)</th>
                <th scope="col">۳ماه (میانگین)</th>
                <th scope="col">۳ماه (تغییر)</th>
                <th scope="col">۶ماه (میانگین)</th>
                <th scope="col">۶ماه (تغییر)</th>
              </tr>
            </thead>
            <tbody>
              {cond.metrics.map((m) => (
                <CohortMetricRow key={m.metric_key} metric={m} minN={minN} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function CohortOutcomesCard({ data }: { data: CohortOutcomesResponse }) {
  return (
    <div
      className={`${styles.card} ${styles.cardWide}`}
      role="region"
      aria-label="وضعیتِ توصیفیِ کوهورت"
    >
      <span className={styles.cardTitle}>روندِ توصیفیِ شاخص‌های بیماری</span>
      <span className={styles.cardSub}>
        میانگین و تغییرِ شاخص‌های کلیدی نسبت به پایه، per-condition. این نمایِ
        تک‌گروهی است؛ نه گروهِ کنترل، نه ادعای علّی.
      </span>
      {data.conditions.length === 0 ? (
        <span className={styles.insufficient}>{insufficientText(30)}</span>
      ) : (
        data.conditions.map((c) => (
          <CohortConditionBlock key={c.condition_code} cond={c} minN={30} />
        ))
      )}
      <p className={styles.cardFraming}>{data.framing}</p>
      <p className={styles.cardFraming}>{data.caveat}</p>
    </div>
  );
}

// ── Control-trend inline-SVG bar chart (offline, no library) ──

function ControlTrendCard({ data }: { data: ControlTrendResponse }) {
  // Group buckets by condition, ordered by ym ascending within each.
  const byCondition = new Map<string, ControlTrendBucket[]>();
  for (const b of data.buckets) {
    const arr = byCondition.get(b.condition) ?? [];
    arr.push(b);
    byCondition.set(b.condition, arr);
  }
  for (const arr of byCondition.values()) {
    arr.sort((a, b) => a.ym.localeCompare(b.ym));
  }

  const conditions = Array.from(byCondition.keys()).sort();

  return (
    <div
      className={`${styles.card} ${styles.cardWide}`}
      role="region"
      aria-label="روندِ زمانیِ کنترلِ بیماری"
    >
      <span className={styles.cardTitle}>روندِ زمانیِ نرخِ کنترل</span>
      <span className={styles.cardSub}>
        درصدِ بیمارانِ «کنترل‌شده» در هر ماه. ماه‌های کم‌داده با گذرگاهِ خاکستریِ
        هاشورخورده (نه نقطهٔ صفر) نمایش داده می‌شوند.
      </span>

      {data.buckets.length === 0 ? (
        <span className={styles.insufficient}>{insufficientText(data.min_n)}</span>
      ) : (
        conditions.map((cond) => {
          const buckets = byCondition.get(cond)!;
          return (
            <TrendSvg
              key={cond}
              condition={cond}
              buckets={buckets}
              minN={data.min_n}
            />
          );
        })
      )}

      <div className={styles.trendLegend} aria-hidden="true">
        <span className={styles.trendLegendItem}>
          <span className={styles.legendSwatchOk} /> ماهِ دارای داده
        </span>
        <span className={styles.trendLegendItem}>
          <span className={styles.legendSwatchNull} /> دادهٔ ناکافی (n کم)
        </span>
      </div>

      <p className={styles.cardFraming}>{data.framing}</p>
    </div>
  );
}

/** One condition's monthly bar chart, drawn with inline SVG. */
function TrendSvg({
  condition,
  buckets,
  minN,
}: {
  condition: string;
  buckets: ControlTrendBucket[];
  minN: number;
}) {
  const W = 640;
  const H = 160;
  const padBottom = 28;
  const padTop = 12;
  const padX = 8;
  const n = buckets.length;
  const slot = (W - padX * 2) / Math.max(1, n);
  const barW = Math.max(4, slot * 0.6);
  const plotH = H - padBottom - padTop;

  return (
    <div className={styles.conditionGroup}>
      <div className={styles.conditionTitle}>{condition}</div>
      <svg
        className={styles.trendChart}
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`روندِ نرخِ کنترلِ ${condition} به تفکیکِ ماه`}
        preserveAspectRatio="xMidYMid meet"
      >
        {/* baseline axis */}
        <line
          x1={padX}
          y1={H - padBottom}
          x2={W - padX}
          y2={H - padBottom}
          stroke="var(--color-border)"
          strokeWidth={1}
        />
        {buckets.map((b, i) => {
          const cx = padX + slot * i + slot / 2;
          const x = cx - barW / 2;
          const ymLabel = toFarsiDigits(b.ym);
          if (b.pct_controlled === null) {
            // Gap: hatched grey full-height placeholder, NOT a zero point.
            return (
              <g key={b.ym}>
                <rect
                  x={x}
                  y={padTop}
                  width={barW}
                  height={plotH}
                  fill="url(#nullHatch)"
                  stroke="var(--color-border)"
                  strokeWidth={0.5}
                >
                  <title>{`${ymLabel}: دادهٔ ناکافی (حداقل ${toFarsiDigits(minN)})`}</title>
                </rect>
                <text
                  x={cx}
                  y={H - padBottom + 16}
                  textAnchor="middle"
                  fontSize="9"
                  fill="var(--color-text-muted)"
                >
                  {ymLabel}
                </text>
              </g>
            );
          }
          const pct = Math.max(0, Math.min(100, b.pct_controlled));
          const barH = (pct / 100) * plotH;
          const y = padTop + (plotH - barH);
          return (
            <g key={b.ym}>
              <rect
                x={x}
                y={y}
                width={barW}
                height={barH}
                rx={2}
                fill="var(--color-ok)"
              >
                <title>{`${ymLabel}: ${faNumber(pct)}٪ کنترل‌شده (n=${toFarsiDigits(b.assessable_n)})`}</title>
              </rect>
              <text
                x={cx}
                y={y - 3}
                textAnchor="middle"
                fontSize="9"
                fill="var(--color-text-muted)"
              >
                {faNumber(pct)}
              </text>
              <text
                x={cx}
                y={H - padBottom + 16}
                textAnchor="middle"
                fontSize="9"
                fill="var(--color-text-muted)"
              >
                {ymLabel}
              </text>
            </g>
          );
        })}
        <defs>
          <pattern
            id="nullHatch"
            width="6"
            height="6"
            patternTransform="rotate(45)"
            patternUnits="userSpaceOnUse"
          >
            <rect width="6" height="6" fill="#ededed" />
            <line x1="0" y1="0" x2="0" y2="6" stroke="#cfcfcf" strokeWidth="3" />
          </pattern>
        </defs>
      </svg>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────

interface FetchState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

const initial = <T,>(): FetchState<T> => ({
  data: null,
  loading: true,
  error: null,
});

export default function ManagerOutcomesPage() {
  const { ready, logout } = useAuth();
  const pathname = usePathname();

  // Role gate — read once auth is ready.
  const [isManager, setIsManager] = useState<boolean | null>(null);

  const [stats, setStats] = useState<FetchState<SuggestionStatsResponse>>(initial);
  const [conv, setConv] = useState<FetchState<ConversionResponse>>(initial);
  const [lapsed, setLapsed] = useState<FetchState<LapsedReturnResponse>>(initial);
  const [cohort, setCohort] = useState<FetchState<CohortOutcomesResponse>>(initial);
  const [trend, setTrend] = useState<FetchState<ControlTrendResponse>>(initial);

  const handle401 = useCallback(
    (err: unknown): boolean => {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return true;
      }
      return false;
    },
    [logout],
  );

  const loadAll = useCallback(async () => {
    // Generic loader for a single section.
    async function run<T>(
      fn: () => Promise<T>,
      set: (s: FetchState<T>) => void,
    ) {
      set({ data: null, loading: true, error: null });
      try {
        const data = await fn();
        set({ data, loading: false, error: null });
      } catch (err) {
        if (handle401(err)) return;
        let msg = "خطا در دریافت داده";
        if (err instanceof ApiError) {
          if (err.status === 403) msg = "دسترسی محدود است.";
          else msg = err.message;
        }
        set({ data: null, loading: false, error: msg });
      }
    }

    await Promise.all([
      run(getSuggestionStats, setStats),
      run(getConversion, setConv),
      run(getLapsedReturn, setLapsed),
      run(getCohortOutcomes, setCohort),
      run(getControlTrend, setTrend),
    ]);
  }, [handle401]);

  useEffect(() => {
    if (!ready) return;
    const manager = getRole() === "manager";
    setIsManager(manager);
    if (manager) {
      loadAll();
    }
  }, [ready, loadAll]);

  if (!ready) return null;

  // ── Non-manager: access restricted ──────────────────────────
  if (isManager === false) {
    return (
      <div className={styles.layout}>
        <Nav currentPath={pathname ?? "/manager/outcomes"} onLogout={logout} />
        <main className={styles.main} id="main-content">
          <div className={styles.restrictedBox} role="alert">
            <p className={styles.restrictedTitle}>دسترسی محدود</p>
            <p>این صفحه فقط برای مدیر در دسترس است.</p>
          </div>
        </main>
      </div>
    );
  }

  // While role is still resolving, render the shell (avoids flash).
  if (isManager === null) return null;

  return (
    <div className={styles.layout}>
      <Nav
        currentPath={pathname ?? "/manager/outcomes"}
        pageTitle="گزارشِ outcome"
        onLogout={logout}
        showManagerLinks
      />

      <main className={styles.main} id="main-content" aria-label="گزارشِ outcome مدیر">
        <div className={styles.pageHeader}>
          <h1 className={styles.pageTitle}>گزارشِ outcome</h1>
        </div>

        {/* Global non-causal banner */}
        <div className={styles.causalBanner} role="note" aria-label="هشدارِ غیرعلّی بودنِ داده‌ها">
          <span className={styles.causalBannerTitle}>این داده‌ها علّی نیستند</span>
          <span className={styles.causalBannerBody}>
            این گزارش‌ها توصیفی و همبستگی‌محور هستند، نه اثباتِ علّی. تغییرِ یک
            شاخص می‌تواند ناشی از عواملِ متعدد (بازگشت به میانگین، سوگیریِ
            انتخاب، فصل) باشد. برای استنتاجِ علّی به گروهِ کنترل/holdout نیاز است.
          </span>
        </div>

        {/* ── Region A: process / our activity ── */}
        <section className={styles.region} aria-label="فعالیت و پذیرشِ ما">
          <div className={`${styles.regionHeader} ${styles.regionHeaderProcess}`}>
            <span className={styles.regionTitle}>فعالیت و پذیرشِ ما</span>
            <span className={styles.regionSub}>
              این بخش رفتارِ تیم را اندازه می‌گیرد (process)، نه وضعیتِ بیماران.
            </span>
          </div>

          <div className={styles.cardGrid}>
            <SectionCard
              state={stats}
              label="پذیرشِ پیشنهادها"
              onRetry={loadAll}
              render={(d) => <AcceptanceCard data={d} />}
            />
            <SectionCard
              state={conv}
              label="قیفِ پیگیری به ویزیت"
              onRetry={loadAll}
              render={(d) => <FunnelCard data={d} />}
            />
            <SectionCard
              state={lapsed}
              label="بازگشتِ بیمارانِ غیبت‌کرده"
              onRetry={loadAll}
              render={(d) => <LapsedReturnCard data={d} />}
            />
          </div>
        </section>

        {/* Explicit visual boundary between the two regions */}
        <hr className={styles.regionDivider} aria-hidden="true" />

        {/* ── Region B: descriptive patient state ── */}
        <section className={styles.region} aria-label="وضعیتِ بیماران">
          <div className={`${styles.regionHeader} ${styles.regionHeaderState}`}>
            <span className={styles.regionTitle}>وضعیتِ بیماران</span>
            <span className={styles.regionSub}>
              این بخش توصیفِ وضعیتِ بالینیِ بیماران است (descriptive) — مستقل از
              فعالیتِ ما؛ هیچ ربطِ علّی به بخشِ بالا ندارد.
            </span>
          </div>

          <div className={styles.cardGrid}>
            <SectionCard
              state={cohort}
              label="روندِ توصیفیِ شاخص‌های بیماری"
              onRetry={loadAll}
              render={(d) => <CohortOutcomesCard data={d} />}
            />
            <SectionCard
              state={trend}
              label="روندِ زمانیِ نرخِ کنترل"
              onRetry={loadAll}
              render={(d) => <ControlTrendCard data={d} />}
            />
          </div>
        </section>
      </main>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// SectionCard — wraps loading / error / data states for one section.
// ─────────────────────────────────────────────────────────────

function SectionCard<T>({
  state,
  label,
  onRetry,
  render,
}: {
  state: FetchState<T>;
  label: string;
  onRetry: () => void;
  render: (data: T) => React.ReactNode;
}) {
  if (state.loading) {
    return (
      <div className={styles.stateBox} role="status" aria-live="polite" aria-label={`در حال بارگذاری ${label}`}>
        <span className={styles.spinner} aria-hidden="true" />
        در حال بارگذاری…
      </div>
    );
  }
  if (state.error) {
    return (
      <div className={styles.errorBox} role="alert">
        <p>{`خطا در «${label}»: ${state.error}`}</p>
        <button type="button" className={styles.retryBtn} onClick={onRetry}>
          تلاش مجدد
        </button>
      </div>
    );
  }
  if (state.data === null) {
    return (
      <div className={styles.emptyNote} role="status">
        دادهٔ ناکافی برای نمایش.
      </div>
    );
  }
  return <>{render(state.data)}</>;
}
