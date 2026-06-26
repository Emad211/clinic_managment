/**
 * Screening Timeline domain — mirrors ScreeningTimelineResponse.
 */
import { apiFetch } from "./_core";

/**
 * Status of a single screening item.
 *   never_done  — has never been done; most prominent / highest-risk
 *   overdue     — done before, now past the due date
 *   due_soon    — due within the next 30 days
 *   ok          — up to date
 */
export type ScreeningStatus = "never_done" | "overdue" | "due_soon" | "ok";

/** One entry in the patient's screening calendar (e.g. HbA1c, urine albumin). */
export interface ScreeningItem {
  /** Machine-readable key, e.g. "a1c", "uacr", "eye_exam". */
  item_key: string;
  /** Human-readable Persian label, e.g. "هموگلوبین گلیکوزیله". */
  label_fa: string;
  /** ISO date (YYYY-MM-DD) of last time this was done. null = never done. */
  last_done_at: string | null;
  /** ISO date (YYYY-MM-DD) of next due date. null = cannot compute. */
  next_due_at: string | null;
  /** Current status. */
  status: ScreeningStatus;
  /** Recommended repeat interval in months. */
  interval_months: number;
  /** Which chronic-disease condition this item belongs to, e.g. "DM". */
  condition_code: string;
  /** Always true — this is a reminder, not a command. */
  suggestion_only: boolean;
}

/**
 * Response from GET /patients/{uuid}/screening-timeline.
 * items may be empty (patient has no applicable screenings).
 * Server delivers items pre-sorted: never_done/overdue first.
 */
export interface ScreeningTimelineResponse {
  patient_link_id: number;
  /** Safety framing string, e.g. "یادآوریِ غربالگری — تأیید با پزشک". */
  framing: string;
  /** Ordered list of screening items (server sort order must be preserved). */
  items: ScreeningItem[];
}

/**
 * GET /patients/{uuid}/screening-timeline
 * Returns the screening calendar for a patient across all their active conditions.
 * Empty items array = patient has no applicable screenings configured.
 */
export async function getScreeningTimeline(
  uuid: string,
): Promise<ScreeningTimelineResponse> {
  return apiFetch<ScreeningTimelineResponse>(
    `/patients/${uuid}/screening-timeline`,
  );
}
