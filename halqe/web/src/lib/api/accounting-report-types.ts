export interface AccountingInvoiceRowDTO {
  id: number;
  work_date: string | null;
  opened_at: string;
  closed_at: string | null;
  status: "open" | "closed";
  total_amount: number;
  insurance_type: string | null;
  supplementary_insurance: string | null;
  opened_by?: string | null;
  opened_by_name: string | null;
  closed_by?: string | null;
  closed_by_name: string | null;
  patient_name: string;
}

export interface AccountingDailyFinancialDTO {
  day: string;
  visits: number;
  nursing: number;
  procedures: number;
  consumables: number;
  operating_revenue: number;
  consumables_cost: number;
}

export interface AccountingReportsOverviewDTO {
  date_from: string;
  date_to: string;
  invoices: {
    total: number;
    open: number;
    closed: number;
    unique_patients: number;
    total_liability: number;
  };
  revenue: {
    visit: { count: number; amount: number };
    nursing: { count: number; amount: number };
    procedure: { count: number; amount: number };
    operating_revenue: number;
  };
  consumables: { count: number; amount: number };
  payments: { items: number; paid_items: number; unpaid_items: number };
  daily: AccountingDailyFinancialDTO[];
  recent_invoices: AccountingInvoiceRowDTO[];
  filters: {
    insurances: string[];
    reception_users: Array<{ username: string; full_name: string }>;
  };
}

export interface AccountingInvoiceReportDTO {
  date_from: string;
  date_to: string;
  summary: { total: number; open: number; closed: number; total_amount: number };
  rows: AccountingInvoiceRowDTO[];
}

export interface AccountingServiceRowDTO {
  service_type: "visit" | "nursing" | "procedure" | "consumable";
  id: number;
  invoice_id: number | null;
  work_date: string | null;
  occurred_at: string;
  patient_name: string;
  service_name: string;
  quantity: number;
  amount: number;
  patient_amount: number;
  insurance_amount: number;
  doctor_id: number | null;
  nurse_id: number | null;
  staff_name: string | null;
  performer_type: string | null;
  shift: string | null;
  reception_user: string | null;
  included_in_revenue: boolean;
  patient_provided: boolean;
  is_exception: boolean;
}

export interface AccountingServiceReportDTO {
  date_from: string;
  date_to: string;
  summary: Record<string, { count: number; amount: number }>;
  rows: AccountingServiceRowDTO[];
}

export interface AccountingPayrollDetailDTO {
  code: string;
  label: string;
  count: number;
  unit_price: number;
  total: number;
}

export interface AccountingPayrollRowDTO {
  id: number;
  name: string;
  staff_type: "doctor" | "nurse";
  type_label: string;
  shift_counts: { morning: number; evening: number; night: number };
  details: AccountingPayrollDetailDTO[];
  gross_salary: number;
  tax_amount: number;
  net_salary: number;
}

export interface AccountingPayrollReportDTO {
  date_from: string;
  date_to: string;
  summary: {
    staff_count: number;
    gross_salary: number;
    tax_amount: number;
    net_salary: number;
  };
  rows: AccountingPayrollRowDTO[];
}

export interface AccountingReportFilters {
  date_from?: string;
  date_to?: string;
  status?: string;
  insurance_type?: string;
  reception_user?: string;
  service_type?: string;
  shift?: string;
  staff_id?: number | null;
  staff_type?: string;
  limit?: number;
}
