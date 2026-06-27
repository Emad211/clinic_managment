/**
 * Engagement domain — approval queue + event→channel config + guardrail
 * settings  (cluster L, step 52).
 *
 * Split out of the old monolithic api.ts in cleanup step 8's wake (step 52b):
 * the ~189 lines step 52 added to api.ts now live here as a per-domain module.
 * The shared `apiFetch` is imported from `./_core`, exactly like the sibling
 * modules (manager-analytics.ts, worklist.ts). The barrel `../api.ts`
 * re-exports everything below via `export * from "./api/engagement"`.
 *
 * SAFETY GATE: NO automated SMS leaves the system. Every send is a
 * manager decision in the approval queue, and even then the live
 * Kavenegar account is in KYC hold (code 430) → /send only SIMULATES
 * (NullProvider). The UI must never claim "ارسال شد" in this mode.
 *
 * Request/response shapes mirror the django-ninja schemas in
 * `clinical/api/engagement.py` (the step-52a backend, merged on main).
 */
import { apiFetch } from "./_core";

// ── 1) GET /engagement/approvals — pending review queue ──────

/** Status of one approval row. */
export type ApprovalStatus = "pending" | "approved" | "rejected" | "sent";

/**
 * One pending engagement approval — a message queued for a manager to
 * review BEFORE it can ever be sent. The card UI renders the verbatim
 * `message` so the reviewer sees exactly what would go out (anti
 * rubber-stamping).
 */
export interface EngagementApproval {
  id: number;
  patient_link_id: number;
  /** Machine-readable event key, e.g. "lab_due". Never shown raw to the user. */
  event_key: string;
  /** Human-readable Persian label for the event, e.g. "آزمایشِ دوره‌ای". */
  event_label: string;
  patient_name: string;
  /** The exact SMS text — rendered verbatim, dir="auto". */
  message: string;
  /** Delivery channel for this item, e.g. "sms". */
  channel: string;
  /** ISO date YYYY-MM-DD the action is due, or null. */
  due_date: string | null;
  status: ApprovalStatus;
  /** True when the patient has opted out of SMS — red badge, blocks send. */
  sms_opt_out: boolean;
  /** False when the patient has NOT consented to SMS — warning badge. */
  sms_consent: boolean;
  /** ISO datetime of the last outbound contact, or null (never contacted). */
  last_contact_at: string | null;
  decided_by: string | null;
  decided_at: string | null;
}

export interface ApprovalListResponse {
  items: EngagementApproval[];
  total: number;
}

/** GET /engagement/approvals — pending queue (any authed user can view). */
export async function getEngagementApprovals(): Promise<ApprovalListResponse> {
  return apiFetch<ApprovalListResponse>("/engagement/approvals");
}

// ── 2) POST /engagement/approvals/{id}/approve  (manager) ─────

/** POST /engagement/approvals/{id}/approve → pending → approved (manager). */
export async function approveEngagementApproval(
  id: number,
): Promise<EngagementApproval> {
  return apiFetch<EngagementApproval>(`/engagement/approvals/${id}/approve`, {
    method: "POST",
  });
}

// ── 3) POST /engagement/approvals/{id}/reject  (manager) ──────

/**
 * POST /engagement/approvals/{id}/reject → pending → rejected (manager).
 * Optional reason is recorded for the audit trail.
 */
export async function rejectEngagementApproval(
  id: number,
  reason?: string,
): Promise<EngagementApproval> {
  return apiFetch<EngagementApproval>(`/engagement/approvals/${id}/reject`, {
    method: "POST",
    body: JSON.stringify({ reason: reason ?? null }),
  });
}

// ── 4) POST /engagement/approvals/{id}/send  (manager) ────────

/**
 * Tri-state result of a send attempt.
 *   - ok=true             → recorded. In KYC/simulation mode this is a
 *     SIMULATED send (NullProvider) — UI shows «ثبت‌شده (شبیه‌سازی)», NEVER
 *     «ارسال شد».
 *   - ok=false + reason   → blocked by a guardrail. Known reasons:
 *       'opt_out'  — patient opted out
 *       'no_phone' — no phone on file
 *       'quiet'    — quiet-hours window
 *   - pending=true        → handed to the provider but not confirmed
 *     (e.g. timeout) → «در انتظارِ سامانه».
 *
 * The backend (SendApprovalOut) also returns approval_id/status/provider_msgid;
 * this client only consumes ok/reason/pending — the extra fields are ignored.
 */
export interface SendApprovalResult {
  ok: boolean;
  reason?: string | null;
  pending?: boolean;
}

/** POST /engagement/approvals/{id}/send → tri-state result (manager, approved only). */
export async function sendEngagementApproval(
  id: number,
): Promise<SendApprovalResult> {
  return apiFetch<SendApprovalResult>(`/engagement/approvals/${id}/send`, {
    method: "POST",
  });
}

// ── 5) GET /engagement/events — event→channel config table ────

/** Delivery channel for an automated event. */
export type EngagementChannel = "sms" | "worklist" | "both" | "off";

/** Persian labels for each channel (segmented control). */
export const ENGAGEMENT_CHANNEL_LABEL: Record<EngagementChannel, string> = {
  sms: "پیامک",
  worklist: "کارِ روزانه",
  both: "هردو",
  off: "خاموش",
};

/** One row of the event→channel routing config. */
export interface EngagementEvent {
  event_key: string;
  label: string;
  category: string;
  channel: EngagementChannel;
  cooldown_days: number;
}

/** GET /engagement/events — manager-only (staff → 403). */
export async function getEngagementEvents(): Promise<EngagementEvent[]> {
  return apiFetch<EngagementEvent[]>("/engagement/events");
}

// ── 6) PUT /engagement/events/{event_key} ─────────────────────

/** PUT /engagement/events/{event_key} → updates channel + cooldown (manager). */
export async function updateEngagementEvent(
  eventKey: string,
  body: { channel: EngagementChannel; cooldown_days: number },
): Promise<EngagementEvent> {
  return apiFetch<EngagementEvent>(
    `/engagement/events/${encodeURIComponent(eventKey)}`,
    {
      method: "PUT",
      body: JSON.stringify(body),
    },
  );
}

// ── 7) GET /engagement/settings — guardrails ──────────────────

/** Global engagement guardrails (quiet hours + daily cap). */
export interface EngagementSettings {
  /** "HH:MM" Tehran-local start of the allowed sending window. */
  quiet_start: string;
  /** "HH:MM" Tehran-local end of the allowed sending window. */
  quiet_end: string;
  /** Maximum SMS per patient per day. */
  daily_cap: number;
}

/** GET /engagement/settings — manager-only (staff → 403). */
export async function getEngagementSettings(): Promise<EngagementSettings> {
  return apiFetch<EngagementSettings>("/engagement/settings");
}

// ── 8) PUT /engagement/settings ───────────────────────────────

/** PUT /engagement/settings → updates quiet hours + daily cap (manager). */
export async function updateEngagementSettings(
  body: EngagementSettings,
): Promise<EngagementSettings> {
  return apiFetch<EngagementSettings>("/engagement/settings", {
    method: "PUT",
    body: JSON.stringify(body),
  });
}
