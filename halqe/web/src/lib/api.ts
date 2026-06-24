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

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
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
  ) {
    super(message);
    this.name = "ApiError";
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
    try {
      const body = await res.json();
      detail = body?.detail ?? detail;
    } catch {
      // ignore parse errors
    }
    throw new ApiError(res.status, detail);
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

export { ApiError };
