/** Item-payment API client for migrated accounting invoices. */
import { apiFetch } from "./_core";

export type AccountingPaymentType =
  | "cash"
  | "card"
  | "insurance"
  | "supplementary";

export interface AccountingPaymentSummaryDTO {
  invoice_id: number;
  total_amount: number;
  paid_amount: number;
  remaining_amount: number;
  all_items_paid: boolean;
  payment_type: AccountingPaymentType | null;
}

export function apiGetAccountingInvoiceFinancials(
  invoiceId: number,
): Promise<AccountingPaymentSummaryDTO> {
  return apiFetch(`/accounting/invoices/${invoiceId}/financials`);
}

export function apiSetAccountingItemPayment(
  invoiceId: number,
  itemType: "visit",
  itemId: number,
  paymentType: AccountingPaymentType | null,
  isPaid: boolean,
): Promise<AccountingPaymentSummaryDTO> {
  return apiFetch(
    `/accounting/invoices/${invoiceId}/items/${itemType}/${itemId}/payment`,
    {
      method: "POST",
      body: JSON.stringify({
        payment_type: isPaid ? paymentType : null,
        is_paid: isPaid,
      }),
    },
  );
}

export function apiSettleAccountingInvoice(
  invoiceId: number,
  paymentType: AccountingPaymentType,
): Promise<AccountingPaymentSummaryDTO> {
  return apiFetch(`/accounting/invoices/${invoiceId}/settle-all`, {
    method: "POST",
    body: JSON.stringify({ payment_type: paymentType }),
  });
}
