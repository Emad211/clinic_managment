/**
 * API client for the Halqe platform backend.
 *
 * Reads NEXT_PUBLIC_API_BASE (default: http://127.0.0.1:8099/api/v1).
 * Attaches Bearer JWT from localStorage when present.
 * All request/response shapes mirror the django-ninja schemas in config/api.py.
 */

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8099/api/v1";

// ────────────────────────────────────────────────────────────
// Token storage  (localStorage — simplest for this slice)
// ────────────────────────────────────────────────────────────

const TOKEN_KEY = "halqe_token";

export function saveToken(token: string): void {
  if (typeof window !== "undefined") {
    localStorage.setItem(TOKEN_KEY, token);
  }
}

/**
 * Decode a JWT payload (base64url) without any library.
 * Returns the parsed claims object, or null on any decode error.
 * Does NOT verify the signature — used only for the `exp` claim check.
 */
function _decodeJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return null;
    // base64url → base64: replace -/_ and pad
    const b64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const pad = b64.length % 4 === 0 ? "" : "=".repeat(4 - (b64.length % 4));
    const json = atob(b64 + pad);
    return JSON.parse(json) as Record<string, unknown>;
  } catch {
    return null;
  }
}

/**
 * Return the stored JWT only if it is present AND not expired.
 * A token is considered expired when its `exp` claim (Unix seconds) is in
 * the past. Tokens without an `exp` claim are treated as non-expiring.
 * Returns null (and clears storage) when the token is missing or expired.
 */
export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  const token = localStorage.getItem(TOKEN_KEY);
  if (!token) return null;

  const claims = _decodeJwtPayload(token);
  if (claims !== null && typeof claims.exp === "number") {
    const nowSeconds = Math.floor(Date.now() / 1000);
    if (claims.exp <= nowSeconds) {
      // Expired — evict silently so the next getToken call starts clean
      localStorage.removeItem(TOKEN_KEY);
      return null;
    }
  }

  return token;
}

export function clearToken(): void {
  if (typeof window !== "undefined") {
    localStorage.removeItem(TOKEN_KEY);
  }
}

/**
 * Read the `role` claim ("manager" | "staff") from the stored JWT.
 *
 * Decodes the (un-verified) payload only — the backend remains the source of
 * truth and re-checks role on every privileged endpoint (manager-only routes
 * return 403). This client read is purely for UI gating / link visibility, so a
 * tampered token gains nothing: the server still rejects the request.
 *
 * Returns null when there is no valid token or the claim is missing.
 */
export function getRole(): string | null {
  const token = getToken();
  if (!token) return null;
  const claims = _decodeJwtPayload(token);
  if (claims !== null && typeof claims.role === "string") {
    return claims.role;
  }
  return null;
}

// ────────────────────────────────────────────────────────────
// Core fetch wrapper
// ────────────────────────────────────────────────────────────

class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    /** Stable machine-readable error code from backend (e.g. 'not_found', 'encounter_sealed'). */
    public readonly code: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/**
 * Map a backend error code to a human-readable Persian message.
 * Falls back to `fallback` (typically `err.message`) when code is unknown.
 *
 * Codes come from `config/errors.py` (halqe backend) — only stable codes that
 * are declared in that file and actively returned by endpoints are listed here.
 * Add new entries as new codes are introduced in the backend.
 */
export function errorMessageFromCode(
  code: string | null | undefined,
  fallback: string,
): string {
  switch (code) {
    // Auth
    case "invalid_credentials":
      return "نام کاربری یا رمز عبور اشتباه است.";
    case "account_locked":
      return "حساب کاربری قفل شده است. لطفاً ۱۵ دقیقه بعد تلاش کنید.";
    // Resource not found
    case "not_found":
      return "مورد درخواستی پیدا نشد.";
    // State transition conflicts
    case "conflict":
      return "این عملیات در وضعیت فعلی مجاز نیست.";
    case "encounter_sealed":
      return "ویزیت بسته شده و امکان ثبت اطلاعات جدید وجود ندارد.";
    case "invalid_transition":
      return "تغییر وضعیت مجاز نیست.";
    // Duplicate data
    case "duplicate_vital":
      return "این علامت حیاتی قبلاً برای این ویزیت ثبت شده است.";
    // Validation
    case "validation_error":
      return "مقدار وارد شده معتبر نیست.";
    // Prescription
    case "insurance_prescription_not_supported":
      return "نسخهٔ بیمه‌ای در این نسخه پشتیبانی نمی‌شود.";
    default:
      return fallback;
  }
}

