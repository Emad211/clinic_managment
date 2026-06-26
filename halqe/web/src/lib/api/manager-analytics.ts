/**
 * Manager Outcomes Dashboard (cluster K) — 5 read-only, manager-only endpoints.
 *
 * All rate/mean/delta fields are `number | null` — null = "insufficient data",
 * NEVER 0. The UI must render the "دادهٔ ناکافی" copy for null, never zero.
 *
 * IMPORTANT honesty boundary: process metrics (acceptance, funnel, lapsed→return)
 * and descriptive patient-state outcomes (cohort-outcome, control-trend) live in
 * two SEPARATE response shapes here and MUST be rendered in two separate UI
 * regions — never combined in one card/chart (would imply false causality).
 */
import { apiFetch } from "./_core";

// ── 1) GET /manager/suggestion-stats  (Step 41) ──────────────
// Mirrors SuggestionStatsResponseDTO + SuggestionRuleStatsDTO (config/api.py).

export interface SuggestionRuleStats {
  rule_code: string;
  n_accepted: number;
  n_dismissed: number;
  n_pending: number;
  n_acted: number;                                  // = accepted + dismissed
  n_fired_patient_days: number;                     // count of fired_daily events
  /** NULL when n_acted < min_n_for_rate — render "دادهٔ ناکافی", never 0. */
  acceptance_rate_of_acted: number | null;
  rate_reliable: boolean;
  /** NULL when n_fired_patient_days < 10 — render "دادهٔ ناکافی", never 0. */
  impression_acceptance_rate: number | null;
  impression_rate_reliable: boolean;
  last_action_at: string | null;                    // ISO datetime or null
}

export interface SuggestionStatsResponse {
  generated_at: string;                             // ISO datetime
  min_n_for_rate: number;
  framing: string;
  rules: SuggestionRuleStats[];
}

/** GET /manager/suggestion-stats — manager-only (staff → 403). */
export async function getSuggestionStats(): Promise<SuggestionStatsResponse> {
  return apiFetch<SuggestionStatsResponse>("/manager/suggestion-stats");
}

// ── 2) GET /control-room/conversion  (Step 42) ───────────────
// Mirrors ConversionResponse (config/api.py). Rates NULL when n_sufficient=false.

export interface ConversionResponse {
  window_days: number;
  generated: number;
  generated_eligible: number;
  resolved_done: number;
  resolved_dismissed: number;
  open_eligible: number;
  to_visit: number;
  /** NULL when generated_eligible < 30 — render "دادهٔ ناکافی", never 0. */
  contact_rate: number | null;
  /** NULL when generated_eligible < 30 — render "دادهٔ ناکافی", never 0. */
  visit_rate_of_reached: number | null;
  /** Headline KPI. NULL when generated_eligible < 30 — render "دادهٔ ناکافی". */
  overall_conversion: number | null;
  n_sufficient: boolean;
  framing: string;
}

/** GET /control-room/conversion — JWT required (any authed user). */
export async function getConversion(): Promise<ConversionResponse> {
  return apiFetch<ConversionResponse>("/control-room/conversion");
}

// ── 3) GET /manager/cohort-outcomes  (Step 49) ───────────────
// Mirrors CohortOutcomesResponseDTO + nested DTOs (config/api.py).

export interface CohortWindow {
  n: number;
  /** NULL when n < min_n — render "دادهٔ ناکافی", never 0. */
  mean: number | null;
  n_paired: number;
  /** NULL when n_paired < min_n — render "دادهٔ ناکافی", never 0. */
  delta: number | null;
  reason: string | null;       // window_n_insufficient | paired_n_insufficient | null
}

export interface CohortMetric {
  metric_key: string;
  metric_type: string;         // mean_delta | relative_median | percent_in_range
  unit: string | null;
  direction: string;           // high | low
  n_baseline: number;
  m3: CohortWindow;
  m6: CohortWindow;
}

export interface CohortSubgroup {
  key: string;
  metric: CohortMetric;
}

export interface CohortStratification {
  by: string;                  // frailty | ascvd
  reason: string | null;       // subgroup_too_small | null
  subgroups: CohortSubgroup[] | null;
  n_positive: number | null;
  n_negative: number | null;
}

export interface CohortCondition {
  condition_code: string;
  condition_label: string;
  anchor: string;
  n_cohort: number;
  n_baseline: number;
  reason: string | null;       // cohort_too_small | null
  metrics: CohortMetric[] | null;   // NULL when cohort_too_small
  stratification: CohortStratification | null;
}

export interface CohortOutcomesResponse {
  tenant_id: number;
  framing: string;
  caveat: string;
  n_sufficient: number;
  conditions: CohortCondition[];
}

/** GET /manager/cohort-outcomes — manager-only (staff → 403). */
export async function getCohortOutcomes(): Promise<CohortOutcomesResponse> {
  return apiFetch<CohortOutcomesResponse>("/manager/cohort-outcomes");
}

// ── 4) GET /manager/lapsed-return  (new — cluster K) ─────────
// Contract locked by the task spec; the backend is being built in parallel.

export interface LapsedReturnResponse {
  denominator: number;
  returned: number;
  /** NULL when denominator < min_n — render "دادهٔ ناکافی", never 0. */
  return_rate: number | null;
  lapse_window_days: number;
  return_window_days: number;
  min_n: number;
  framing: string;
}

/** GET /manager/lapsed-return — manager-only (staff → 403). */
export async function getLapsedReturn(): Promise<LapsedReturnResponse> {
  return apiFetch<LapsedReturnResponse>("/manager/lapsed-return");
}

// ── 5) GET /manager/control-trend  (new — cluster K) ─────────
// Time series of % controlled per (year-month, condition).
// Contract locked by the task spec; the backend is being built in parallel.

export interface ControlTrendBucket {
  ym: string;                  // "YYYY-MM" (Gregorian year-month label)
  condition: string;
  assessable_n: number;
  controlled_n: number;
  /** NULL when assessable_n < min_n — render gap/grey, never a 0 point. */
  pct_controlled: number | null;
}

export interface ControlTrendResponse {
  buckets: ControlTrendBucket[];
  min_n: number;
  framing: string;
}

/** GET /manager/control-trend — manager-only (staff → 403). */
export async function getControlTrend(): Promise<ControlTrendResponse> {
  return apiFetch<ControlTrendResponse>("/manager/control-trend");
}
