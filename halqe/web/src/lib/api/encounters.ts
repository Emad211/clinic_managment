/**
 * Encounters domain — mirrors EncounterOut + CreateEncounterIn + VitalIn + LabIn.
 */
import { apiFetch } from "./_core";

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
