/** Structured patient-record API client migrated from specialist_clinic. */
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

export interface StructuredConditionDTO {
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

export interface MedicationEventDTO {
  id: number;
  medication_id: number | null;
  drug_name: string;
  event_type: "start" | "stop" | "dose_change" | string;
  dose: string | null;
  event_date: string | null;
  note: string | null;
  created_by: string | null;
  created_at: string;
}

export interface StructuredMedicationDTO {
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
  events: MedicationEventDTO[];
}

export interface RecordFlagOptionDTO {
  value: string;
  label: string;
}

export interface RecordFlagDTO {
  id: number;
  flag_key: string;
  label: string;
  flag_type: "bool" | "enum" | "date" | "text" | string;
  options: RecordFlagOptionDTO[];
  category: string;
  record_section: string;
  display_order: number;
  notes: string | null;
  value: string | null;
  recorded_by: string | null;
  updated_at: string | null;
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
  kind: "symptom" | "exam" | "lifestyle" | "general" | string;
  body: string | null;
  recorded_at: string;
  recorded_by: string | null;
}

export interface StructuredLabResultDTO {
  id: number;
  encounter_id: number | null;
  test_name: string;
  test_key: string | null;
  value: number | null;
  unit: string | null;
  ref_low: number | null;
  ref_high: number | null;
  taken_at: string;
  notes: string | null;
  recorded_by: string | null;
}

export interface LabCatalogDTO {
  id: number;
  test_key: string;
  name_fa: string;
  unit: string | null;
  ref_low: number | null;
  ref_high: number | null;
  category: string | null;
  display_order: number;
  suggested: boolean;
}

export interface RecordAppointmentDTO {
  id: number;
  scheduled_at: string;
  appt_type: string | null;
  status: string;
  recurrence_months: number | null;
  reminder_sent: boolean;
  notes: string | null;
  doctor_id: number | null;
  chief_complaint: string | null;
}

export interface RecordFollowupDTO {
  id: number;
  due_date: string | null;
  reason: string | null;
  detail: string | null;
  status: string;
  assigned_to: string | null;
  call_log: string | null;
  source_rule: string | null;
  source_event: string | null;
  appointment_id: number | null;
  fulfillment: string | null;
  created_at: string;
  resolved_at: string | null;
}

export interface RecordPrescriptionItemDTO {
  id: number | null;
  drug_name: string;
  drug_class: string | null;
  dose_value: string | null;
  dose_unit: string | null;
  frequency: string | null;
  route: string | null;
  quantity: number | null;
  duration_days: number | null;
  instructions: string | null;
  source: "structured" | "legacy_json" | string;
}

export interface RecordPrescriptionDTO {
  id: number;
  kind: string;
  mode: string;
  insurer: string | null;
  portal_rx_id: string | null;
  prescriber_user_id: number | null;
  followup_task_id: number | null;
  encounter_id: number | null;
  issued_at: string;
  items: RecordPrescriptionItemDTO[];
}

export interface RecordDrugClassDTO {
  id: number;
  class_key: string;
  label: string;
  glucose_lowering: boolean;
  display_order: number;
}

export interface RecordDrugCatalogDTO {
  id: number;
  generic_fa: string;
  drug_class_key: string | null;
  standard_doses: string[];
}

export interface StructuredPatientRecordDTO {
  patient_link_id: number;
  condition_catalog: RecordConditionCatalogDTO[];
  conditions: StructuredConditionDTO[];
  medications: StructuredMedicationDTO[];
  orphan_medication_events: MedicationEventDTO[];
  flag_catalog: RecordFlagDTO[];
  surgeries: SurgeryHistoryDTO[];
  medical_history: MedicalHistoryDTO[];
  clinical_notes: ClinicalNoteDTO[];
  labs: StructuredLabResultDTO[];
  lab_catalog: LabCatalogDTO[];
  appointments: RecordAppointmentDTO[];
  followups: RecordFollowupDTO[];
  prescriptions: RecordPrescriptionDTO[];
  drug_classes: RecordDrugClassDTO[];
  drug_catalog: RecordDrugCatalogDTO[];
}

export interface AddConditionInput {
  condition_id: number;
  stage?: string | null;
  onset_date?: string | null;
  notes?: string | null;
}

export interface AddMedicationInput {
  drug_name: string;
  dose?: string | null;
  schedule?: string | null;
  start_date?: string | null;
  refill_due_date?: string | null;
  refill_interval_days?: number | null;
  notes?: string | null;
  drug_class?: string | null;
}

export interface PatchFlagsInput {
  values: Record<string, unknown>;
  clear_keys?: string[];
}

export interface AddLabInput {
  test_key?: string | null;
  test_name?: string | null;
  value?: number | null;
  unit?: string | null;
  ref_low?: number | null;
  ref_high?: number | null;
  taken_at?: string | null;
  notes?: string | null;
}

export interface DeleteRecordOut {
  deleted: boolean;
  id: number;
}

export function apiGetStructuredPatientRecord(
  uuid: string,
): Promise<StructuredPatientRecordDTO> {
  return apiFetch(`/patients/${uuid}/record/structured`);
}

export function apiAddPatientCondition(
  uuid: string,
  payload: AddConditionInput,
): Promise<StructuredConditionDTO> {
  return apiFetch(`/patients/${uuid}/record/conditions`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function apiDeactivatePatientCondition(
  uuid: string,
  patientConditionId: number,
): Promise<DeleteRecordOut> {
  return apiFetch(`/patients/${uuid}/record/conditions/${patientConditionId}`, {
    method: "DELETE",
  });
}

export function apiAddPatientMedication(
  uuid: string,
  payload: AddMedicationInput,
): Promise<StructuredMedicationDTO> {
  return apiFetch(`/patients/${uuid}/record/medications`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function apiStopPatientMedication(
  uuid: string,
  medicationId: number,
  endDate?: string | null,
  note?: string | null,
): Promise<StructuredMedicationDTO> {
  return apiFetch(`/patients/${uuid}/record/medications/${medicationId}/stop`, {
    method: "POST",
    body: JSON.stringify({ end_date: endDate ?? null, note: note ?? null }),
  });
}

export function apiChangePatientMedicationDose(
  uuid: string,
  medicationId: number,
  dose: string,
  changeDate?: string | null,
  note?: string | null,
): Promise<StructuredMedicationDTO> {
  return apiFetch(`/patients/${uuid}/record/medications/${medicationId}/dose`, {
    method: "POST",
    body: JSON.stringify({
      dose,
      change_date: changeDate ?? null,
      note: note ?? null,
    }),
  });
}

export function apiPatchPatientRecordFlags(
  uuid: string,
  payload: PatchFlagsInput,
): Promise<RecordFlagDTO[]> {
  return apiFetch(`/patients/${uuid}/record/flags`, {
    method: "PATCH",
    body: JSON.stringify({
      values: payload.values,
      clear_keys: payload.clear_keys ?? [],
    }),
  });
}

export function apiAddPatientSurgery(
  uuid: string,
  title: string,
  performedOn?: string | null,
  note?: string | null,
): Promise<SurgeryHistoryDTO> {
  return apiFetch(`/patients/${uuid}/record/surgeries`, {
    method: "POST",
    body: JSON.stringify({
      title,
      performed_on: performedOn ?? null,
      note: note ?? null,
    }),
  });
}

export function apiDeletePatientSurgery(
  uuid: string,
  surgeryId: number,
): Promise<DeleteRecordOut> {
  return apiFetch(`/patients/${uuid}/record/surgeries/${surgeryId}`, {
    method: "DELETE",
  });
}

export function apiAddPatientMedicalHistory(
  uuid: string,
  title: string,
  since?: string | null,
  note?: string | null,
): Promise<MedicalHistoryDTO> {
  return apiFetch(`/patients/${uuid}/record/medical-history`, {
    method: "POST",
    body: JSON.stringify({ title, since: since ?? null, note: note ?? null }),
  });
}

export function apiDeletePatientMedicalHistory(
  uuid: string,
  historyId: number,
): Promise<DeleteRecordOut> {
  return apiFetch(`/patients/${uuid}/record/medical-history/${historyId}`, {
    method: "DELETE",
  });
}

export function apiAddPatientClinicalNote(
  uuid: string,
  kind: "symptom" | "exam" | "lifestyle" | "general",
  body: string,
): Promise<ClinicalNoteDTO> {
  return apiFetch(`/patients/${uuid}/record/notes`, {
    method: "POST",
    body: JSON.stringify({ kind, body }),
  });
}

export function apiDeletePatientClinicalNote(
  uuid: string,
  noteId: number,
): Promise<DeleteRecordOut> {
  return apiFetch(`/patients/${uuid}/record/notes/${noteId}`, {
    method: "DELETE",
  });
}

export function apiAddPatientLabResult(
  uuid: string,
  payload: AddLabInput,
): Promise<StructuredLabResultDTO> {
  return apiFetch(`/patients/${uuid}/record/labs`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function apiDeletePatientLabResult(
  uuid: string,
  labId: number,
): Promise<DeleteRecordOut> {
  return apiFetch(`/patients/${uuid}/record/labs/${labId}`, {
    method: "DELETE",
  });
}
