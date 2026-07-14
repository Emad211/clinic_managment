import { apiGetAccountingPayrollReport } from "../src/lib/api/accounting-payroll-report";
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
  saveToken("payroll-report-token");
  jest.resetAllMocks();
  globalThis.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ summary: {}, rows: [] }),
  }) as jest.Mock;
});

test("payroll request carries range, staff type and shift", async () => {
  await apiGetAccountingPayrollReport({
    date_from: "2026-07-01",
    date_to: "2026-07-31",
    staff_type: "doctor",
    shift: "morning",
    staff_id: 9,
  });
  const [url, options] = (globalThis.fetch as jest.Mock).mock.calls[0];
  const parsed = new URL(String(url), "http://localhost");
  expect(parsed.pathname).toContain("/accounting/reports/payroll");
  expect(Object.fromEntries(parsed.searchParams)).toEqual({
    date_from: "2026-07-01",
    date_to: "2026-07-31",
    staff_type: "doctor",
    shift: "morning",
    staff_id: "9",
  });
  expect(options.headers.Authorization).toBe("Bearer payroll-report-token");
});
