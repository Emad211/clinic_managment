/** Complete vital-history projection for the specialist record editor. */
import { apiFetch } from "./_core";

export interface RecordVitalDTO {
  id: number;
  type: string;
  value: number;
  unit: string | null;
  measured_at: string;
  source: string | null;
  notes: string | null;
  recorded_by: string | null;
  verified: boolean;
  verified_by: string | null;
  verified_at: string | null;
  rejected_by: string | null;
  rejected_at: string | null;
  encounter_id: number | null;
}

export function apiGetRecordVitals(uuid: string): Promise<RecordVitalDTO[]> {
  return apiFetch(`/patients/${uuid}/record/vitals`);
}
