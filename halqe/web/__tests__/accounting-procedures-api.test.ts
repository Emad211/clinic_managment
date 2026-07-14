import {
  apiAddAccountingProcedureItems,
  apiCloseAccountingProcedureInvoice,
  apiGetAccountingProcedureTariffs,
  apiSetAccountingProcedureItemPayment,
  apiSettleAccountingProcedureInvoice,
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

function mockJson(payload: unknown) {
  globalThis.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: async () => payload,
  }) as jest.Mock;
}

beforeEach(() => {
  localStorageMock.clear();
  saveToken("procedure-token");
  jest.resetAllMocks();
});

test("loads procedure tariffs", async () => {
  mockJson([{ id: 1, name: "پانسمان", unit_price: 45000 }]);
  const rows = await apiGetAccountingProcedureTariffs();
  expect(rows[0]).toEqual({ id: 1, name: "پانسمان", unit_price: 45000 });
  const [url, options] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(url).toContain("/accounting/procedures/tariffs");
  expect(options.headers.Authorization).toBe("Bearer procedure-token");
});

test("submits catalogue and manual procedure entries", async () => {
  mockJson({
    invoice_id: 42,
    pricing_version: "halqe_visit_procedure_v1",
    procedure_ids: [11, 12],
    financials: {
      invoice_id: 42,
      total_amount: 235000,
      paid_amount: 0,
      remaining_amount: 235000,
      all_items_paid: false,
      payment_type: null,
    },
  });
  const procedures = [
    {
      tariff_id: 1,
      quantity: 1,
      performer_type: "nurse" as const,
    },
    {
      tariff_id: null,
      name: "پروسیجر دستی",
      unit_price: 150000,
      quantity: 1,
      performer_type: "doctor" as const,
    },
  ];
  const result = await apiAddAccountingProcedureItems(42, procedures, "یادداشت");
  expect(result.procedure_ids).toEqual([11, 12]);
  const [url, options] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(url).toContain("/accounting/invoices/42/procedure-items");
  expect(options.method).toBe("POST");
  expect(JSON.parse(options.body)).toEqual({ procedures, notes: "یادداشت" });
});

test("uses procedure-specific settlement, item payment and close endpoints", async () => {
  const summary = {
    invoice_id: 42,
    total_amount: 235000,
    paid_amount: 235000,
    remaining_amount: 0,
    all_items_paid: true,
    payment_type: "card" as const,
  };
  mockJson(summary);
  await apiSettleAccountingProcedureInvoice(42, "card");
  let [url, options] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(url).toContain("/accounting/invoices/42/procedure/settle-all");
  expect(options.method).toBe("POST");

  mockJson(summary);
  await apiSetAccountingProcedureItemPayment(
    42,
    "procedure",
    9,
    "cash",
    true,
  );
  [url, options] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(url).toContain("/accounting/invoices/42/procedure/items/procedure/9/payment");
  expect(JSON.parse(options.body)).toEqual({
    payment_type: "cash",
    is_paid: true,
  });

  mockJson({ id: 42, status: "closed" });
  await apiCloseAccountingProcedureInvoice(42);
  [url, options] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(url).toContain("/accounting/invoices/42/procedure/close");
  expect(options.method).toBe("POST");
});
