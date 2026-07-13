/** Complete specialist patient-record API client. */
import { apiFetch } from "./_core";

export interface RecordConditionCatalogDTO {
  id: number;
  name: string;
  code: string | null;
  description: string | null;
  icon: string | null;
  color: string | null;
  display_order: number;
}

export interface RecordConditionDTO {
  id: number;
  condition_id: number;
  condition_name: string | null;
  condition_code: string | null;
  stage: string | null;
  onset_date: string | null;
  notes: string | null;
  is_active: boolean;
  diagnosed_at: string;
}

export interface SurgeryHistoryDTO {
  id: number;
  title: string;
  performed_on: string | null;
  note: string | null;
  created_at: string;
}

export interface MedicalHistoryDTO {
  id: number;
  title: string;
  since: string | null;
  note: string | null;
  created_at: string;
}

export interface ClinicalNoteDTO {
  id: number;
  kind: "symptom" | "exam" | "lifestyle" | "general";
  body: string;
  recorded_at: string;
  recorded_by: string | null;
}

export interface FlagOptionDTO {
  value: string;
  label: string;
}

export interface RecordFlagCatalogDTO {
  flag_key: string;
  label: string;
  flag_type: "bool" | "enum" | "date" | "text";
  options: FlagOptionDTO[];
  category: string;
  category_label: string;
  record_section: "lifestyle" | "exam" | "disease" | "general";
  display_order: number;
}

export interface RecordLabCatalogDTO {
  id: number;
  test_key: string;
  name_fa: string;
  unit: string | null;
  ref_low: number | null;
  ref_high: number | null;
  category: string | null;
  display_order: number;
}

export interface RecordLabResultDTO {
  id: number;
  test_name: string;
  test_key: string | null;
  value: number | null;
  unit: string | null;
  ref_low: number | null;
  ref_high: number | null;
  taken_at: string;
  notes: string | null;
  recorded_by: string | null;
  encounter_id: number | null;
}

export interface RecordIndicatorCatalogDTO {
  key: string;
  label: string;
  unit: string | null;
  category: string;
  display_order: number;
}

export interface RecordDrugClassDTO {
  class_key: string;
  label: string;
  glucose_lowering: boolean;
  display_order: number;
}

export interface RecordDrugCatalogDTO {
  id: number;
  generic_fa: string;
  drug_class_key: string | null;
  doses: string[];
}

export interface RecordMedicationDTO {
  id: number;
  drug_name: string;
  dose: string | null;
  schedule: string | null;
  start_date: string | null;
  refill_due_date: string | null;
  end_date: string | null;
  drug_class: string | null;
  is_active: boolean;
  notes: string | null;
  created_at: string;
}

export interface RecordMedicationEventDTO {
  id: number;
  medication_id: number | null;
  drug_name: string;
  event_type: "start" | "stop" | "dose_change";
  dose: string | null;
  event_date: string | null;
  note: string | null;
  created_by: string | null;
  created_at: string;
}

export interface RecordAppointmentDTO {
  id: number;
  scheduled_at: string;
  appt_type: string | null;
  status: string;
  notes: string | null;
  chief_complaint: string | null;
  doctor_id: number | null;
}

export interface RecordPrescriptionDTO {
  id: number;
  kind: string;
  mode: string | null;
  insurer: string | null;
  portal_rx_id: string | null;
  issued_at: string;
  item_count: number;
  items: unknown;
}

export interface AccountingVisitHistoryDTO {
  visit_id: number;
  invoice_id: number | null;
  visit_date: string;
  work_date: string | null;
  doctor_name: string | null;
  price: number;
  status: string | null;
}

export interface PatientRecordDataDTO {
  condition_catalog: RecordConditionCatalogDTO[];
  conditions: RecordConditionDTO[];
  surgeries: SurgeryHistoryDTO[];
  medical_history: MedicalHistoryDTO[];
  notes: ClinicalNoteDTO[];
  flag_catalog: RecordFlagCatalogDTO[];
  patient_flags: Record<string, string | null>;
  lab_catalog: RecordLabCatalogDTO[];
  suggested_labs: RecordLabCatalogDTO[];
  labs: RecordLabResultDTO[];
  indicator_catalog: RecordIndicatorCatalogDTO[];
  drug_classes: RecordDrugClassDTO[];
  drug_catalog: RecordDrugCatalogDTO[];
  medications: RecordMedicationDTO[];
  medication_events: RecordMedicationEventDTO[];
  appointments: RecordAppointmentDTO[];
  prescriptions: RecordPrescriptionDTO[];
  accounting_visit_history: AccountingVisitHistoryDTO[];
}

export interface ConditionInput {
  condition_id: number;
  stage?: string | null;
  onset_date?: string | null;
  notes?: string | null;
}

