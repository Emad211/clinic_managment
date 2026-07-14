import {
  apiDeleteAccountingExclusion,
  apiGetAccountingAdminConfiguration,
  apiSaveAccountingCatalogItem,
  apiSaveAccountingExclusion,
  apiSaveAccountingInsuranceScheme,
  apiSaveAccountingPayrollSettings,
  apiSaveAccountingStaff,
  apiSaveAccountingVisitTariff,
} from "../src/lib/api/accounting-admin";
import { saveToken } from "../src/lib/api";

const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = value; },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { store = {}; },
  };
})();

Object.defineProperty(globalThis, "localStorage", {
  value: localStorageMock,
  writable: true,
});

function mockJson(payload: unknown) {
  globalThis.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => payload,
  }) as jest.Mock;
}

function request(index = 0) {
  const [url, options] = (globalThis.fetch as jest.Mock).mock.calls[index];
  return {
    url: String(url),
    method: options.method ?? "GET",
    body: options.body ? JSON.parse(options.body) : undefined,
    authorization: options.headers.Authorization,
  };
}

beforeEach(() => {
  localStorageMock.clear();
  saveToken("accounting-admin-token");
  jest.resetAllMocks();
});

test("loads the complete manager configuration with bearer auth", async () => {
  mockJson({
    staff: [], insurance_schemes: [], visit_tariffs: [],
    catalogs: { nursing: [], procedure: [], consumable: [] },
    exclusions: [], payroll_settings: [],
  });
  await apiGetAccountingAdminConfiguration();
  expect(request()).toEqual({
    url: expect.stringContaining("/accounting/admin/config"),
    method: "GET",
    body: undefined,
    authorization: "Bearer accounting-admin-token",
  });
});

test("staff, insurer and tariff mutations keep complete typed payloads", async () => {
  mockJson({ id: 1 });
  await apiSaveAccountingStaff({
    id: null,
    full_name: "دکتر تست",
    staff_type: "doctor",
    is_active: true,
  });
  await apiSaveAccountingInsuranceScheme({
    id: null,
    code: "base-test",
    name: "بیمه تست",
    is_base: true,
    is_supplementary: false,
    is_active: true,
  });
  await apiSaveAccountingVisitTariff({
    id: null,
    insurance_type: "بیمه تست",
    insurance_scheme_id: 1,
    tariff_price: 125000,
    nursing_tariff: 20000,
    nursing_covers: true,
    is_active: true,
    is_supplementary: false,
    is_base_tariff: true,
  });

  expect(request(0)).toEqual(expect.objectContaining({
    url: expect.stringContaining("/accounting/admin/staff"), method: "POST",
  }));
  expect(request(0).body).toMatchObject({ full_name: "دکتر تست", staff_type: "doctor" });
  expect(request(1).url).toContain("/accounting/admin/insurance-schemes");
  expect(request(2).body).toEqual({
    id: null,
    insurance_type: "بیمه تست",
    insurance_scheme_id: 1,
    tariff_price: 125000,
    nursing_tariff: 20000,
    nursing_covers: true,
    is_active: true,
    is_supplementary: false,
    is_base_tariff: true,
  });
});

test("catalog paths are separated and exclusion delete is explicit", async () => {
  mockJson({ id: 4 });
  await apiSaveAccountingCatalogItem("nursing", {
    id: null, name: "تزریق", price: 40000, category: null, is_active: true,
  });
  await apiSaveAccountingCatalogItem("consumable", {
    id: null, name: "گاز", price: 12000, category: "supply", is_active: true,
  });
  await apiSaveAccountingExclusion({
    id: null,
    insurance_type: "بیمه تست",
    nursing_service_id: 4,
    note: "پرداخت بیمار",
  });
  await apiDeleteAccountingExclusion(19);

  expect(request(0).url).toContain("/accounting/admin/catalogs/nursing");
  expect(request(1).url).toContain("/accounting/admin/catalogs/consumable");
  expect(request(2).url).toContain("/accounting/admin/exclusions");
  expect(request(3)).toEqual(expect.objectContaining({
    url: expect.stringContaining("/accounting/admin/exclusions/19"),
    method: "DELETE",
  }));
});

test("payroll sends integer Toman amounts and decimal percentages", async () => {
  mockJson({ id: 7 });
  await apiSaveAccountingPayrollSettings({
    staff_id: 3,
    base_morning: 500000,
    base_evening: 600000,
    base_night: 750000,
    visit_fee: 25000,
    injection_percent: 20.5,
    procedure_percent: 30,
    tax_percent: 5,
    nursing_percent: 15,
    nurse_procedure_percent: 25,
  });
  expect(request().url).toContain("/accounting/admin/payroll-settings");
  expect(request().body).toEqual({
    staff_id: 3,
    base_morning: 500000,
    base_evening: 600000,
    base_night: 750000,
    visit_fee: 25000,
    injection_percent: 20.5,
    procedure_percent: 30,
    tax_percent: 5,
    nursing_percent: 15,
    nurse_procedure_percent: 25,
  });
});
