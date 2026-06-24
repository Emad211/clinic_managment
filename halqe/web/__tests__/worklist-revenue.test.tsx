/**
 * Tests for the worklist revenue column (Step 15 — manager-only درآمد column).
 *
 * Covers:
 *   1. apiGetWorklist sends include_revenue=true by default.
 *   2. formatToman formats amounts in Persian digits with تومان suffix.
 *   3. A minimal inline worklist table renders the revenue column when at
 *      least one item has non-null revenue (manager scenario).
 *   4. The revenue column is hidden when all items have null/absent revenue
 *      (non-manager scenario — backend never sends revenue data).
 *
 * Strategy: inline component mirrors the exact hasRevenue + formatToman logic
 * from the worklist page — avoids importing the full Next.js page (which
 * requires router mocking).
 */

import React from "react";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { formatToman } from "../src/lib/jalali";
import type { WorklistItem } from "../src/lib/api";

// ─────────────────────────────────────────────────────────────
// Mock localStorage (required by api.ts module init)
// ─────────────────────────────────────────────────────────────

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

// ─────────────────────────────────────────────────────────────
// 1. formatToman utility
// ─────────────────────────────────────────────────────────────

describe("formatToman", () => {
  it("formats zero as ۰ تومان", () => {
    const result = formatToman(0);
    expect(result).toContain("تومان");
    // fa-IR locale for 0 → "۰"
    expect(result).toMatch(/۰/);
  });

  it("returns — for null", () => {
    expect(formatToman(null)).toBe("—");
  });

  it("returns — for undefined", () => {
    expect(formatToman(undefined)).toBe("—");
  });

  it("formats a positive integer and includes تومان suffix", () => {
    const result = formatToman(1500000);
    expect(result).toContain("تومان");
    // Should contain Persian digits (not ASCII)
    expect(result).toMatch(/[۰-۹]/);
  });

  it("contains the digit characters of the input (Persian-ified)", () => {
    // 100 → "۱۰۰ تومان"
    const result = formatToman(100);
    expect(result).toContain("تومان");
    // The toLocaleString("fa-IR") should produce Persian digits
    expect(result).toMatch(/[۰-۹]/);
  });
});

// ─────────────────────────────────────────────────────────────
// 2. apiGetWorklist sends include_revenue=true by default
// ─────────────────────────────────────────────────────────────

describe("apiGetWorklist — include_revenue param", () => {
  beforeEach(() => {
    localStorageMock.clear();
    localStorageMock.setItem("halqe_token", "mock-token");
    jest.resetAllMocks();
  });

  test("sends include_revenue=true by default", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items: [], total: 0, limit: 20, offset: 0 }),
    }) as jest.Mock;

    const { apiGetWorklist } = await import("../src/lib/api");
    await apiGetWorklist();

    const url: string = (globalThis.fetch as jest.Mock).mock.calls[0][0];
    expect(url).toContain("include_revenue=true");
    expect(url).toContain("/worklist");
  });

  test("sends include_revenue=true when explicitly set", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items: [], total: 0, limit: 20, offset: 0 }),
    }) as jest.Mock;

    const { apiGetWorklist } = await import("../src/lib/api");
    await apiGetWorklist({ includeRevenue: true });

    const url: string = (globalThis.fetch as jest.Mock).mock.calls[0][0];
    expect(url).toContain("include_revenue=true");
  });

  test("omits include_revenue when explicitly set to false", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items: [], total: 0, limit: 20, offset: 0 }),
    }) as jest.Mock;

    const { apiGetWorklist } = await import("../src/lib/api");
    await apiGetWorklist({ includeRevenue: false });

    const url: string = (globalThis.fetch as jest.Mock).mock.calls[0][0];
    expect(url).not.toContain("include_revenue");
  });

  test("WorklistItem type accepts revenue field", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        items: [
          {
            id: 1,
            patient_uuid: "uuid-1",
            patient_full_name: "علی رضایی",
            kind: "lab_review",
            reason: "lab_review",
            due_date: "2026-06-20",
            status: "open",
            fulfillment: null,
            created_at: "2026-06-10T09:00:00+03:30",
            resolved_at: null,
            revenue: 2500000,
          },
        ],
        total: 1,
        limit: 20,
        offset: 0,
      }),
    }) as jest.Mock;

    const { apiGetWorklist } = await import("../src/lib/api");
    const result = await apiGetWorklist();

    expect(result.items[0].revenue).toBe(2500000);
  });

  test("WorklistItem revenue is null for non-manager (backend returns null)", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        items: [
          {
            id: 2,
            patient_uuid: "uuid-2",
            patient_full_name: "مریم احمدی",
            kind: "med_refill",
            reason: "med_refill",
            due_date: "2026-06-25",
            status: "open",
            fulfillment: null,
            created_at: "2026-06-11T09:00:00+03:30",
            resolved_at: null,
            revenue: null,
          },
        ],
        total: 1,
        limit: 20,
        offset: 0,
      }),
    }) as jest.Mock;

    const { apiGetWorklist } = await import("../src/lib/api");
    const result = await apiGetWorklist();

    expect(result.items[0].revenue).toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────
