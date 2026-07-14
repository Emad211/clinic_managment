/** Manager-only accounting configuration API client. */
import { apiFetch } from "./_core";

export interface AccountingAdminStaffDTO {
  id: number;
  full_name: string;
  staff_type: "doctor" | "nurse";
  is_active: boolean;
  created_at: string;
}

export interface AccountingInsuranceSchemeDTO {
  id: number;
  code: string;
  name: string;
  is_supplementary: boolean;
  is_base: boolean;
  is_active: boolean;
  created_at: string;
}

export interface AccountingAdminVisitTariffDTO {
  id: number;
  insurance_type: string;
  insurance_scheme_id: number | null;
  tariff_price: number;
  nursing_tariff: number;
  nursing_covers: boolean;
  is_active: boolean;
  is_supplementary: boolean;
  is_base_tariff: boolean;
  created_at: string;
  updated_at: string;
}

export type AccountingCatalogType = "nursing" | "procedure" | "consumable";

export interface AccountingAdminCatalogItemDTO {
  id: number;
  name: string;
  price: number;
  category: "drug" | "supply" | null;
  is_active: boolean;
  created_at: string;
}

export interface AccountingAdminExclusionDTO {
  id: number;
  insurance_type: string;
  nursing_service_id: number;
  service_name: string | null;
  note: string | null;
  created_at: string;
}

export interface AccountingPayrollSettingDTO {
  id: number;
  staff_id: number;
  staff_name: string | null;
  staff_type: string | null;
  base_morning: number;
  base_evening: number;
  base_night: number;
  visit_fee: number;
  injection_percent: number;
  procedure_percent: number;
  tax_percent: number;
  nursing_percent: number;
  nurse_procedure_percent: number;
  updated_at: string;
}

export interface AccountingAdminConfigurationDTO {
  staff: AccountingAdminStaffDTO[];
  insurance_schemes: AccountingInsuranceSchemeDTO[];
  visit_tariffs: AccountingAdminVisitTariffDTO[];
  catalogs: Record<AccountingCatalogType, AccountingAdminCatalogItemDTO[]>;
  exclusions: AccountingAdminExclusionDTO[];
  payroll_settings: AccountingPayrollSettingDTO[];
}

export type StaffInput = Omit<AccountingAdminStaffDTO, "created_at">;
export type InsuranceSchemeInput = Omit<AccountingInsuranceSchemeDTO, "created_at">;
export type VisitTariffInput = Omit<
  AccountingAdminVisitTariffDTO,
  "created_at" | "updated_at"
>;
export type CatalogItemInput = Omit<AccountingAdminCatalogItemDTO, "created_at">;
export type ExclusionInput = Omit<
  AccountingAdminExclusionDTO,
  "created_at" | "service_name"
>;
export type PayrollInput = Omit<
  AccountingPayrollSettingDTO,
  "id" | "staff_name" | "staff_type" | "updated_at"
>;

export function apiGetAccountingAdminConfiguration(): Promise<AccountingAdminConfigurationDTO> {
  return apiFetch("/accounting/admin/config");
}

export function apiSaveAccountingStaff(
  payload: Partial<StaffInput> & Pick<StaffInput, "full_name" | "staff_type">,
): Promise<AccountingAdminStaffDTO> {
  return apiFetch("/accounting/admin/staff", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function apiSaveAccountingInsuranceScheme(
  payload: Partial<InsuranceSchemeInput> & Pick<InsuranceSchemeInput, "code" | "name">,
): Promise<AccountingInsuranceSchemeDTO> {
  return apiFetch("/accounting/admin/insurance-schemes", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function apiSaveAccountingVisitTariff(
  payload: Partial<VisitTariffInput> & Pick<VisitTariffInput, "insurance_type">,
): Promise<AccountingAdminVisitTariffDTO> {
  return apiFetch("/accounting/admin/visit-tariffs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function apiSaveAccountingCatalogItem(
  catalogType: AccountingCatalogType,
  payload: Partial<CatalogItemInput> & Pick<CatalogItemInput, "name">,
): Promise<AccountingAdminCatalogItemDTO> {
  return apiFetch(`/accounting/admin/catalogs/${catalogType}`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function apiSaveAccountingExclusion(
  payload: Partial<ExclusionInput> &
    Pick<ExclusionInput, "insurance_type" | "nursing_service_id">,
): Promise<AccountingAdminExclusionDTO> {
  return apiFetch("/accounting/admin/exclusions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function apiDeleteAccountingExclusion(
  exclusionId: number,
): Promise<{ deleted: boolean; id: number }> {
  return apiFetch(`/accounting/admin/exclusions/${exclusionId}`, {
    method: "DELETE",
  });
}

export function apiSaveAccountingPayrollSettings(
  payload: PayrollInput,
): Promise<AccountingPayrollSettingDTO> {
  return apiFetch("/accounting/admin/payroll-settings", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
