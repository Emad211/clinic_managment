import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom";

jest.mock("@/lib/api/accounting-admin", () => ({
  apiSaveAccountingStaff: jest.fn(),
  apiSaveAccountingInsuranceScheme: jest.fn(),
  apiSaveAccountingVisitTariff: jest.fn(),
  apiSaveAccountingCatalogItem: jest.fn(),
  apiSaveAccountingExclusion: jest.fn(),
  apiDeleteAccountingExclusion: jest.fn(),
  apiSaveAccountingPayrollSettings: jest.fn(),
}));

import {
  apiDeleteAccountingExclusion,
  apiSaveAccountingCatalogItem,
  apiSaveAccountingExclusion,
  apiSaveAccountingInsuranceScheme,
  apiSaveAccountingPayrollSettings,
  apiSaveAccountingStaff,
  apiSaveAccountingVisitTariff,
  type AccountingAdminConfigurationDTO,
} from "@/lib/api/accounting-admin";
import { AccountingStaffSettings } from "@/components/accounting-settings/AccountingStaffSettings";
import { AccountingInsuranceSettings } from "@/components/accounting-settings/AccountingInsuranceSettings";
import { AccountingCatalogSettings } from "@/components/accounting-settings/AccountingCatalogSettings";
import { AccountingPayrollSettings } from "@/components/accounting-settings/AccountingPayrollSettings";

