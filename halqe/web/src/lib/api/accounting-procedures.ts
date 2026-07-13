/** Procedure pricing, payment and close API client. */
import { apiFetch } from "./_core";
import type { AccountingInvoiceDTO } from "./accounting";
import type {
  AccountingPaymentSummaryDTO,
  AccountingPaymentType,
} from "./accounting-payments";

export interface AccountingProcedureTariffDTO {
  id: number;
  name: string;
  unit_price: number;
}

export interface AccountingProcedureInput {
  tariff_id?: number | null;
  name?: string | null;
  unit_price?: number | null;
  quantity: number;
  performer_type?: "doctor" | "nurse" | null;
}

export interface AccountingProcedureMutationDTO {
  invoice_id: number;
  pricing_version: string;
  procedure_ids: number[];
  financials: AccountingPaymentSummaryDTO;
}

export function apiGetAccountingProcedureTariffs(): Promise<
  AccountingProcedureTariffDTO[]
> {
  return apiFetch("/accounting/procedures/tariffs");
}

export function apiAddAccountingProcedureItems(
  invoiceId: number,
  procedures: AccountingProcedureInput[],
  notes?: string | null,
): Promise<AccountingProcedureMutationDTO> {
  return apiFetch(`/accounting/invoices/${invoiceId}/procedure-items`, {
    method: "POST",
    body: JSON.stringify({ procedures, notes: notes ?? null }),
  });
}

export function apiSettleAccountingProcedureInvoice(
  invoiceId: number,
  paymentType: AccountingPaymentType,
): Promise<AccountingPaymentSummaryDTO> {
  return apiFetch(`/accounting/invoices/${invoiceId}/procedure/settle-all`, {
    method: "POST",
    body: JSON.stringify({ payment_type: paymentType }),
  });
}

export function apiSetAccountingProcedureItemPayment(
  invoiceId: number,
  itemType: "visit" | "injection" | "procedure" | "consumable",
  itemId: number,
  paymentType: AccountingPaymentType | null,
  isPaid: boolean,
): Promise<AccountingPaymentSummaryDTO> {
  return apiFetch(
    `/accounting/invoices/${invoiceId}/procedure/items/${itemType}/${itemId}/payment`,
    {
      method: "POST",
      body: JSON.stringify({
        payment_type: isPaid ? paymentType : null,
        is_paid: isPaid,
      }),
    },
  );
}

export function apiCloseAccountingProcedureInvoice(
  invoiceId: number,
): Promise<AccountingInvoiceDTO> {
  return apiFetch(`/accounting/invoices/${invoiceId}/procedure/close`, {
    method: "POST",
  });
}
