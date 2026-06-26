/**
 * Patients list domain — mirrors EnrolledPatientDTO + PatientListResponse.
 */
import { apiFetch } from "./_core";

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
