/** Full accounting invoice projection and correction API client. */
import { apiFetch } from "./_core";
import type { AccountingInvoiceDTO } from "./accounting";
import type { AccountingPaymentSummaryDTO } from "./accounting-payments";

export type AccountingWorkbenchItemType =
  | "visit"
  | "injection"
  | "procedure"
  | "consumable";

export interface AccountingWorkbenchItemDTO {
  item_type: AccountingWorkbenchItemType;
  item_id: number;
  description: string;
  quantity: number;
  recorded_amount: number;
  patient_amount: number;
  insurance_amount: number;
  covered_by_insurance: boolean;
  performer_type: string | null;
  performer_id: number | null;
  performer_name: string | null;
  occurred_at: string;
  notes: string | null;
  payment_type: string | null;
  is_paid: boolean;
  payment_updated_at: string | null;
}

export interface AccountingInvoiceWorkbenchDTO {
  invoice: AccountingInvoiceDTO;
  items: AccountingWorkbenchItemDTO[];
  financials: AccountingPaymentSummaryDTO;
}

export interface AccountingDeleteItemDTO {
  deleted: boolean;
  item_type: AccountingWorkbenchItemType;
  item_id: number;
  detail: AccountingInvoiceWorkbenchDTO;
}

export function apiGetAccountingInvoiceDetail(
  invoiceId: number,
): Promise<AccountingInvoiceWorkbenchDTO> {
  return apiFetch(`/accounting/invoices/${invoiceId}/detail`);
}

export function apiAddAccountingVisitToInvoice(
  invoiceId: number,
  notes?: string | null,
): Promise<AccountingInvoiceWorkbenchDTO> {
  return apiFetch(`/accounting/invoices/${invoiceId}/visits`, {
    method: "POST",
    body: JSON.stringify({ notes: notes ?? null }),
  });
}

export function apiDeleteAccountingInvoiceItem(
  invoiceId: number,
  itemType: AccountingWorkbenchItemType,
  itemId: number,
): Promise<AccountingDeleteItemDTO> {
  return apiFetch(
    `/accounting/invoices/${invoiceId}/items/${itemType}/${itemId}`,
    { method: "DELETE" },
  );
}