const CONFIG: AccountingAdminConfigurationDTO = {
  staff: [
    { id: 1, full_name: "دکتر نمونه", staff_type: "doctor", is_active: true, created_at: "2026-01-01T00:00:00Z" },
    { id: 2, full_name: "پرستار نمونه", staff_type: "nurse", is_active: true, created_at: "2026-01-01T00:00:00Z" },
  ],
  insurance_schemes: [
    { id: 3, code: "base", name: "بیمه پایه", is_supplementary: false, is_base: true, is_active: true, created_at: "2026-01-01T00:00:00Z" },
  ],
  visit_tariffs: [
    { id: 4, insurance_type: "بیمه پایه", insurance_scheme_id: 3, tariff_price: 125000, nursing_tariff: 20000, nursing_covers: true, is_active: true, is_supplementary: false, is_base_tariff: true, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" },
  ],
  catalogs: {
    nursing: [{ id: 5, name: "تزریق عضلانی", price: 40000, category: null, is_active: true, created_at: "2026-01-01T00:00:00Z" }],
    procedure: [{ id: 6, name: "پانسمان", price: 80000, category: null, is_active: true, created_at: "2026-01-01T00:00:00Z" }],
    consumable: [{ id: 7, name: "گاز", price: 12000, category: "supply", is_active: true, created_at: "2026-01-01T00:00:00Z" }],
  },
  exclusions: [
    { id: 8, insurance_type: "بیمه پایه", nursing_service_id: 5, service_name: "تزریق عضلانی", note: "پرداخت بیمار", created_at: "2026-01-01T00:00:00Z" },
  ],
  payroll_settings: [
    { id: 9, staff_id: 1, staff_name: "دکتر نمونه", staff_type: "doctor", base_morning: 500000, base_evening: 600000, base_night: 750000, visit_fee: 25000, injection_percent: 20.5, procedure_percent: 30, tax_percent: 5, nursing_percent: 15, nurse_procedure_percent: 25, updated_at: "2026-01-01T00:00:00Z" },
  ],
};

const changed = jest.fn(async () => undefined);
const setError = jest.fn();

beforeEach(() => {
  jest.clearAllMocks();
  changed.mockResolvedValue(undefined);
  (apiSaveAccountingStaff as jest.Mock).mockResolvedValue(CONFIG.staff[0]);
  (apiSaveAccountingInsuranceScheme as jest.Mock).mockResolvedValue(CONFIG.insurance_schemes[0]);
  (apiSaveAccountingVisitTariff as jest.Mock).mockResolvedValue(CONFIG.visit_tariffs[0]);
  (apiSaveAccountingCatalogItem as jest.Mock).mockResolvedValue(CONFIG.catalogs.nursing[0]);
  (apiSaveAccountingExclusion as jest.Mock).mockResolvedValue(CONFIG.exclusions[0]);
  (apiDeleteAccountingExclusion as jest.Mock).mockResolvedValue({ deleted: true, id: 8 });
  (apiSaveAccountingPayrollSettings as jest.Mock).mockResolvedValue(CONFIG.payroll_settings[0]);
  Object.defineProperty(window, "confirm", { configurable: true, value: jest.fn(() => true) });
});

test("staff form creates and edit action repopulates the form", async () => {
  render(<AccountingStaffSettings config={CONFIG} onChanged={changed} onError={setError} />);
  fireEvent.change(screen.getByLabelText("نام و نام خانوادگی"), { target: { value: "پرستار جدید" } });
  fireEvent.change(screen.getByLabelText("نقش"), { target: { value: "nurse" } });
  fireEvent.click(screen.getByRole("button", { name: "ذخیره کادر" }));
  await waitFor(() => expect(apiSaveAccountingStaff).toHaveBeenCalled());
  expect(apiSaveAccountingStaff).toHaveBeenCalledWith({ id: null, full_name: "پرستار جدید", staff_type: "nurse", is_active: true });

  fireEvent.click(screen.getAllByRole("button", { name: "ویرایش" })[0]);
  expect(screen.getByLabelText("نام و نام خانوادگی")).toHaveValue("دکتر نمونه");
});

test("insurance workspace submits scheme and numeric tariff snapshots", async () => {
  render(<AccountingInsuranceSettings config={CONFIG} onChanged={changed} onError={setError} />);
  const schemeForm = screen.getByRole("heading", { name: "تعریف بیمه" }).closest("form")!;
  fireEvent.change(within(schemeForm).getByLabelText("کد"), { target: { value: "supp" } });
  fireEvent.change(within(schemeForm).getByLabelText("نام"), { target: { value: "بیمه تکمیلی" } });
  fireEvent.click(within(schemeForm).getByLabelText("تکمیلی"));
  fireEvent.click(within(schemeForm).getByRole("button", { name: "ذخیره بیمه" }));
  await waitFor(() => expect(apiSaveAccountingInsuranceScheme).toHaveBeenCalled());

  const tariffForm = screen.getByRole("heading", { name: "تعرفه و پوشش بیمه" }).closest("section")!;
  fireEvent.change(within(tariffForm).getByLabelText("نام تعرفه"), { target: { value: "بیمه پایه" } });
  fireEvent.change(within(tariffForm).getByLabelText("تعرفه ویزیت"), { target: { value: "135000" } });
  fireEvent.change(within(tariffForm).getByLabelText("تعرفه پرستاری"), { target: { value: "25000" } });
  fireEvent.click(within(tariffForm).getByRole("button", { name: "ذخیره تعرفه" }));
  await waitFor(() => expect(apiSaveAccountingVisitTariff).toHaveBeenCalled());
  expect(apiSaveAccountingVisitTariff).toHaveBeenCalledWith(expect.objectContaining({ tariff_price: 135000, nursing_tariff: 25000 }));
});

test("catalog and exclusion flows preserve type and require destructive confirmation", async () => {
  render(<AccountingCatalogSettings config={CONFIG} onChanged={changed} onError={setError} />);
  fireEvent.change(screen.getByLabelText("کاتالوگ"), { target: { value: "consumable" } });
  fireEvent.change(screen.getByLabelText("نام"), { target: { value: "سرنگ" } });
  fireEvent.change(screen.getByLabelText("قیمت (تومان)"), { target: { value: "18000" } });
  fireEvent.click(screen.getByRole("button", { name: "ذخیره خدمت" }));
  await waitFor(() => expect(apiSaveAccountingCatalogItem).toHaveBeenCalled());
  expect(apiSaveAccountingCatalogItem).toHaveBeenCalledWith("consumable", expect.objectContaining({ name: "سرنگ", price: 18000, category: "supply" }));

  const exclusionSection = screen.getByRole("heading", { name: "استثناهای پوشش پرستاری" }).closest("section")!;
  fireEvent.change(within(exclusionSection).getByLabelText("بیمه"), { target: { value: "بیمه پایه" } });
  fireEvent.change(within(exclusionSection).getByLabelText("خدمت"), { target: { value: "5" } });
  fireEvent.click(within(exclusionSection).getByRole("button", { name: "ثبت استثنا" }));
  await waitFor(() => expect(apiSaveAccountingExclusion).toHaveBeenCalled());

  fireEvent.click(within(exclusionSection).getByRole("button", { name: "حذف" }));
  expect(window.confirm).toHaveBeenCalled();
  await waitFor(() => expect(apiDeleteAccountingExclusion).toHaveBeenCalledWith(8));
});

test("payroll workspace submits integer amounts and decimal percentages", async () => {
  render(<AccountingPayrollSettings config={CONFIG} onChanged={changed} onError={setError} />);
  fireEvent.change(screen.getByLabelText("کادر درمان"), { target: { value: "1" } });
  fireEvent.change(screen.getByLabelText("پایه صبح"), { target: { value: "550000" } });
  fireEvent.change(screen.getByLabelText("درصد تزریق"), { target: { value: "22.5" } });
  fireEvent.change(screen.getByLabelText("مالیات"), { target: { value: "6" } });
  fireEvent.click(screen.getByRole("button", { name: "ذخیره قرارداد" }));
  await waitFor(() => expect(apiSaveAccountingPayrollSettings).toHaveBeenCalled());
  expect(apiSaveAccountingPayrollSettings).toHaveBeenCalledWith(expect.objectContaining({ staff_id: 1, base_morning: 550000, injection_percent: 22.5, tax_percent: 6 }));
});
