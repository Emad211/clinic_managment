/**
 * Control Room domain — read-only client.
 *
 * Mirrors clinical/api/control_room.py:
 *   GET /control-room              → ControlRoomPanel (panel; show_value = manager)
 *   GET /control-room/conversion   → ConversionMetric (honest funnel)
 *   GET /control-room/cohort/{key} → CohortIds (recomputed server-side)
 *
 * This surface is GET-ONLY by design — the control room is a read-only triage
 * view. No state-changing function lives here (enforced by an architecture
 * guard test). Imports ONLY from ./_core, like every other per-domain module.
 */
import { apiFetch } from "./_core";

// ────────────────────────────────────────────────────────────
// Panel — GET /control-room
// ────────────────────────────────────────────────────────────

/** A danger or warn indicator flag for a patient. value is a numeric reading. */
export interface ControlRoomFlag {
  label: string;
  value: number;
}

export interface ControlRoomPatient {
  id: number; // patient_link_id
  patient_id: number; // accounting patient id
  full_name: string | null;
  phone_number: string | null;
  opt_out: boolean;
  /** uncontrolled | borderline | controlled | unknown */
  control: string;
  flags: ControlRoomFlag[]; // danger flags
  warns: ControlRoomFlag[]; // warn flags
  lapsed: boolean;
  days_since_last: number | null;
  last_observed_at: string | null; // ISO datetime or null
  open_fu: number;
  /** Revenue (Toman). Manager-only — null for staff. */
  value: number | null;
  score: number;
  /** [(label, points), ...] — OpenAPI types this as a loose array; render defensively. */
  breakdown: unknown[];
  conditions: string[];
  upcoming: boolean;
}

export interface ControlRoomCohort {
  key: string;
  label: string;
  count: number;
  ids: number[];
}

export interface ControlRoomPanel {
  patients: ControlRoomPatient[];
  cohorts: ControlRoomCohort[];
  median_rev: number;
  total: number;
  show_value: boolean;
}

/** Read-only: fetch the prioritized control-room panel for the authed tenant. */
export async function apiGetControlRoom(): Promise<ControlRoomPanel> {
  return apiFetch<ControlRoomPanel>(`/control-room`);
}

// ────────────────────────────────────────────────────────────
// Conversion — GET /control-room/conversion
// ────────────────────────────────────────────────────────────

export interface ConversionMetric {
  window_days: number;
  generated: number;
  generated_eligible: number;
  resolved_done: number;
  resolved_dismissed: number;
  open_eligible: number;
  to_visit: number;
  /** All three rates are null when n_sufficient === false (eligible < 30). */
  contact_rate: number | null;
  visit_rate_of_reached: number | null;
  overall_conversion: number | null;
  n_sufficient: boolean;
  framing: string;
}

/** Read-only: fetch the follow-up → visit conversion funnel metric. */
export async function apiGetConversion(): Promise<ConversionMetric> {
  return apiFetch<ConversionMetric>(`/control-room/conversion`);
}

// ────────────────────────────────────────────────────────────
// Cohort ids — GET /control-room/cohort/{key}
// ────────────────────────────────────────────────────────────

export interface CohortIds {
  cohort_key: string;
  ids: number[];
  count: number;
}

/**
 * Read-only: recompute a cohort's patient_link_ids server-side.
 *
 * NOTE: the control-room page filters client-side on panel.cohorts[].ids and
 * does NOT call this — it exists for completeness / future use. The key is
 * encoded into the path; valid keys: uncontrolled_lapsed, valuable_drifting
 * (manager only), overdue_care, uncontrolled.
 */
export async function apiGetCohortIds(key: string): Promise<CohortIds> {
  return apiFetch<CohortIds>(`/control-room/cohort/${encodeURIComponent(key)}`);
}
