/** Accounting API client contract tests. */

const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => {
      store[key] = value;
    },
    removeItem: (key: string) => {
      delete store[key];
    },
    clear: () => {
      store = {};
    },
  };
})();

Object.defineProperty(globalThis, "localStorage", {
  value: localStorageMock,
  writable: true,
});

const INVOICE = {
  id: 42,
  tenant_id: 1,
  patient_id: 7,
  patient_uuid: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
  patient_full_name: "مریم حسابی",
  national_id: "2170415981",
  phone_number: "09121111111",
  status: "open" as const,
  pricing_version: "halqe_visit_v1",
  insurance_type: "تامین اجتماعی",
  supplementary_insurance: null,
  total_amount: 85000,
  work_date: "2026-07-13",
  shift: "morning",
  opened_at: "2026-07-13T08:00:00+03:30",
  closed_at: null,
  opened_by: "reception_test",
  opened_by_name: "پذیرش تست",
  closed_by: null,
  closed_by_name: null,
  visit_id: 9,
  visit_price: 85000,
};

beforeEach(() => {
  localStorageMock.clear();
  localStorageMock.setItem("halqe_token", "accounting-test-token");
  jest.resetAllMocks();
});

test("lists open accounting invoices with bearer auth", async () => {
  globalThis.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ items: [INVOICE], total: 1, limit: 50, offset: 0 }),
  }) as jest.Mock;

  const { apiGetOpenAccountingInvoices } = await import("../src/lib/api");
  const result = await apiGetOpenAccountingInvoices(50, 0);

  expect(result.total).toBe(1);
  const [url, options] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(url).toContain("/accounting/invoices/open");
  expect(url).toContain("limit=50");
  expect(options.headers.Authorization).toBe("Bearer accounting-test-token");
});

test("opens a visit invoice using the typed JSON contract", async () => {
  globalThis.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: async () => INVOICE,
  }) as jest.Mock;

  const { apiOpenVisitInvoice } = await import("../src/lib/api");
  const result = await apiOpenVisitInvoice({
    patient: {
      name: "مریم",
      family_name: "حسابی",
      national_id: "2170415981",
      phone_number: "09121111111",
    },
    insurance_type: "تامین اجتماعی",
  });

  expect(result.pricing_version).toBe("halqe_visit_v1");
  const [url, options] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(url).toContain("/accounting/invoices/visit");
  expect(options.method).toBe("POST");
  expect(JSON.parse(options.body)).toMatchObject({
    insurance_type: "تامین اجتماعی",
    patient: { national_id: "2170415981" },
  });
});

test("closes the requested invoice", async () => {
  globalThis.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ ...INVOICE, status: "closed" }),
  }) as jest.Mock;

  const { apiCloseAccountingInvoice } = await import("../src/lib/api");
  await apiCloseAccountingInvoice(42);

  const [url, options] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(url).toContain("/accounting/invoices/42/close");
  expect(options.method).toBe("POST");
});

test("encodes accounting patient search parameters", async () => {
  globalThis.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: async () => [],
  }) as jest.Mock;

  const { apiSearchAccountingPatients } = await import("../src/lib/api");
  await apiSearchAccountingPatients("مریم رضایی", 10);

  const [url] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(url).toContain("/accounting/patients/search");
  expect(url).toContain("q=%D9%85%D8%B1%DB%8C%D9%85+%D8%B1%D8%B6%D8%A7%DB%8C%DB%8C");
  expect(url).toContain("limit=10");
});
