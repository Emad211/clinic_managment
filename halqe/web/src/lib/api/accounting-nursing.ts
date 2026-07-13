/** Nursing, consumable and shift-staff accounting API client. */
import { apiFetch } from "./_core";
import type { AccountingInvoiceDTO } from "./accounting";
import type {
  AccountingPaymentSummaryDTO,
  AccountingPaymentType,
} from "./accounting-payments";

export interface AccountingNursingServiceDTO {
  id: number;
  service_name: string;
  unit_price: number;
}

export interface AccountingConsumableTariffDTO {
  id: number;
  name: string;
  default_price: number;
  category: "drug" | "supply";
}

export interface AccountingStaffDTO {
  id: number;
  full_name: string;
  staff_type: "doctor" | "nurse";
}

export interface AccountingShiftStaffDTO {
  id: number;
  work_date: string;
  shift: string;
  doctor_id: number | null;
  nurse_id: number | null;
  doctor_name: string | null;
  nurse_name: string | null;
  updated_at: string;
}

export interface AccountingNursingServiceInput {
  service_id: number;
  quantity: number;
}

export interface AccountingConsumableInput {
  name: string;
  category: "drug" | "supply";
  quantity: number;
  unit_price: number;
  patient_provided?: boolean;
  is_exception?: boolean;
}

export interface AccountingNursingItemsInput {
  services: AccountingNursingServiceInput[];
  consumables: AccountingConsumableInput[];
  notes?: string | null;
}

export interface AccountingNursingMutationDTO {
  invoice_id: number;
  pricing_version: string;
  injection_ids: number[];
  consumable_ids: number[];
  financials: AccountingPaymentSummaryDTO;
}

export function apiGetAccountingNursingServices(): Promise<
  AccountingNursingServiceDTO[]
> {
  return apiFetch("/accounting/nursing/services");
}

export function apiGetAccountingConsumableTariffs(
  category?: "drug" | "supply",
): Promise<AccountingConsumableTariffDTO[]> {
  const suffix = category ? `?category=${encodeURIComponent(category)}` : "";
  return apiFetch(`/accounting/consumables/tariffs${suffix}`);
}

export function apiGetAccountingStaff(
  staffType?: "doctor" | "nurse",
): Promise<AccountingStaffDTO[]> {
  const suffix = staffType
    ? `?staff_type=${encodeURIComponent(staffType)}`
    : "";
  return apiFetch(`/accounting/staff${suffix}`);
}

export function apiGetAccountingShiftStaff(
  invoiceId: number,
): Promise<AccountingShiftStaffDTO | null> {
  return apiFetch(`/accounting/invoices/${invoiceId}/shift-staff`);
}

export function apiSetAccountingShiftStaff(
  invoiceId: number,
  doctorId: number | null,
  nurseId: number | null,
): Promise<AccountingShiftStaffDTO> {
  return apiFetch(`/accounting/invoices/${invoiceId}/shift-staff`, {
    method: "PUT",
    body: JSON.stringify({ doctor_id: doctorId, nurse_id: nurseId }),
  });
}

export function apiAddAccountingNursingItems(
  invoiceId: number,
  payload: AccountingNursingItemsInput,
): Promise<AccountingNursingMutationDTO> {
  return apiFetch(`/accounting/invoices/${invoiceId}/nursing-items`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function apiSettleAccountingNursingInvoice(
  invoiceId: number,
  paymentType: AccountingPaymentType,
): Promise<AccountingPaymentSummaryDTO> {
  return apiFetch(`/accounting/invoices/${invoiceId}/nursing/settle-all`, {
    method: "POST",
    body: JSON.stringify({ payment_type: paymentType }),
  });
}

export function apiSetAccountingNursingItemPayment(
  invoiceId: number,
  itemType: "visit" | "injection" | "consumable",
  itemId: number,
  paymentType: AccountingPaymentType | null,
  isPaid: boolean,
): Promise<AccountingPaymentSummaryDTO> {
  return apiFetch(
    `/accounting/invoices/${invoiceId}/nursing/items/${itemType}/${itemId}/payment`,
    {
      method: "POST",
      body: JSON.stringify({
        payment_type: isPaid ? paymentType : null,
        is_paid: isPaid,
      }),
    },
  );
}

export function apiCloseAccountingNursingInvoice(
  invoiceId: number,
): Promise<AccountingInvoiceDTO> {
  return apiFetch(`/accounting/invoices/${invoiceId}/nursing/close`, {
    method: "POST",
  });
}
