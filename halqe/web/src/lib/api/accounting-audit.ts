import { apiFetch } from "./_core";

export interface AccountingAuditUserDTO {
  user_id: number | null;
  username: string;
  full_name: string;
}

export interface AccountingAuditRowDTO {
  id: number;
  created_at: string;
  user_id: number | null;
  username: string;
  user_full_name: string;
  action_type: string;
  action_category: string;
  description: string | null;
  target_type: string | null;
  target_id: number | null;
  target_name: string | null;
  invoice_id: number | null;
  patient_id: number | null;
  patient_name: string | null;
  amount: number;
  old_value: string | null;
  new_value: string | null;
  ip_address: string | null;
  user_agent: string | null;
}

export interface AccountingAuditSearchDTO {
  date_from: string;
  date_to: string;
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
  rows: AccountingAuditRowDTO[];
  category_summary: Array<{ action_category: string; count: number }>;
  filter_options: {
    action_types: string[];
    action_categories: string[];
    users: AccountingAuditUserDTO[];
  };
}

export interface AccountingAuditFilters {
  date_from?: string;
  date_to?: string;
  page?: number;
  page_size?: number;
  user_id?: number | null;
  action_type?: string;
  action_category?: string;
  invoice_id?: number | null;
  patient_id?: number | null;
  search_text?: string;
}

export function apiGetAccountingAuditLogs(
  filters: AccountingAuditFilters,
): Promise<AccountingAuditSearchDTO> {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, String(value));
    }
  });
  const query = params.toString();
  return apiFetch(`/accounting/audit/logs${query ? `?${query}` : ""}`);
}
