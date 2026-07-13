import {
  apiGetAccountingInvoiceFinancials,
  apiSetAccountingItemPayment,
  apiSettleAccountingInvoice,
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

const SUMMARY = {
  invoice_id: 42,
  total_amount: 85000,
  paid_amount: 85000,
  remaining_amount: 0,
  all_items_paid: true,
  payment_type: "card" as const,
};

beforeEach(() => {
  localStorageMock.clear();
  saveToken("accounting-token");
  jest.resetAllMocks();
});

test("gets invoice financials", async () => {
  globalThis.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: async () => SUMMARY,
  }) as jest.Mock;

  const result = await apiGetAccountingInvoiceFinancials(42);
  expect(result).toEqual(SUMMARY);
  const [url, options] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(url).toContain("/accounting/invoices/42/financials");
  expect(options.headers.Authorization).toBe("Bearer accounting-token");
});

test("settles all items with the selected method", async () => {
  globalThis.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: async () => SUMMARY,
  }) as jest.Mock;

  await apiSettleAccountingInvoice(42, "card");
  const [url, options] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(url).toContain("/accounting/invoices/42/settle-all");
  expect(options.method).toBe("POST");
  expect(JSON.parse(options.body)).toEqual({ payment_type: "card" });
});

test("can reverse an individual visit payment", async () => {
  globalThis.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: async () => ({
      ...SUMMARY,
      paid_amount: 0,
      remaining_amount: 85000,
      all_items_paid: false,
      payment_type: null,
    }),
  }) as jest.Mock;

  await apiSetAccountingItemPayment(42, "visit", 9, null, false);
  const [url, options] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(url).toContain("/accounting/invoices/42/items/visit/9/payment");
  expect(options.method).toBe("POST");
  expect(JSON.parse(options.body)).toEqual({
    payment_type: null,
    is_paid: false,
  });
});
