/**
 * Worklist page — real-component security guard (Step 32 / شکاف ۲).
 *
 * Renders the ACTUAL WorklistPage component (not a mirror stub) to lock down
 * the revenue-column visibility gate on the live DOM.  Covers:
 *
 *   1. Manager scenario   — apiGetWorklist returns items with non-null revenue
 *      → سرستون «درآمد» و مقادیر در DOM هست.
 *   2. Staff scenario     — all revenue fields are null/absent
 *      → سرستون «درآمد» در DOM نیست (گیت امنیتی اصلی).
 *   3. Mark-done (اختیاری) — دکمهٔ «انجام شد» روی صفحهٔ واقعی trigger می‌شود.
 *
 * Mocks:
 *   - @/lib/api       : apiGetWorklist, apiMarkDone (no real HTTP)
 *   - @/hooks/useAuth : ready=true, logout=jest.fn() (bypasses router/token)
 *   - next/navigation : usePathname → "/worklist" (no router needed)
 *   - next/link       : simple <a> anchor (avoids Next.js Link internals)
 *
 * The existing formatToman + include_revenue + WorklistTableStub tests in
 * worklist-revenue.test.tsx remain untouched — this file adds a second layer.
 */

import React from "react";
import {
  render,
  screen,
  waitFor,
  fireEvent,
  act,
} from "@testing-library/react";
import "@testing-library/jest-dom";

// ─────────────────────────────────────────────────────────────
// localStorage mock (api.ts reads TOKEN_KEY on module import)
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
// Module mocks — must be declared before any imports that use them
// ─────────────────────────────────────────────────────────────

// Mock @/lib/api so no real HTTP is made
jest.mock("@/lib/api", () => ({
  apiGetWorklist: jest.fn(),
  apiMarkDone: jest.fn(),
  // Nav (rendered un-stubbed here) reads the role claim in an effect.
  getRole: jest.fn(() => "manager"),
  ApiError: class ApiError extends Error {
    status: number;
    code: string | null;
    constructor(status: number, message: string, code: string | null = null) {
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.code = code;
    }
  },
}));

// Mock useAuth — always ready, exposes a controllable logout spy
const mockLogout = jest.fn();
jest.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ ready: true, logout: mockLogout }),
}));

// Mock next/navigation — usePathname returns a fixed string
jest.mock("next/navigation", () => ({
  usePathname: () => "/worklist",
}));

// Mock next/link — renders a plain <a> so Link hrefs are testable
jest.mock("next/link", () => {
  const MockLink = ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: React.ReactNode;
    [key: string]: unknown;
  }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  );
  MockLink.displayName = "MockLink";
  return MockLink;
});

// Silence CSS module import errors (Jest jsdom doesn't parse .module.css)
jest.mock("./worklist.module.css", () => ({}), { virtual: true });

// ─────────────────────────────────────────────────────────────
// Import page AFTER mocks are wired
// ─────────────────────────────────────────────────────────────

import WorklistPage from "@/app/worklist/page";
import { apiGetWorklist, apiMarkDone } from "@/lib/api";

// ─────────────────────────────────────────────────────────────
// Fixtures
// ─────────────────────────────────────────────────────────────

const MANAGER_RESPONSE = {
  items: [
    {
      id: 10,
      patient_uuid: "uuid-10",
      patient_full_name: "علی رضایی",
      kind: "lab_review",
      reason: "بررسی آزمایشگاه",
      due_date: "2026-06-20",
      status: "open",
      fulfillment: null,
      created_at: "2026-06-10T09:00:00+03:30",
      resolved_at: null,
      revenue: 3200000,        // non-null → manager gate triggered
    },
    {
      id: 11,
      patient_uuid: "uuid-11",
      patient_full_name: "مریم احمدی",
      kind: "med_refill",
      reason: "تجدید نسخه",
      due_date: "2026-06-25",
      status: "open",
      fulfillment: null,
      created_at: "2026-06-11T09:00:00+03:30",
      resolved_at: null,
      revenue: 1500000,        // non-null
    },
  ],
  total: 2,
  limit: 20,
  offset: 0,
};

const STAFF_RESPONSE = {
  items: [
    {
      id: 20,
      patient_uuid: "uuid-20",
      patient_full_name: "حسن موسوی",
      kind: "lab_review",
      reason: "بررسی آزمایشگاه",
      due_date: "2026-06-22",
      status: "open",
      fulfillment: null,
      created_at: "2026-06-12T09:00:00+03:30",
      resolved_at: null,
      revenue: null,           // null → backend enforced: staff never gets revenue
    },
    {
      id: 21,
      patient_uuid: "uuid-21",
      patient_full_name: "زهرا کریمی",
      kind: "bp_check",
      reason: "کنترل فشار",
      due_date: null,
      status: "open",
      fulfillment: null,
      created_at: "2026-06-13T09:00:00+03:30",
      resolved_at: null,
      // revenue absent entirely (backend omits it for non-managers)
    },
  ],
  total: 2,
  limit: 20,
  offset: 0,
};

// ─────────────────────────────────────────────────────────────
// Helper: render the page and wait for loading spinner to disappear
// ─────────────────────────────────────────────────────────────

async function renderWorklistAndWait() {
  await act(async () => {
    render(<WorklistPage />);
  });
  // Wait until loading state resolves (spinner / «در حال بارگذاری» disappears)
  await waitFor(() => {
    expect(screen.queryByText("در حال بارگذاری…")).not.toBeInTheDocument();
  });
}

