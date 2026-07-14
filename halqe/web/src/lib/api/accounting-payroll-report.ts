import { apiFetch } from "./_core";
import type {
  AccountingPayrollReportDTO,
  AccountingReportFilters,
} from "./accounting-report-types";

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

export function apiGetAccountingPayrollReport(
  filters: AccountingReportFilters,
): Promise<AccountingPayrollReportDTO> {
  return apiFetch(`/accounting/reports/payroll${query(filters)}`);
}
