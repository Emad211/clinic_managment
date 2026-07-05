/**
 * Clinical record domain — mirrors ClinicalRecordDTO + vital-review endpoints.
 */
import { apiFetch } from "./_core";

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
  /**
   * Derived age in whole years (safety-cockpit enrichment, فاز ۱).
   * Additive: null when birthdate is absent, or when the backend predates the
   * enrichment (graceful fallback). Never render a bare `null`.
   */
  age?: number | null;
}

// ────────────────────────────────────────────────────────────
// Safety-cockpit summary DTOs (فاز ۱ — additive enrichment of /record)
//
// These mirror the nested Schemas in clinical/api/patients.py exactly. They are
// OPTIONAL on ClinicalRecordDTO so the page degrades gracefully against a
// backend that predates the enrichment (the cockpit strips silently omit).
// ────────────────────────────────────────────────────────────

/** Control state token — worst of the latest verified vitals. */
export type ControlStatus =
  | "controlled"
  | "borderline"
  | "uncontrolled"
  | "no_data";

/** Overall (or per-disease) control state + Persian display label. */
export interface ControlDTO {
  status: ControlStatus;
  label: string;
}

/** Weighted headline risk tier. 'ok' surfaces as 'stable' at the boundary. */
export type RiskLevel = "high" | "medium" | "low" | "stable";

/** Weighted headline risk (suggestion-only derivation). */
export interface RiskDTO {
  level: RiskLevel;
  /** Dominant category (Persian) driving the score, or null. */
  dominant: string | null;
  /** Weighted risk points (for transparency, not a primary display). */
  score: number;
}

/** Direction of a between-reading change. */
export type DeltaDir = "up" | "down" | "flat";

/** Direction-aware change between the two latest verified readings. */
export interface IndicatorDeltaDTO {
  /** Signed delta (latest − previous). */
  value: number;
  dir: DeltaDir;
  /** True when moving away from danger (direction-aware). */
  improving: boolean;
}

/** One risk-weighted indicator tile within a per-disease block. */
export interface PerDiseaseIndicatorDTO {
  key: string;
  label: string;
  value: number | null;
  unit: string | null;
  /** Target as a display string (e.g. "<7"), or null. */
  target: number | string | null;
  /** Worse-when direction: 'high' | 'low' | null. */
  direction: "high" | "low" | null;
  delta: IndicatorDeltaDTO | null;
  level: "ok" | "warn" | "danger" | null;
}

/** Per active chronic condition: control + risk tier + top indicators. */
export interface PerDiseaseDTO {
  condition_code: string;
  condition_name: string;
  control: ControlDTO;
  risk_level: RiskLevel;
  indicators: PerDiseaseIndicatorDTO[];
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
  // ── safety-cockpit summary (فاز ۱ — additive; OPTIONAL for graceful fallback) ──
  control?: ControlDTO;
  risk?: RiskDTO;
  open_followups_count?: number;
  refill_due_count?: number;
  per_disease?: PerDiseaseDTO[];
}

export async function apiGetRecord(uuid: string): Promise<ClinicalRecordDTO> {
  return apiFetch<ClinicalRecordDTO>(`/patients/${uuid}/record`);
}
