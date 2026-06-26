/**
 * Doctor Queue domain — mirrors DoctorQueueEntry + DoctorQueueResponse +
 * DoctorVisitLog.
 */
import { apiFetch } from "./_core";

export interface DoctorQueueEntry {
  invoice_id: number;
  patient_id: number;
  patient_uuid?: string | null;
  full_name: string;
  phone_number?: string | null;
  opened_at?: string | null;
  work_date?: string | null;
  status: string;            // "waiting" | "in_progress" | "done"
  patient_link_id?: number | null;
  enrolled: boolean;
  done_by?: string | null;
  started_at?: string | null;
  done_at?: string | null;
}

export interface DoctorQueueResponse {
  waiting: DoctorQueueEntry[];  // includes waiting + in_progress
  done: DoctorQueueEntry[];
  work_date: string;
}

export interface DoctorVisitLog {
  id: number;
  tenant_id: number;
  accounting_invoice_id: number;
  patient_link_id?: number | null;
  patient_uuid?: string | null;
  full_name: string;
  work_date: string;
  status: string;
  started_at?: string | null;
  done_at?: string | null;
  physician_notes?: string | null;
  done_by?: string | null;
  created_at?: string | null;
}

/**
 * GET /doctor-queue?work_date=YYYY-MM-DD
 * work_date is optional — backend defaults to today (Tehran local).
 */
export async function apiGetDoctorQueue(
  workDate?: string,
): Promise<DoctorQueueResponse> {
  const path = workDate
    ? `/doctor-queue?work_date=${encodeURIComponent(workDate)}`
    : "/doctor-queue";
  return apiFetch<DoctorQueueResponse>(path);
}

/**
 * POST /doctor-queue/{invoiceId}/start
 * Transitions the entry from waiting → in_progress.
 */
export async function apiStartVisit(
  invoiceId: number,
): Promise<DoctorVisitLog> {
  return apiFetch<DoctorVisitLog>(`/doctor-queue/${invoiceId}/start`, {
    method: "POST",
  });
}

/**
 * POST /doctor-queue/{invoiceId}/done
 * Transitions the entry from in_progress → done.
 * Optional physician notes are sent in the request body.
 */
export async function apiMarkVisitDone(
  invoiceId: number,
  notes?: string,
): Promise<DoctorVisitLog> {
  return apiFetch<DoctorVisitLog>(`/doctor-queue/${invoiceId}/done`, {
    method: "POST",
    body: JSON.stringify({ notes: notes ?? null }),
  });
}
