/**
 * Worklist page — overdue marker (MVP step 87 / U4, triage-safety gap).
 *
 * Renders the ACTUAL WorklistPage and asserts the «سررسید گذشته» (overdue)
 * marker appears ONLY on still-open tasks whose due_date is in the past
 * (Tehran), and NOT on:
 *   - open tasks with a future due_date, or
 *   - done/dismissed tasks even when their due_date is in the past.
 *
 * Deterministic without mocking the clock: we use fixed past (2020-01-01) and
 * far-future (2999-12-31) dates, which straddle "today" for any realistic run.
 *
 * Mock pattern reused from worklist-page.test.tsx (incl. getRole, since the page
 * renders the real Nav which reads the role claim).
 */

import React from "react";
import { render, screen, waitFor, act } from "@testing-library/react";
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
// Module mocks — declared before any imports that use them
// ─────────────────────────────────────────────────────────────

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

const mockLogout = jest.fn();
jest.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ ready: true, logout: mockLogout }),
}));

jest.mock("next/navigation", () => ({
  usePathname: () => "/worklist",
}));

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

jest.mock("./worklist.module.css", () => ({}), { virtual: true });

// ─────────────────────────────────────────────────────────────
// Import page + helper AFTER mocks are wired
// ─────────────────────────────────────────────────────────────

import WorklistPage from "@/app/worklist/page";
import { apiGetWorklist } from "@/lib/api";
import { todayTehranISO } from "@/lib/jalali";

// ─────────────────────────────────────────────────────────────
// Fixtures — fixed past / future dates make the test deterministic
// ─────────────────────────────────────────────────────────────

const PAST = "2020-01-01"; // definitely before today
const FUTURE = "2999-12-31"; // definitely after today

const RESPONSE = {
  items: [
    {
      id: 1,
      patient_uuid: "uuid-1",
      patient_full_name: "بیمارِ سررسیدگذشته",
      kind: "lab_review",
      reason: "بررسی آزمایشگاه",
      due_date: PAST, // open + past → overdue
      status: "open",
      fulfillment: null,
      created_at: "2020-01-01T09:00:00+03:30",
      resolved_at: null,
    },
    {
      id: 2,
      patient_uuid: "uuid-2",
      patient_full_name: "بیمارِ آینده",
      kind: "med_refill",
      reason: "تجدید نسخه",
      due_date: FUTURE, // open + future → NOT overdue
      status: "open",
      fulfillment: null,
      created_at: "2026-06-11T09:00:00+03:30",
      resolved_at: null,
    },
    {
      id: 3,
      patient_uuid: "uuid-3",
      patient_full_name: "بیمارِ انجام‌شده",
      kind: "bp_check",
      reason: "کنترل فشار",
      due_date: PAST, // past BUT done → NOT overdue
      status: "done",
      fulfillment: null,
      created_at: "2020-01-01T09:00:00+03:30",
      resolved_at: "2020-02-01T09:00:00+03:30",
    },
  ],
  total: 3,
  limit: 20,
  offset: 0,
};

async function renderWorklistAndWait() {
  await act(async () => {
    render(<WorklistPage />);
  });
  await waitFor(() => {
    expect(screen.queryByText("در حال بارگذاری…")).not.toBeInTheDocument();
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  localStorageMock.clear();
  localStorageMock.setItem("halqe_token", "test-token");
  (apiGetWorklist as jest.Mock).mockResolvedValue(RESPONSE);
});

// ─────────────────────────────────────────────────────────────
// Overdue marker visibility
// ─────────────────────────────────────────────────────────────

describe("WorklistPage — overdue marker", () => {
  it("shows exactly one «سررسید گذشته» marker — only on the open past-due task", async () => {
    await renderWorklistAndWait();

    // 1 open+past task → exactly one overdue marker (not the future, not the done one)
    const markers = screen.getAllByText("سررسید گذشته");
    expect(markers).toHaveLength(1);
  });

  it("places the overdue marker on the open past-due patient's row, not others", async () => {
    await renderWorklistAndWait();

    const marker = screen.getByText("سررسید گذشته");
    // Climb to the enclosing <tr> and confirm it is the past-due patient's row.
    const row = marker.closest("tr");
    expect(row).not.toBeNull();
    expect(row).toHaveTextContent("بیمارِ سررسیدگذشته");
  });

  it("does NOT mark the future-dated open task as overdue", async () => {
    await renderWorklistAndWait();

    const futureRow = screen.getByText("بیمارِ آینده").closest("tr");
    expect(futureRow).not.toBeNull();
    expect(futureRow).not.toHaveTextContent("سررسید گذشته");
  });

  it("does NOT mark a done task as overdue even when its due_date is in the past", async () => {
    await renderWorklistAndWait();

    const doneRow = screen.getByText("بیمارِ انجام‌شده").closest("tr");
    expect(doneRow).not.toBeNull();
    expect(doneRow).not.toHaveTextContent("سررسید گذشته");
  });
});

// ─────────────────────────────────────────────────────────────
// todayTehranISO() format (value is non-deterministic, format is not)
// ─────────────────────────────────────────────────────────────

describe("todayTehranISO", () => {
  it("returns a YYYY-MM-DD string", () => {
    expect(todayTehranISO()).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});