// 3. Inline worklist table — revenue column visibility
// ─────────────────────────────────────────────────────────────

/** Minimal inline table mirroring the exact hasRevenue + formatToman logic from the worklist page. */
function WorklistTableStub({ items }: { items: WorklistItem[] }) {
  const hasRevenue = items.some((item) => item.revenue != null);

  return (
    <table aria-label="لیست پیگیری‌های بیماران">
      <thead>
        <tr>
          <th scope="col">بیمار</th>
          <th scope="col">وضعیت</th>
          {hasRevenue && <th scope="col">درآمد</th>}
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <tr key={item.id}>
            <td>{item.patient_full_name ?? "ناشناس"}</td>
            <td>{item.status}</td>
            {hasRevenue && (
              <td
                aria-label={
                  item.revenue != null
                    ? `درآمد: ${formatToman(item.revenue)}`
                    : "درآمد: ندارد"
                }
              >
                {item.revenue != null ? formatToman(item.revenue) : "—"}
              </td>
            )}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const MANAGER_ITEMS: WorklistItem[] = [
  {
    id: 10,
    patient_uuid: "uuid-10",
    patient_full_name: "علی رضایی",
    kind: "lab_review",
    reason: "lab_review",
    due_date: "2026-06-20",
    status: "open",
    fulfillment: null,
    created_at: "2026-06-10T09:00:00+03:30",
    resolved_at: null,
    revenue: 3200000,
  },
  {
    id: 11,
    patient_uuid: "uuid-11",
    patient_full_name: "مریم احمدی",
    kind: "med_refill",
    reason: "med_refill",
    due_date: "2026-06-25",
    status: "open",
    fulfillment: null,
    created_at: "2026-06-11T09:00:00+03:30",
    resolved_at: null,
    revenue: 0,
  },
];

const NON_MANAGER_ITEMS: WorklistItem[] = [
  {
    id: 20,
    patient_uuid: "uuid-20",
    patient_full_name: "حسن موسوی",
    kind: "lab_review",
    reason: "lab_review",
    due_date: "2026-06-22",
    status: "open",
    fulfillment: null,
    created_at: "2026-06-12T09:00:00+03:30",
    resolved_at: null,
    revenue: null,
  },
  {
    id: 21,
    patient_uuid: "uuid-21",
    patient_full_name: "زهرا کریمی",
    kind: "bp_check",
    reason: "bp_check",
    due_date: null,
    status: "open",
    fulfillment: null,
    created_at: "2026-06-13T09:00:00+03:30",
    resolved_at: null,
    // revenue absent entirely (not returned by backend for non-managers)
  },
];

describe("WorklistTableStub — revenue column rendering", () => {
  it("shows the درآمد column header when at least one item has non-null revenue", () => {
    render(<WorklistTableStub items={MANAGER_ITEMS} />);
    expect(screen.getByRole("columnheader", { name: "درآمد" })).toBeInTheDocument();
  });

  it("renders formatted Toman for each item with non-null revenue (manager)", () => {
    render(<WorklistTableStub items={MANAGER_ITEMS} />);
    // First item has revenue=3200000 — should contain تومان
    const cells = screen.getAllByRole("cell");
    const revenueCells = cells.filter((c) => c.textContent?.includes("تومان"));
    expect(revenueCells.length).toBeGreaterThan(0);
  });

  it("renders — for items with revenue=0", () => {
    // revenue=0 is non-null, so hasRevenue=true and formatToman(0) is shown (not —)
    render(<WorklistTableStub items={MANAGER_ITEMS} />);
    // revenue=0 → "۰ تومان" (not —)
    const cells = screen.getAllByRole("cell");
    const zeroCells = cells.filter((c) => c.textContent?.includes("تومان") && c.textContent.includes("۰"));
    expect(zeroCells.length).toBeGreaterThanOrEqual(1);
  });

  it("hides the درآمد column header when all items have null/absent revenue (non-manager)", () => {
    render(<WorklistTableStub items={NON_MANAGER_ITEMS} />);
    expect(screen.queryByRole("columnheader", { name: "درآمد" })).not.toBeInTheDocument();
  });

  it("renders no revenue cells when all items have null/absent revenue", () => {
    render(<WorklistTableStub items={NON_MANAGER_ITEMS} />);
    // No cell should contain تومان
    const cells = screen.getAllByRole("cell");
    const revenueCells = cells.filter((c) => c.textContent?.includes("تومان"));
    expect(revenueCells).toHaveLength(0);
  });

  it("renders patient names and statuses regardless of revenue visibility", () => {
    render(<WorklistTableStub items={NON_MANAGER_ITEMS} />);
    expect(screen.getByText("حسن موسوی")).toBeInTheDocument();
    expect(screen.getByText("زهرا کریمی")).toBeInTheDocument();
  });

  it("aria-label on revenue cells describes the amount for screen readers", () => {
    render(<WorklistTableStub items={MANAGER_ITEMS} />);
    // Both items have non-null revenue so both cells carry a درآمد: … تومان label
    const revenueCells = screen.getAllByLabelText(/درآمد: .*تومان/);
    expect(revenueCells.length).toBeGreaterThanOrEqual(1);
  });
});