export interface SurgeryInput {
  title: string;
  performed_on?: string | null;
  note?: string | null;
}

export interface MedicalHistoryInput {
  title: string;
  since?: string | null;
  note?: string | null;
}

export interface ClinicalNoteInput {
  kind: ClinicalNoteDTO["kind"];
  body: string;
}

export interface FlagsInput {
  managed_keys: string[];
  values: Record<string, string | boolean | null>;
}

export interface MedicationInput {
  drug_id?: number | null;
  drug_name?: string | null;
  drug_class?: string | null;
  dose?: string | null;
  schedule?: string | null;
  start_date?: string | null;
  refill_interval_days?: 15 | 30 | 60 | 90 | null;
  notes?: string | null;
}

export interface LabEntryInput {
  test_key: string;
  value: number;
  notes?: string | null;
}

export interface VitalEntryInput {
  type: string;
  value: number;
  notes?: string | null;
}

interface MutationOut {
  id: number;
  changed?: boolean;
}

interface BulkCreatedOut {
  count: number;
  ids: number[];
}

export function apiGetRecordData(uuid: string): Promise<PatientRecordDataDTO> {
  return apiFetch(`/patients/${uuid}/record-data`);
}

export function apiAddRecordCondition(uuid: string, payload: ConditionInput): Promise<MutationOut> {
  return apiFetch(`/patients/${uuid}/record/conditions`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function apiRemoveRecordCondition(uuid: string, rowId: number): Promise<{ deleted: boolean; id: number }> {
  return apiFetch(`/patients/${uuid}/record/conditions/${rowId}`, { method: "DELETE" });
}

export function apiAddSurgery(uuid: string, payload: SurgeryInput): Promise<SurgeryHistoryDTO> {
  return apiFetch(`/patients/${uuid}/record/surgeries`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function apiDeleteSurgery(uuid: string, rowId: number): Promise<{ deleted: boolean; id: number }> {
  return apiFetch(`/patients/${uuid}/record/surgeries/${rowId}`, { method: "DELETE" });
}

export function apiAddMedicalHistory(uuid: string, payload: MedicalHistoryInput): Promise<MedicalHistoryDTO> {
  return apiFetch(`/patients/${uuid}/record/medical-history`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function apiDeleteMedicalHistory(uuid: string, rowId: number): Promise<{ deleted: boolean; id: number }> {
  return apiFetch(`/patients/${uuid}/record/medical-history/${rowId}`, { method: "DELETE" });
}

export function apiAddClinicalNote(uuid: string, payload: ClinicalNoteInput): Promise<ClinicalNoteDTO> {
  return apiFetch(`/patients/${uuid}/record/notes`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function apiDeleteClinicalNote(uuid: string, rowId: number): Promise<{ deleted: boolean; id: number }> {
  return apiFetch(`/patients/${uuid}/record/notes/${rowId}`, { method: "DELETE" });
}

export function apiUpdateRecordFlags(uuid: string, payload: FlagsInput): Promise<{ values: Record<string, string | null> }> {
  return apiFetch(`/patients/${uuid}/record/flags`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function apiAddRecordMedication(uuid: string, payload: MedicationInput): Promise<RecordMedicationDTO> {
  return apiFetch(`/patients/${uuid}/record/medications`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function apiChangeMedicationDose(
  uuid: string,
  medicationId: number,
  payload: { new_dose: string; change_date?: string | null; note?: string | null },
): Promise<RecordMedicationDTO> {
  return apiFetch(`/patients/${uuid}/record/medications/${medicationId}/dose`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function apiStopRecordMedication(
  uuid: string,
  medicationId: number,
  payload: { end_date?: string | null; note?: string | null },
): Promise<RecordMedicationDTO> {
  return apiFetch(`/patients/${uuid}/record/medications/${medicationId}/stop`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function apiAddRecordLabs(
  uuid: string,
  payload: { items: LabEntryInput[]; taken_at?: string | null },
): Promise<BulkCreatedOut> {
  return apiFetch(`/patients/${uuid}/record/labs`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function apiDeleteRecordLab(uuid: string, labId: number): Promise<{ deleted: boolean; id: number }> {
  return apiFetch(`/patients/${uuid}/record/labs/${labId}`, { method: "DELETE" });
}

export function apiAddRecordVitals(
  uuid: string,
  payload: { items: VitalEntryInput[]; measured_at?: string | null },
): Promise<BulkCreatedOut> {
  return apiFetch(`/patients/${uuid}/record/vitals`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function apiDeleteRecordVital(uuid: string, vitalId: number): Promise<{ deleted: boolean; id: number }> {
  return apiFetch(`/patients/${uuid}/record/vitals/${vitalId}`, { method: "DELETE" });
}