async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token = getToken();
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...(options.headers ?? {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (!res.ok) {
    let detail = res.statusText;
    let code: string | null = null;
    try {
      const body = await res.json();
      detail = body?.detail ?? detail;
      // Read the stable machine-readable code from the backend error contract
      code = typeof body?.code === "string" ? body.code : null;
    } catch {
      // ignore parse errors — use statusText fallback
    }
    throw new ApiError(res.status, detail, code);
  }

  return res.json() as Promise<T>;
}

// ────────────────────────────────────────────────────────────
// Auth
// ────────────────────────────────────────────────────────────

export interface LoginResponse {
  token: string;
}

export async function apiLogin(
  username: string,
  password: string,
): Promise<LoginResponse> {
  return apiFetch<LoginResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

// ────────────────────────────────────────────────────────────
// Patients list  — mirrors EnrolledPatientDTO + PatientListResponse
// ────────────────────────────────────────────────────────────

export interface EnrolledPatient {
  link_id: number;
  patient_id: number;
  is_active: boolean;
  enrolled_at: string;            // ISO datetime string
  full_name: string | null;
  national_id: string | null;
  phone_number: string | null;
  patient_uuid: string | null;
}

export interface PatientListResponse {
  items: EnrolledPatient[];
  total: number;
  limit: number;
  offset: number;
}

export async function apiGetPatients(
  limit = 20,
  offset = 0,
): Promise<PatientListResponse> {
  return apiFetch<PatientListResponse>(
    `/patients?limit=${limit}&offset=${offset}`,
  );
}

// ────────────────────────────────────────────────────────────
// Clinical record  — mirrors ClinicalRecordDTO
// ────────────────────────────────────────────────────────────

export interface PatientDemographics {
  id: number;
  uuid: string;
  name: string;
  family_name: string;
  full_name: string;
  national_id: string | null;
  phone_number: string | null;
  birthdate: string | null;   // ISO date YYYY-MM-DD
  gender: string | null;
}

export interface ConditionDTO {
  id: number;
  condition_id: number;
  condition_name: string | null;
  condition_code: string | null;
  stage: string | null;
  onset_date: string | null;  // ISO date
  notes: string | null;
  is_active: boolean;
  diagnosed_at: string;       // ISO datetime
}

export interface MedicationDTO {
  id: number;
  drug_name: string;
  dose: string | null;
  schedule: string | null;
  start_date: string | null;
  refill_due_date: string | null;
  drug_class: string | null;
  is_active: boolean;
  notes: string | null;
  created_at: string;
}

export interface VitalReadingDTO {
  id: number;
  patient_link_id: number;
  type: string;
  value: number;
  unit: string | null;
  measured_at: string;        // ISO datetime
  /** Origin of the reading. 'patient_self' = patient self-report; 'clinic' / null = clinic-entered. */
  source: string | null;
  notes: string | null;
  /** Server-evaluated status from clinical_indicators thresholds. null = no threshold defined. */
  level?: "ok" | "warn" | "danger" | null;
  /**
   * Physician-review state (slice14 / step 47). Backend always serialises these.
   * Three derived states (see backend VitalReadingDTO contract):
   *   pending  : verified === false && rejected_at === null  — awaiting review
   *   approved : verified === true                            — accepted into the engine
   *   rejected : verified === false && rejected_at !== null   — soft-kept, out of the engine
   * Backend defaults `verified` to true for legacy/clinic rows that predate review.
   */
  verified: boolean;
  /** ISO 8601 timestamp string when the reading was rejected, or null. */
  rejected_at: string | null;
}

/**
 * Review state of a vital reading on the public record DTO, derived from
 * `verified` + `rejected_at`. Single source of truth so UI + tests agree.
 */
export type VitalReviewState = "pending" | "approved" | "rejected";

export function vitalReviewState(v: {
  verified: boolean;
  rejected_at: string | null;
}): VitalReviewState {
  if (v.verified) return "approved";
  if (v.rejected_at !== null) return "rejected";
  return "pending";
}

/**
 * Full vital row returned by the verify/reject endpoints — mirrors
 * `VitalReviewOut` (config/api.py). Not all fields are used in the UI;
 * the page refetches the record after a successful action.
 */
export interface VitalReviewOutDTO {
  id: number;
  patient_link_id: number;
  type: string;
  value: number;
  unit: string | null;
  measured_at: string;
  source: string | null;
  verified: boolean;
  verified_by: string | null;
  verified_at: string | null;
  rejected_by: string | null;
  rejected_at: string | null;
}

/**
 * POST /patients/{uuid}/vitals/{vitalId}/verify  (staff JWT)
 * Transitions a self-reported reading pending → approved (verified=true),
 * making it visible to the clinical engine.
 * Throws ApiError 409 (code "conflict") if the reading is already verified.
 */
export async function verifyVital(
  uuid: string,
  vitalId: number,
): Promise<VitalReviewOutDTO> {
  return apiFetch<VitalReviewOutDTO>(
    `/patients/${uuid}/vitals/${vitalId}/verify`,
    { method: "POST" },
  );
}

/**
 * POST /patients/{uuid}/vitals/{vitalId}/reject  (staff JWT)
 * Soft-rejects a self-reported reading pending → rejected (sets rejected_at;
 * verified stays false so it remains out of the engine, kept for audit).
 * Throws ApiError 409 (code "conflict") if already rejected or already verified.
 */
export async function rejectVital(
  uuid: string,
  vitalId: number,
): Promise<VitalReviewOutDTO> {
  return apiFetch<VitalReviewOutDTO>(
    `/patients/${uuid}/vitals/${vitalId}/reject`,
    { method: "POST" },
  );
}

export interface ClinicalRecordDTO {
  patient_link_id: number;
  demographics: PatientDemographics | null;
  active_conditions: ConditionDTO[];
  active_medications: MedicationDTO[];
  recent_vitals: VitalReadingDTO[];
}

export async function apiGetRecord(uuid: string): Promise<ClinicalRecordDTO> {
  return apiFetch<ClinicalRecordDTO>(`/patients/${uuid}/record`);
}

// ────────────────────────────────────────────────────────────
// Suggestions  — mirrors SuggestionsResponseDTO
// ────────────────────────────────────────────────────────────

export interface SuggestionRuleDTO {
  rule_code: string;
  title: string;
  category: string;
  condition_code: string;
  recommendation: string | null;
  dosage_titration: string | null;
  monitoring: string | null;
  contraindications: string | null;
  evidence_level: string | null;
  action_type: string;
  severity: "info" | "warn" | "urgent";
  priority: number;
  source_ref: string | null;
  section: string;
  suggestion_only: boolean;
  /**
   * Prior physician action for this rule on this patient.
   * Populated by GET /patients/{uuid}/suggestions.
   * Any value other than 'accepted' or 'dismissed' is treated as null (no prior action).
   */
  prior_action: "accepted" | "dismissed" | null;
}

export interface SuggestionSectionDTO {
  key: string;
  label: string;
  rules: SuggestionRuleDTO[];
}

/**
 * A single missing clinical datum that prevented some rules from being evaluated.
 * Returned by GET /patients/{uuid}/suggestions when the engine detected gaps.
 */
export interface DataGapDTO {
  /** Machine-readable datum key, e.g. "age", "egfr", "hba1c". */
  datum: string;
  /** Human-readable Persian label shown in the transparency banner. */
  label: string;
  /** Number of clinical rules that could not be evaluated due to this missing datum. */
  affected_rules: number;
}

/**
 * One drug-drug interaction (DDI) flagged by the clinical engine.
 * Returned in `ddi[]` on GET /patients/{uuid}/suggestions.
 *
 * Severity levels (clinical pharmacist contract):
 *   - contraindicated : absolute two-blocker risk (e.g. dual RAAS) — role="alert"
 *   - major           : serious interaction requiring physician review — role="note"
 *   - moderate        : monitor + consider alternatives — role="note"
 *
 * `suggestion_only` is always true — no automatic action is taken.
 */
export interface DdiDTO {
  /** Pharmacologic class of the first drug (e.g. "acei"). */
  class_a: string;
  /** Pharmacologic class of the second drug (e.g. "arb"). */
  class_b: string;
  severity: "contraindicated" | "major" | "moderate";
  /** Human-readable Persian explanation of the interaction. */
  message_fa: string;
  /** Evidence citation, e.g. "ONTARGET 2008؛ ADA 2025 §CKD". Optional. */
  evidence?: string;
  /** Always true — the system suggests, the physician decides. */
  suggestion_only?: boolean;
}

export interface SuggestionsResponseDTO {
  patient_link_id: number;
  count: number;
  has_redflag: boolean;
  framing: string;
  sections: SuggestionSectionDTO[];
  /**
   * Missing data items that prevented some rules from being evaluated.
   * Empty array (or absent) when the engine had everything it needed.
   * Displayed as a non-alarming informational transparency banner.
   */
  data_gaps?: DataGapDTO[];
  /**
   * Drug-drug interactions detected for this patient's active medications.
   * Empty array (or absent) = no interactions found.
   * Rendered above the regular suggestion list, sorted by severity descending.
   */
  ddi?: DdiDTO[];
}

export async function apiGetSuggestions(
  uuid: string,
): Promise<SuggestionsResponseDTO> {
  return apiFetch<SuggestionsResponseDTO>(`/patients/${uuid}/suggestions`);
}

// ────────────────────────────────────────────────────────────
// Suggestion action  — mirrors SuggestionLogDTO
// ────────────────────────────────────────────────────────────

export interface SuggestionLogDTO {
  id: number;
  patient_link_id: number;
  tenant_id: number;
  rule_code: string;
  status: string;
  acted_by: string | null;
  acted_at: string | null;
  note: string | null;
  created_at: string;
}

export async function apiSuggestionAction(
  uuid: string,
  ruleCode: string,
  action: "accept" | "dismiss",
  note?: string,
): Promise<SuggestionLogDTO> {
  return apiFetch<SuggestionLogDTO>(
    `/patients/${uuid}/suggestions/${encodeURIComponent(ruleCode)}/action`,
    {
      method: "POST",
      body: JSON.stringify({ action, note: note ?? null }),
    },
  );
}

// ────────────────────────────────────────────────────────────
// Worklist  — mirrors WorklistItemDTO + WorklistResponseDTO
// ────────────────────────────────────────────────────────────

export interface WorklistItem {
  id: number;
  patient_uuid: string | null;
  patient_full_name: string | null;
  kind: string | null;       // same value as reason — the "kind" of follow-up
  reason: string | null;
  due_date: string | null;   // ISO date YYYY-MM-DD (can be null)
  status: string;            // 'open' | 'done' | 'dismissed'
  fulfillment: string | null;
  created_at: string;        // ISO datetime
  resolved_at: string | null;
  /**
   * Cumulative closed-invoice revenue for this patient (Toman).
   * Only populated when the authed user is a MANAGER and include_revenue=true
   * was sent. Backend enforces the manager gate — non-managers always get null.
   */
  revenue?: number | null;
}

export interface WorklistResponse {
  items: WorklistItem[];
  total: number;
  limit: number;
  offset: number;
}

export async function apiGetWorklist({
  status,
  limit = 20,
  offset = 0,
  includeRevenue = true,
}: {
  status?: string;
  limit?: number;
  offset?: number;
  /**
   * When true, passes include_revenue=true to the backend.
   * The backend only populates `revenue` for MANAGER users — non-managers
   * receive null regardless. Defaults to true so the UI auto-shows the column
   * for managers without any client-side role check.
   */
  includeRevenue?: boolean;
} = {}): Promise<WorklistResponse> {
  const params = new URLSearchParams();
  if (status !== undefined) params.set("status", status);
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  if (includeRevenue) params.set("include_revenue", "true");
  return apiFetch<WorklistResponse>(`/worklist?${params.toString()}`);
}

// ────────────────────────────────────────────────────────────
// Mark worklist task done  — mirrors FollowupTaskDTO
// ────────────────────────────────────────────────────────────

export interface FollowupTaskDTO {
  id: number;
  patient_link_id: number;
  tenant_id: number;
  reason: string | null;
  detail: string | null;
  due_date: string | null;
  status: string;
  fulfillment: string | null;
  source_rule: string | null;
  source_event: string | null;
  created_at: string;
  resolved_at: string | null;
}

export async function apiMarkDone(taskId: number): Promise<FollowupTaskDTO> {
  return apiFetch<FollowupTaskDTO>(`/worklist/${taskId}/done`, {
    method: "POST",
  });
}

// ────────────────────────────────────────────────────────────
// Encounters — mirrors EncounterOut + CreateEncounterIn + VitalIn + LabIn
// ────────────────────────────────────────────────────────────

export type EncounterType = "visit" | "follow_up" | "phone" | "remote";
export type EncounterStatus = "open" | "completed" | "cancelled";

export interface EncounterOut {
  id: number;
  tenant_id: number;
  patient_link_id: number;
  encounter_type: EncounterType;
  encounter_at: string;          // ISO datetime (Tehran local)
  status: EncounterStatus;
  chief_complaint: string | null;
  doctor_id: number | null;
  appointment_id: number | null;
  accounting_invoice_id: number | null;
  completed_at: string | null;
  summary_note: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateEncounterIn {
  encounter_type?: EncounterType;
  encounter_at?: string;
  chief_complaint?: string | null;
  doctor_id?: number | null;
  appointment_id?: number | null;
}

export interface VitalIn {
  type: string;
  value: number;
  unit?: string | null;
  source?: string;               // default "clinic"
  measured_at?: string | null;
}

export interface VitalReadingCreatedDTO {
  id: number;
  patient_link_id: number;
  encounter_id: number;
  type: string;
  value: number;
  unit: string | null;
  source: string | null;
  measured_at: string;
}

export interface AddVitalsResponse {
  count: number;
  vitals: VitalReadingCreatedDTO[];
}

export interface LabIn {
  test_name: string;
  test_key?: string | null;      // keep null — no catalog row yet
  value?: number | null;
  unit?: string | null;
  ref_low?: number | null;
  ref_high?: number | null;
  taken_at?: string | null;
}

export interface AddLabsResponse {
  count: number;
  labs: unknown[];               // typed loosely — not used in UI yet
}

export interface EncounterListResponse {
  items: EncounterOut[];
  total: number;
  limit: number;
  offset: number;
}

/** POST /patients/{uuid}/encounters → 201 EncounterOut */
export async function apiCreateEncounter(
  uuid: string,
  body: CreateEncounterIn,
): Promise<EncounterOut> {
  return apiFetch<EncounterOut>(`/patients/${uuid}/encounters`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** POST /encounters/{encounterId}/vitals → 200 AddVitalsResponse */
export async function apiAddVitals(
  encounterId: number,
  vitals: VitalIn[],
): Promise<AddVitalsResponse> {
  return apiFetch<AddVitalsResponse>(`/encounters/${encounterId}/vitals`, {
    method: "POST",
    body: JSON.stringify(vitals),
  });
}

/** POST /encounters/{encounterId}/labs → 200 AddLabsResponse */
export async function apiAddLabs(
  encounterId: number,
  labs: LabIn[],
): Promise<AddLabsResponse> {
  return apiFetch<AddLabsResponse>(`/encounters/${encounterId}/labs`, {
    method: "POST",
    body: JSON.stringify(labs),
  });
}

/** POST /encounters/{encounterId}/complete → 200 EncounterOut */
export async function apiCompleteEncounter(
  encounterId: number,
  summaryNote?: string,
): Promise<EncounterOut> {
  return apiFetch<EncounterOut>(`/encounters/${encounterId}/complete`, {
    method: "POST",
    body: JSON.stringify({ summary_note: summaryNote ?? null }),
  });
}

/** POST /encounters/{encounterId}/cancel → 200 EncounterOut */
export async function apiCancelEncounter(
  encounterId: number,
  reason?: string,
): Promise<EncounterOut> {
  return apiFetch<EncounterOut>(`/encounters/${encounterId}/cancel`, {
    method: "POST",
    body: JSON.stringify({ reason: reason ?? null }),
  });
}

/** GET /patients/{uuid}/encounters → EncounterListResponse (newest first) */
export async function apiListEncounters(
  uuid: string,
  limit = 10,
  offset = 0,
): Promise<EncounterListResponse> {
  return apiFetch<EncounterListResponse>(
    `/patients/${uuid}/encounters?limit=${limit}&offset=${offset}`,
  );
}

// ────────────────────────────────────────────────────────────
// Doctor Queue  — mirrors DoctorQueueEntry + DoctorQueueResponse + DoctorVisitLog
// ────────────────────────────────────────────────────────────

export interface DoctorQueueEntry {
  invoice_id: number;
  patient_id: number;
  patient_uuid?: string | null;
  full_name: string;
  phone_number?: string | null;
  opened_at?: string | null;
  work_date?: string | null;
  status: string;            // "waiting" | "in_progress" | "done"
  patient_link_id?: number | null;
  enrolled: boolean;
  done_by?: string | null;
  started_at?: string | null;
  done_at?: string | null;
}

export interface DoctorQueueResponse {
  waiting: DoctorQueueEntry[];  // includes waiting + in_progress
  done: DoctorQueueEntry[];
  work_date: string;
}

export interface DoctorVisitLog {
  id: number;
  tenant_id: number;
  accounting_invoice_id: number;
  patient_link_id?: number | null;
  patient_uuid?: string | null;
  full_name: string;
  work_date: string;
  status: string;
  started_at?: string | null;
  done_at?: string | null;
  physician_notes?: string | null;
  done_by?: string | null;
  created_at?: string | null;
}

/**
 * GET /doctor-queue?work_date=YYYY-MM-DD
 * work_date is optional — backend defaults to today (Tehran local).
 */
export async function apiGetDoctorQueue(
  workDate?: string,
): Promise<DoctorQueueResponse> {
  const path = workDate
    ? `/doctor-queue?work_date=${encodeURIComponent(workDate)}`
    : "/doctor-queue";
  return apiFetch<DoctorQueueResponse>(path);
}

/**
 * POST /doctor-queue/{invoiceId}/start
 * Transitions the entry from waiting → in_progress.
 */
export async function apiStartVisit(
  invoiceId: number,
): Promise<DoctorVisitLog> {
  return apiFetch<DoctorVisitLog>(`/doctor-queue/${invoiceId}/start`, {
    method: "POST",
  });
}

/**
 * POST /doctor-queue/{invoiceId}/done
 * Transitions the entry from in_progress → done.
 * Optional physician notes are sent in the request body.
 */
export async function apiMarkVisitDone(
  invoiceId: number,
  notes?: string,
): Promise<DoctorVisitLog> {
  return apiFetch<DoctorVisitLog>(`/doctor-queue/${invoiceId}/done`, {
    method: "POST",
    body: JSON.stringify({ notes: notes ?? null }),
  });
}

// ────────────────────────────────────────────────────────────
// Prescriptions — mirrors PrescriptionItemIn / CreatePrescriptionIn /
// PrescriptionItemOut / PrescriptionOut (config/api.py Step 11)
// ────────────────────────────────────────────────────────────

/**
 * Canonical frequency values — MUST match PrescriptionItem.ALLOWED_FREQUENCIES
 * in clinical/models.py exactly (frozenset built from FREQUENCY_CHOICES).
 */
export const ALLOWED_FREQUENCIES = [
  "od",
  "bid",
  "tid",
  "qid",
  "qod",
  "weekly",
  "monthly",
  "prn",
  "with_meal",
  "bedtime",
  "other",
] as const;

export type PrescriptionFrequency = (typeof ALLOWED_FREQUENCIES)[number];

/** Persian labels for each canonical frequency value (clinical pharmacist). */
export const FREQUENCY_LABEL: Record<PrescriptionFrequency, string> = {
  od: "یک‌بار روزانه",
  bid: "دوبار روزانه",
  tid: "سه‌بار روزانه",
  qid: "چهاربار روزانه",
  qod: "یک‌درمیان",
  weekly: "هفتگی",
  monthly: "ماهانه",
  prn: "در صورت نیاز",
  with_meal: "با غذا",
  bedtime: "قبل از خواب",
  other: "سایر",
};

/**
 * Canonical route values — MUST match PrescriptionItem.ALLOWED_ROUTES
 * in clinical/models.py exactly (frozenset built from ROUTE_CHOICES).
 */
export const ALLOWED_ROUTES = [
  "oral",
  "sublingual",
  "sc",
  "im",
  "iv",
  "topical",
  "inhaled",
  "other",
] as const;

export type PrescriptionRoute = (typeof ALLOWED_ROUTES)[number];

/** Persian labels for each canonical route value (clinical pharmacist). */
export const ROUTE_LABEL: Record<PrescriptionRoute, string> = {
  oral: "خوراکی",
  sublingual: "زیرزبانی",
  sc: "زیرپوستی",
  im: "عضلانی",
  iv: "وریدی",
  topical: "موضعی",
  inhaled: "تنفسی",
  other: "سایر",
};

/** One line-item of a prescription being sent to the server. */
export interface PrescriptionItemIn {
  drug_name: string;                        // required — free text
  drug_class?: string | null;               // optional — soft ref to drug_classes
  dose_value?: number | null;               // NUMERIC(10,3) — float in API
  dose_unit?: string | null;                // e.g. "mg", "mcg", "unit"
  frequency?: PrescriptionFrequency | null; // canonical set only (validated server-side)
  route?: PrescriptionRoute | null;         // canonical set only (validated server-side)
  quantity?: number | null;                 // integer > 0
  duration_days?: number | null;            // integer > 0
  instructions?: string | null;
}

/** Body for POST /encounters/{encounter_id}/prescriptions. */
export interface CreatePrescriptionIn {
  kind: string;                   // required; no vocabulary in DB — "outpatient" default
  items: PrescriptionItemIn[];
  mode: "free";                   // always "free"; "insurance" → 422
}

/** One created prescription item returned from the server. */
export interface PrescriptionItemOut {
  id: number;
  tenant_id: number;
  prescription_id: number;
  drug_name: string;
  drug_class: string | null;
  dose_value: number | null;
  dose_unit: string | null;
  frequency: string | null;
  route: string | null;
  quantity: number | null;
  duration_days: number | null;
  instructions: string | null;
}

/** Created prescription header + structured items returned from the server. */
export interface PrescriptionOut {
  id: number;
  tenant_id: number;
  patient_link_id: number;
  encounter_id: number | null;
  kind: string;
  mode: string;
  prescriber_user_id: number | null;
  followup_task_id: number | null;
  issued_at: string;              // ISO datetime (Tehran local)
  items_structured: PrescriptionItemOut[];
}

/**
 * POST /encounters/{encounterId}/prescriptions
 * Creates a free-mode prescription (header + structured items) on an open encounter.
 * mode is always "free" — "insurance" returns 422 (insurance_prescription_not_supported).
 */
export async function apiAddPrescription(
  encounterId: number,
  body: CreatePrescriptionIn,
): Promise<PrescriptionOut> {
  return apiFetch<PrescriptionOut>(`/encounters/${encounterId}/prescriptions`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// ────────────────────────────────────────────────────────────
// Screening Timeline  — mirrors ScreeningTimelineResponse
// ────────────────────────────────────────────────────────────

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

// ────────────────────────────────────────────────────────────
// Patient Card (public — no JWT)  — mirrors CardResponse
// GET /api/v1/card/{token}  (unauthenticated)
// ────────────────────────────────────────────────────────────

/**
 * One vital shown on the public patient card.
 * status ∈ 'ok' | 'warn' | 'danger'.
 * value is a number (not a string).
 */
export interface CardVital {
  key: string;
  label: string;
  value: number;
  unit: string;
  status: "ok" | "warn" | "danger";
}

/**
 * Response from GET /api/v1/card/{token}.
 * Contains no national_id, phone, medications, or diagnoses —
 * the backend guarantees that only these fields are returned.
 */
export interface CardResponse {
  first_name: string | null;
  clinic_name: string | null;
  vitals: CardVital[];
  /** ISO date YYYY-MM-DD, or null when no appointment is scheduled. */
  next_appointment: string | null;
  /** Safety framing text, e.g. "پیشنهاد — تأیید با پزشک". */
  framing: string | null;
  /**
   * Pre-rendered, patient-safe screening reminder line (step 48, cluster J).
   *
   * The backend guarantees this string contains NO patient name, diagnosis,
   * medication, or exact clinical number — it is a single neutral
   * informational sentence (e.g. "چند موردِ مراقبتِ دوره‌ای… با کلینیک تماس بگیرید").
   *
   * - null  → no reminder is due → render NOTHING (no empty section).
   * - non-null → render exactly this string, verbatim, in a soft neutral
   *   (informational) banner. The UI must never add/infer extra detail and
   *   must never show it with danger styling / at the level of a danger vital.
   *
   * Marked optional (`?`) so the UI is forward/backward compatible: the live
   * backend `PublicCardResponse` may not yet serialise this field — absence is
   * treated identically to null.
   */
  reminder_message?: string | null;
}

/**
 * Fetch the public patient card by token.
 *
 * This is a PUBLIC endpoint — no Authorization header is attached.
 * An invalid/expired/revoked token returns ApiError with status 404.
 */
export async function getCard(token: string): Promise<CardResponse> {
  const res = await fetch(`${API_BASE}/card/${encodeURIComponent(token)}`, {
    method: "GET",
    headers: { "Content-Type": "application/json" },
    // No Authorization header — deliberately public
  });

  if (!res.ok) {
    let detail = res.statusText;
    let code: string | null = null;
    try {
      const body = await res.json();
      detail = body?.detail ?? detail;
      code = typeof body?.code === "string" ? body.code : null;
    } catch {
      // ignore parse errors
    }
    throw new ApiError(res.status, detail, code);
  }

  return res.json() as Promise<CardResponse>;
}

// ────────────────────────────────────────────────────────────
// Patient Card Token (staff — JWT)  — mirrors CardTokenOut
// POST /api/v1/patients/{uuid}/card-token
// ────────────────────────────────────────────────────────────

/**
 * Response from POST /patients/{uuid}/card-token (mirrors CardTokenOut).
 *
 * `card_url` is a relative PATH only (e.g. "/card/<token>"), not an absolute
 * URL — the deployment is LAN-only for now. The UI builds the copy-able link
 * by prepending window.location.origin.
 */
export interface CardTokenOut {
  token: string;
  expires_at: string;     // ISO datetime
  card_url: string;       // relative path, e.g. "/card/<token>"
}

/**
 * POST /patients/{uuid}/card-token  (staff JWT) → 201 CardTokenOut
 * Issues a new public-card token for the patient. one-active-at-a-time:
 * the backend revokes any previous active token for this patient first.
 */
export async function issueCardToken(uuid: string): Promise<CardTokenOut> {
  return apiFetch<CardTokenOut>(`/patients/${uuid}/card-token`, {
    method: "POST",
  });
}

// ────────────────────────────────────────────────────────────
// Patient Self-Report (public — no JWT)
// POST /api/v1/patient-report/{token}
// ────────────────────────────────────────────────────────────

/**
 * One vital reading submitted by the patient themselves.
 * type ∈ 'fbs' | 'bp_systolic' | 'bp_diastolic' — no weight.
 */
export interface SelfReportReading {
  type: "fbs" | "bp_systolic" | "bp_diastolic";
  value: number;
}

/**
 * Accepted reading echoed back in the 200 response.
 */
export interface AcceptedReading {
  type: string;
  value: number;
}

/**
 * 200 response from POST /patient-report/{token}.
 */
export interface SelfReportResponse {
  status: "ok";
  accepted: AcceptedReading[];
  count: number;
  message: string;
}

/**
 * Submit a batch of self-reported vital readings for a patient.
 *
 * PUBLIC endpoint — no Authorization header attached (same pattern as getCard).
 * Token is one-time-use: consumed after a 200 response.
 *
 * Error codes:
 *   404 — token invalid/used/expired → do NOT retry
 *   422 — validation failure (out-of-range / empty batch) → token NOT consumed; fix and retry
 *   429 — rate limit → wait and retry
 */
export async function submitReport(
  token: string,
  readings: SelfReportReading[],
): Promise<SelfReportResponse> {
  const res = await fetch(
    `${API_BASE}/patient-report/${encodeURIComponent(token)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // No Authorization header — deliberately public
      body: JSON.stringify({ readings }),
    },
  );

  if (!res.ok) {
    let detail = res.statusText;
    let code: string | null = null;
    try {
      const body = await res.json();
      detail = body?.detail ?? detail;
      code = typeof body?.code === "string" ? body.code : null;
    } catch {
      // ignore parse errors
    }
    throw new ApiError(res.status, detail, code);
  }

  return res.json() as Promise<SelfReportResponse>;
}

// ────────────────────────────────────────────────────────────
// Manager Outcomes Dashboard (cluster K) — 5 read-only, manager-only endpoints.
//
// All rate/mean/delta fields are `number | null` — null = "insufficient data",
// NEVER 0. The UI must render the "دادهٔ ناکافی" copy for null, never zero.
//
// IMPORTANT honesty boundary: process metrics (acceptance, funnel, lapsed→return)
// and descriptive patient-state outcomes (cohort-outcome, control-trend) live in
// two SEPARATE response shapes here and MUST be rendered in two separate UI
// regions — never combined in one card/chart (would imply false causality).
// ────────────────────────────────────────────────────────────

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

export { ApiError };
