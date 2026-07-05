/**
 * Allergies domain — mirrors clinical/api/allergies.py.
 *
 * Endpoints (all JWT, tenant-scoped server-side):
 *   GET    /patients/{uuid}/allergies            → AllergyDTO[]
 *   POST   /patients/{uuid}/allergies            → 201 AllergyDTO
 *   DELETE /patients/{uuid}/allergies/{id}       → { deleted, id }
 *
 * Safety note: allergies are surfaced as a prominent banner ABOVE the tabs so a
 * physician never has to open a tab to see them. The list + add/delete form live
 * inside the record tab. This client only shapes the request/response — no logic.
 */
import { apiFetch } from "./_core";

/** Severity ladder (matches the backend validator). null = unspecified. */
export type AllergySeverity =
  | "mild"
  | "moderate"
  | "severe"
  | "anaphylaxis"
  | null;

export interface AllergyDTO {
  id: number;
  substance: string;
  severity: AllergySeverity;
  note: string | null;
  /** Superset field (slice2 column) — the UI may ignore it. */
  reaction: string | null;
  created_at: string; // ISO datetime
}

export interface AllergyIn {
  substance: string;
  severity?: AllergySeverity;
  note?: string | null;
}

export interface AllergyDeleteOut {
  deleted: boolean;
  id: number;
}

/** GET /patients/{uuid}/allergies — newest first. */
export async function listAllergies(uuid: string): Promise<AllergyDTO[]> {
  return apiFetch<AllergyDTO[]>(`/patients/${uuid}/allergies`);
}

/**
 * POST /patients/{uuid}/allergies — add one allergy → 201 with the created row.
 * Throws ApiError 422 (code "validation_error") on empty substance / bad severity.
 */
export async function addAllergy(
  uuid: string,
  payload: AllergyIn,
): Promise<AllergyDTO> {
  return apiFetch<AllergyDTO>(`/patients/${uuid}/allergies`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * DELETE /patients/{uuid}/allergies/{id}.
 * Throws ApiError 404 (code "not_found") if the row is not this patient's.
 */
export async function deleteAllergy(
  uuid: string,
  allergyId: number,
): Promise<AllergyDeleteOut> {
  return apiFetch<AllergyDeleteOut>(`/patients/${uuid}/allergies/${allergyId}`, {
    method: "DELETE",
  });
}
