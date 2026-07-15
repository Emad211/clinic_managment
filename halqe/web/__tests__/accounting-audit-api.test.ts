import { apiGetAccountingAuditLogs } from "../src/lib/api/accounting-audit";
import { saveToken } from "../src/lib/api/_core";

const storage = (() => {
  let data: Record<string, string> = {};
  return {
    getItem: (key: string) => data[key] ?? null,
    setItem: (key: string, value: string) => { data[key] = value; },
    removeItem: (key: string) => { delete data[key]; },
    clear: () => { data = {}; },
  };
})();

Object.defineProperty(globalThis, "localStorage", { value: storage, writable: true });

beforeEach(() => {
  storage.clear();
  saveToken("accounting-audit-token");
  jest.resetAllMocks();
  globalThis.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ rows: [], total: 0, total_pages: 0 }),
  }) as jest.Mock;
});

test("audit client sends all supported filters and bearer auth", async () => {
  await apiGetAccountingAuditLogs({
    date_from: "2099-01-01",
    date_to: "2099-01-31",
    page: 3,
    page_size: 25,
    user_id: 12,
    action_type: "item_payment_set",
    action_category: "invoice",
    invoice_id: 45,
    patient_id: 78,
    search_text: "بیمار آلفا",
  });
  const [url, options] = (globalThis.fetch as jest.Mock).mock.calls[0];
  const parsed = new URL(String(url), "http://localhost");
  expect(parsed.pathname).toContain("/accounting/audit/logs");
  expect(Object.fromEntries(parsed.searchParams)).toEqual({
    date_from: "2099-01-01",
    date_to: "2099-01-31",
    page: "3",
    page_size: "25",
    user_id: "12",
    action_type: "item_payment_set",
    action_category: "invoice",
    invoice_id: "45",
    patient_id: "78",
    search_text: "بیمار آلفا",
  });
  expect(options.headers.Authorization).toBe("Bearer accounting-audit-token");
});

test("audit client omits empty and null filters", async () => {
  await apiGetAccountingAuditLogs({
    date_from: "2099-01-01",
    date_to: "2099-01-02",
    user_id: null,
    action_type: "",
    action_category: "",
    invoice_id: null,
    patient_id: null,
    search_text: "",
  });
  const [url] = (globalThis.fetch as jest.Mock).mock.calls[0];
  const parsed = new URL(String(url), "http://localhost");
  expect(Object.fromEntries(parsed.searchParams)).toEqual({
    date_from: "2099-01-01",
    date_to: "2099-01-02",
  });
});
