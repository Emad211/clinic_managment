/**
 * Prescriptions domain — mirrors PrescriptionItemIn / CreatePrescriptionIn /
 * PrescriptionItemOut / PrescriptionOut (config/api.py Step 11).
 */
import { apiFetch } from "./_core";

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
