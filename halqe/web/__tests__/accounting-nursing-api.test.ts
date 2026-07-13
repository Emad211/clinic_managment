import {
  apiAddAccountingNursingItems,
  apiCloseAccountingNursingInvoice,
  apiGetAccountingConsumableTariffs,
  apiGetAccountingNursingServices,
  apiGetAccountingShiftStaff,
  apiGetAccountingStaff,
  apiSetAccountingShiftStaff,
  apiSettleAccountingNursingInvoice,
  saveToken,
} from "../src/lib/api";

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

beforeEach(() => {
  localStorageMock.clear();
  saveToken("accounting-nursing-token");
  jest.resetAllMocks();
});

function mockJson(payload: unknown) {
  globalThis.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: async () => payload,
  }) as jest.Mock;
}

test("loads nursing and consumable catalogues with bearer auth", async () => {
  mockJson([{ id: 4, service_name: "تزریق", unit_price: 30000 }]);
  const services = await apiGetAccountingNursingServices();
  expect(services[0].unit_price).toBe(30000);
  let [url, options] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(url).toContain("/accounting/nursing/services");
  expect(options.headers.Authorization).toBe("Bearer accounting-nursing-token");

  mockJson([{ id: 8, name: "گاز", default_price: 25000, category: "supply" }]);
  const consumables = await apiGetAccountingConsumableTariffs("supply");
  expect(consumables[0].name).toBe("گاز");
  [url] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(url).toContain("category=supply");
});

test("loads staff and shift context", async () => {
  mockJson([{ id: 10, full_name: "پرستار تست", staff_type: "nurse" }]);
  await apiGetAccountingStaff("nurse");
  let [url] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(url).toContain("staff_type=nurse");

  mockJson({
    id: 1,
    work_date: "2026-07-13",
    shift: "evening",
    doctor_id: null,
    nurse_id: 10,
    doctor_name: null,
    nurse_name: "پرستار تست",
    updated_at: "2026-07-13T10:00:00+03:30",
  });
  const shift = await apiGetAccountingShiftStaff(42);
  expect(shift?.nurse_id).toBe(10);
  [url] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(url).toContain("/accounting/invoices/42/shift-staff");
});

test("saves shift staff with a PUT request", async () => {
  mockJson({
    id: 1,
    work_date: "2026-07-13",
    shift: "evening",
    doctor_id: 9,
    nurse_id: 10,
    doctor_name: "پزشک تست",
    nurse_name: "پرستار تست",
    updated_at: "2026-07-13T10:00:00+03:30",
  });

  await apiSetAccountingShiftStaff(42, 9, 10);
  const [url, options] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(url).toContain("/accounting/invoices/42/shift-staff");
  expect(options.method).toBe("PUT");
  expect(JSON.parse(options.body)).toEqual({ doctor_id: 9, nurse_id: 10 });
});

test("submits nursing services and consumables atomically", async () => {
  mockJson({
    invoice_id: 42,
    pricing_version: "halqe_visit_nursing_v1",
    injection_ids: [11],
    consumable_ids: [12],
    financials: {
      invoice_id: 42,
      total_amount: 165000,
      paid_amount: 0,
      remaining_amount: 165000,
      all_items_paid: false,
      payment_type: null,
    },
  });

  const payload = {
    services: [{ service_id: 4, quantity: 1 }],
    consumables: [
      {
        name: "گاز",
        category: "supply" as const,
        quantity: 2,
        unit_price: 25000,
        patient_provided: false,
        is_exception: false,
      },
    ],
    notes: "ثبت تست",
  };
  const result = await apiAddAccountingNursingItems(42, payload);
  expect(result.injection_ids).toEqual([11]);
  expect(result.consumable_ids).toEqual([12]);

  const [url, options] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(url).toContain("/accounting/invoices/42/nursing-items");
  expect(options.method).toBe("POST");
  expect(JSON.parse(options.body)).toEqual(payload);
});

test("uses the nursing pricing engine for settlement and close", async () => {
  mockJson({
    invoice_id: 42,
    total_amount: 165000,
    paid_amount: 165000,
    remaining_amount: 0,
    all_items_paid: true,
    payment_type: "card",
  });
  await apiSettleAccountingNursingInvoice(42, "card");
  let [url, options] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(url).toContain("/accounting/invoices/42/nursing/settle-all");
  expect(options.method).toBe("POST");

  mockJson({ id: 42, status: "closed" });
  await apiCloseAccountingNursingInvoice(42);
  [url, options] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(url).toContain("/accounting/invoices/42/nursing/close");
  expect(options.method).toBe("POST");
});
