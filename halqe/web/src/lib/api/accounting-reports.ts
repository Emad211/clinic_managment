import { apiFetch } from "./_core";
import type {
  AccountingInvoiceReportDTO,
  AccountingReportFilters,
  AccountingReportsOverviewDTO,
  AccountingServiceReportDTO,
} from "./accounting-report-types";

export * from "./accounting-report-types";

function query(filters: AccountingReportFilters): string {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, String(value));
    }
  });
  const rendered = params.toString();
  return rendered ? `?${rendered}` : "";
}

export function apiGetAccountingReportsOverview(
  filters: AccountingReportFilters,
): Promise<AccountingReportsOverviewDTO> {
  return apiFetch(`/accounting/reports/overview${query(filters)}`);
}

export function apiGetAccountingInvoiceReport(
  filters: AccountingReportFilters,
): Promise<AccountingInvoiceReportDTO> {
  return apiFetch(`/accounting/reports/invoices${query(filters)}`);
}

export function apiGetAccountingServiceReport(
  filters: AccountingReportFilters,
): Promise<AccountingServiceReportDTO> {
  return apiFetch(`/accounting/reports/services${query(filters)}`);
}
