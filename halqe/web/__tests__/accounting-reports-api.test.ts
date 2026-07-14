import {
  apiGetAccountingInvoiceReport,
  apiGetAccountingReportsOverview,
  apiGetAccountingServiceReport,
} from "../src/lib/api/accounting-reports";
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
  saveToken("accounting-reports-token");
  jest.resetAllMocks();
  globalThis.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ rows: [], summary: {}, daily: [] }),
  }) as jest.Mock;
});

test("overview sends exact ISO range and bearer auth", async () => {
  await apiGetAccountingReportsOverview({
    date_from: "2026-07-01",
    date_to: "2026-07-07",
  });
  const [url, options] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(url).toContain("/accounting/reports/overview");
  expect(url).toContain("date_from=2026-07-01");
  expect(url).toContain("date_to=2026-07-07");
  expect(options.headers.Authorization).toBe("Bearer accounting-reports-token");
});

test("invoice filters are encoded and empty filters are omitted", async () => {
  await apiGetAccountingInvoiceReport({
    date_from: "2026-07-01",
    date_to: "2026-07-07",
    status: "closed",
    insurance_type: "بیمه پایه",
    reception_user: "reception-a",
    service_type: "",
    limit: 500,
  });
  const [url] = (globalThis.fetch as jest.Mock).mock.calls[0];
  const parsed = new URL(String(url), "http://localhost");
  expect(parsed.pathname).toContain("/accounting/reports/invoices");
  expect(Object.fromEntries(parsed.searchParams)).toEqual({
    date_from: "2026-07-01",
    date_to: "2026-07-07",
    status: "closed",
    insurance_type: "بیمه پایه",
    reception_user: "reception-a",
    limit: "500",
  });
});

test("service report preserves type, shift and staff filters", async () => {
  await apiGetAccountingServiceReport({
    date_from: "2026-07-01",
    date_to: "2026-07-07",
    service_type: "procedure",
    shift: "night",
    staff_id: 12,
    limit: 700,
  });
  const [url] = (globalThis.fetch as jest.Mock).mock.calls[0];
  const parsed = new URL(String(url), "http://localhost");
  expect(Object.fromEntries(parsed.searchParams)).toEqual({
    date_from: "2026-07-01",
    date_to: "2026-07-07",
    service_type: "procedure",
    shift: "night",
    staff_id: "12",
    limit: "700",
  });
});
