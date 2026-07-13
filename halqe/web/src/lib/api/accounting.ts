/** Accounting/reception API client — first migration vertical slice. */
import { apiFetch } from "./_core";

export interface AccountingPatientInput {
  name: string;
  family_name: string;
  national_id?: string | null;
  phone_number?: string | null;
  birthdate?: string | null;
  gender?: string | null;
  insurance_expiry?: string | null;
  address?: string | null;
  is_foreign?: boolean;
}

export interface AccountingPatientDTO {
  id: number;
  uuid: string;
  name: string;
  family_name: string;
  full_name: string;
  national_id: string | null;
  phone_number: string | null;
  birthdate: string | null;
  gender: string | null;
  insurance_type: string | null;
  insurance_expiry: string | null;
  address: string | null;
  is_foreign: boolean;
}

export interface VisitTariffDTO {
  id: number;
  insurance_type: string;
  tariff_price: number;
  is_supplementary: boolean;
  is_base_tariff: boolean;
  nursing_covers: boolean;
  nursing_tariff: number;
}

export interface OpenVisitInvoiceInput {
  patient: AccountingPatientInput;
  insurance_type: string;
  supplementary_insurance?: string | null;
  doctor_id?: number | null;
  work_date?: string | null;
  shift?: string | null;
  notes?: string | null;
}

export interface AccountingInvoiceDTO {
  id: number;
  tenant_id: number;
  patient_id: number;
  patient_uuid: string;
  patient_full_name: string;
  national_id: string | null;
  phone_number: string | null;
  status: "open" | "closed";
  pricing_version: string;
  insurance_type: string | null;
  supplementary_insurance: string | null;
  total_amount: number;
  work_date: string | null;
  shift: string | null;
  opened_at: string;
  closed_at: string | null;
  opened_by: string | null;
  opened_by_name: string | null;
  closed_by: string | null;
  closed_by_name: string | null;
  visit_id: number | null;
  visit_price: number | null;
}

export interface OpenAccountingInvoicesResponse {
  items: AccountingInvoiceDTO[];
  total: number;
  limit: number;
  offset: number;
}

export function apiSearchAccountingPatients(
  query: string,
  limit = 30,
): Promise<AccountingPatientDTO[]> {
  const params = new URLSearchParams({ q: query, limit: String(limit) });
  return apiFetch(`/accounting/patients/search?${params.toString()}`);
}

export function apiGetVisitTariffs(): Promise<VisitTariffDTO[]> {
  return apiFetch("/accounting/tariffs/visits");
}

export function apiGetOpenAccountingInvoices(
  limit = 50,
  offset = 0,
): Promise<OpenAccountingInvoicesResponse> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  return apiFetch(`/accounting/invoices/open?${params.toString()}`);
}

export function apiOpenVisitInvoice(
  payload: OpenVisitInvoiceInput,
): Promise<AccountingInvoiceDTO> {
  return apiFetch("/accounting/invoices/visit", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function apiCloseAccountingInvoice(
  invoiceId: number,
): Promise<AccountingInvoiceDTO> {
  return apiFetch(`/accounting/invoices/${invoiceId}/close`, {
    method: "POST",
  });
}