// ─────────────────────────────────────────────────────────────
// Before each: reset mocks and set a token in localStorage
// ─────────────────────────────────────────────────────────────

beforeEach(() => {
  jest.clearAllMocks();
  localStorageMock.clear();
  // Put a non-expiring dummy token so api.ts doesn't evict it
  // (we mock useAuth so getToken is only called inside api.ts fetch, not by the page directly)
  localStorageMock.setItem("halqe_token", "test-token");
});

// ─────────────────────────────────────────────────────────────
// سناریوی ۱: مدیر — revenue non-null → ستون درآمد در DOM
// ─────────────────────────────────────────────────────────────

describe("WorklistPage — manager scenario (revenue visible)", () => {
  beforeEach(() => {
    (apiGetWorklist as jest.Mock).mockResolvedValue(MANAGER_RESPONSE);
  });

  it("renders the «درآمد» column header when backend returns non-null revenue", async () => {
    await renderWorklistAndWait();

    const header = screen.queryByRole("columnheader", { name: "درآمد" });
    expect(header).toBeInTheDocument();
  });

  it("renders formatted Toman amounts in revenue cells", async () => {
    await renderWorklistAndWait();

    // At least one cell should contain «تومان» (formatToman output)
    const cells = screen.getAllByRole("cell");
    const revenueCells = cells.filter((c) => c.textContent?.includes("تومان"));
    expect(revenueCells.length).toBeGreaterThan(0);
  });

  it("renders patient names in the table", async () => {
    await renderWorklistAndWait();

    expect(screen.getByText("علی رضایی")).toBeInTheDocument();
    expect(screen.getByText("مریم احمدی")).toBeInTheDocument();
  });

  it("renders mark-done buttons for open items", async () => {
    await renderWorklistAndWait();

    const doneBtns = screen.getAllByRole("button", { name: /انجام شد/ });
    expect(doneBtns.length).toBeGreaterThan(0);
  });
});

// ─────────────────────────────────────────────────────────────
// سناریوی ۲: staff — revenue null/absent → ستون درآمد در DOM نیست
// این هستهٔ گیت امنیتی است
// ─────────────────────────────────────────────────────────────

describe("WorklistPage — staff scenario (revenue hidden)", () => {
  beforeEach(() => {
    (apiGetWorklist as jest.Mock).mockResolvedValue(STAFF_RESPONSE);
  });

  it("does NOT render the «درآمد» column header when all revenue fields are null/absent", async () => {
    await renderWorklistAndWait();

    // The security gate: staff must never see the revenue column
    const header = screen.queryByRole("columnheader", { name: "درآمد" });
    expect(header).not.toBeInTheDocument();
  });

  it("renders no تومان amounts in any cell", async () => {
    await renderWorklistAndWait();

    const cells = screen.getAllByRole("cell");
    const revenueCells = cells.filter((c) => c.textContent?.includes("تومان"));
    expect(revenueCells).toHaveLength(0);
  });

  it("still renders patient names and open worklist (staff sees non-revenue data)", async () => {
    await renderWorklistAndWait();

    expect(screen.getByText("حسن موسوی")).toBeInTheDocument();
    expect(screen.getByText("زهرا کریمی")).toBeInTheDocument();
  });

  it("still shows mark-done buttons for staff (worklist actions remain available)", async () => {
    await renderWorklistAndWait();

    const doneBtns = screen.getAllByRole("button", { name: /انجام شد/ });
    expect(doneBtns.length).toBeGreaterThan(0);
  });
});

// ─────────────────────────────────────────────────────────────
// سناریوی ۳ (اختیاری): mark-done روی صفحهٔ واقعی
// ─────────────────────────────────────────────────────────────

describe("WorklistPage — mark-done action", () => {
  beforeEach(() => {
    (apiGetWorklist as jest.Mock).mockResolvedValue(MANAGER_RESPONSE);
    (apiMarkDone as jest.Mock).mockResolvedValue({
      id: 10,
      patient_link_id: 1,
      tenant_id: 1,
      reason: "بررسی آزمایشگاه",
      detail: null,
      due_date: "2026-06-20",
      status: "done",
      fulfillment: null,
      source_rule: null,
      source_event: null,
      created_at: "2026-06-10T09:00:00+03:30",
      resolved_at: "2026-06-25T10:00:00+03:30",
    });
  });

  it("calls apiMarkDone with the correct task id when «انجام شد» is clicked", async () => {
    await renderWorklistAndWait();

    // Click the first mark-done button (task id=10 — «علی رضایی»)
    const doneBtns = screen.getAllByRole("button", { name: /انجام شد/ });
    await act(async () => {
      fireEvent.click(doneBtns[0]);
    });

    expect(apiMarkDone).toHaveBeenCalledTimes(1);
    expect(apiMarkDone).toHaveBeenCalledWith(10);
  });

  it("optimistically disables the button while the request is in flight", async () => {
    // Make apiMarkDone hang so we can inspect the loading state
    let resolve!: () => void;
    (apiMarkDone as jest.Mock).mockImplementation(
      () =>
        new Promise<void>((res) => {
          resolve = res;
        }),
    );

    await renderWorklistAndWait();

    const doneBtns = screen.getAllByRole("button", { name: /انجام شد/ });
    fireEvent.click(doneBtns[0]);

    // During the in-flight period, the button shows «…» and is disabled
    await waitFor(() => {
      expect(doneBtns[0]).toBeDisabled();
    });

    // Resolve to clean up
    await act(async () => {
      resolve();
    });
  });
});
