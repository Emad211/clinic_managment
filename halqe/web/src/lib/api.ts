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
  source: string | null;
  notes: string | null;
  /** Server-evaluated status from clinical_indicators thresholds. null = no threshold defined. */
  level?: "ok" | "warn" | "danger" | null;
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

export interface SuggestionsResponseDTO {
  patient_link_id: number;
  count: number;
  has_redflag: boolean;
  framing: string;
  sections: SuggestionSectionDTO[];
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

export { ApiError };
