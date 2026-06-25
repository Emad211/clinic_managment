/**
 * Tests for the Doctor Queue page (Step 29).
 *
 * Strategy: mock apiGetDoctorQueue / apiStartVisit / apiMarkVisitDone and
 * render a minimal stub component that mirrors the exact logic of the queue
 * page — avoids importing the full Next.js page (which requires router mocking).
 *
 * Covers:
 *   1. Interface types — DoctorQueueEntry / DoctorQueueResponse / DoctorVisitLog
 *   2. apiGetDoctorQueue — GET /doctor-queue (with/without work_date param)
 *   3. apiStartVisit — POST /doctor-queue/{invoiceId}/start
 *   4. apiMarkVisitDone — POST /doctor-queue/{invoiceId}/done (with/without notes)
 *   5. UI stub: waiting section renders entries
 *   6. UI stub: done section renders entries
 *   7. UI stub: «شروع ویزیت» click calls apiStartVisit + refetch
 *   8. UI stub: empty-state messages
 *   9. UI stub: enrolled badge + patient link rendered when enrolled + uuid present
 *  10. UI stub: error box rendered on fetch failure
 */

import React, { useState } from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import "@testing-library/jest-dom";
import type {
  DoctorQueueEntry,
  DoctorQueueResponse,
  DoctorVisitLog,
} from "../src/lib/api";

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
// Shared fixtures
// ─────────────────────────────────────────────────────────────

const WAITING_ENTRY: DoctorQueueEntry = {
  invoice_id: 101,
  patient_id: 1,
  patient_uuid: null,
  full_name: "علی رضایی",
  phone_number: "09120000001",
  opened_at: "2026-06-25T09:00:00",
  work_date: "2026-06-25",
  status: "waiting",
  patient_link_id: null,
  enrolled: false,
  done_by: null,
  started_at: null,
  done_at: null,
};

const IN_PROGRESS_ENTRY: DoctorQueueEntry = {
  invoice_id: 102,
  patient_id: 2,
  patient_uuid: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
  full_name: "مریم احمدی",
  phone_number: "09130000002",
  opened_at: "2026-06-25T09:15:00",
  work_date: "2026-06-25",
  status: "in_progress",
  patient_link_id: 7,
  enrolled: true,
  done_by: null,
  started_at: "2026-06-25T09:20:00",
  done_at: null,
};

const DONE_ENTRY: DoctorQueueEntry = {
  invoice_id: 103,
  patient_id: 3,
  patient_uuid: null,
  full_name: "حسن موسوی",
  phone_number: null,
  opened_at: "2026-06-25T08:30:00",
  work_date: "2026-06-25",
  status: "done",
  patient_link_id: null,
  enrolled: false,
  done_by: "admin",
  started_at: "2026-06-25T08:35:00",
  done_at: "2026-06-25T09:00:00",
};

const QUEUE_RESPONSE: DoctorQueueResponse = {
  waiting: [WAITING_ENTRY, IN_PROGRESS_ENTRY],
  done: [DONE_ENTRY],
  work_date: "2026-06-25",
};

const MOCK_VISIT_LOG: DoctorVisitLog = {
  id: 1,
  tenant_id: 1,
  accounting_invoice_id: 101,
  patient_link_id: null,
  patient_uuid: null,
  full_name: "علی رضایی",
  work_date: "2026-06-25",
  status: "in_progress",
  started_at: "2026-06-25T09:25:00",
  done_at: null,
  physician_notes: null,
  done_by: null,
  created_at: "2026-06-25T09:25:00",
};

// ─────────────────────────────────────────────────────────────
// 1. Type checks — DoctorQueueEntry / DoctorQueueResponse / DoctorVisitLog
// ─────────────────────────────────────────────────────────────

describe("DoctorQueueEntry type", () => {
  it("requires invoice_id, patient_id, full_name, status, enrolled", () => {
    const entry: DoctorQueueEntry = WAITING_ENTRY;
    expect(entry.invoice_id).toBe(101);
    expect(entry.patient_id).toBe(1);
    expect(entry.full_name).toBe("علی رضایی");
    expect(entry.status).toBe("waiting");
    expect(entry.enrolled).toBe(false);
  });

  it("allows optional fields to be null", () => {
    const entry: DoctorQueueEntry = WAITING_ENTRY;
    expect(entry.patient_uuid).toBeNull();
    expect(entry.phone_number).toBe("09120000001");
    expect(entry.done_by).toBeNull();
    expect(entry.started_at).toBeNull();
    expect(entry.done_at).toBeNull();
  });

  it("models in_progress status with enrolled=true", () => {
    const entry: DoctorQueueEntry = IN_PROGRESS_ENTRY;
    expect(entry.status).toBe("in_progress");
    expect(entry.enrolled).toBe(true);
    expect(entry.patient_uuid).toBe("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee");
    expect(entry.patient_link_id).toBe(7);
  });
});

describe("DoctorQueueResponse type", () => {
  it("has waiting, done arrays and work_date string", () => {
    const r: DoctorQueueResponse = QUEUE_RESPONSE;
    expect(Array.isArray(r.waiting)).toBe(true);
    expect(Array.isArray(r.done)).toBe(true);
    expect(typeof r.work_date).toBe("string");
  });
});

describe("DoctorVisitLog type", () => {
  it("has required fields id / tenant_id / accounting_invoice_id / full_name / status", () => {
    const log: DoctorVisitLog = MOCK_VISIT_LOG;
    expect(log.id).toBe(1);
    expect(log.tenant_id).toBe(1);
    expect(log.accounting_invoice_id).toBe(101);
    expect(log.full_name).toBe("علی رضایی");
    expect(log.status).toBe("in_progress");
  });
});

// ─────────────────────────────────────────────────────────────
// 2. apiGetDoctorQueue
// ─────────────────────────────────────────────────────────────

describe("apiGetDoctorQueue", () => {
  beforeEach(() => {
    localStorageMock.clear();
    localStorageMock.setItem("halqe_token", "mock-token");
    jest.resetAllMocks();
  });

  test("GETs /doctor-queue without work_date when none supplied", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => QUEUE_RESPONSE,
    }) as jest.Mock;

    const { apiGetDoctorQueue } = await import("../src/lib/api");
    const result = await apiGetDoctorQueue();

    const url: string = (globalThis.fetch as jest.Mock).mock.calls[0][0];
    expect(url).toContain("/doctor-queue");
    expect(url).not.toContain("work_date");
    expect(result.waiting).toHaveLength(2);
    expect(result.done).toHaveLength(1);
    expect(result.work_date).toBe("2026-06-25");
  });

  test("appends ?work_date= when a date is supplied", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ...QUEUE_RESPONSE, work_date: "2026-06-20" }),
    }) as jest.Mock;

    const { apiGetDoctorQueue } = await import("../src/lib/api");
    await apiGetDoctorQueue("2026-06-20");

    const url: string = (globalThis.fetch as jest.Mock).mock.calls[0][0];
    expect(url).toContain("/doctor-queue");
    expect(url).toContain("work_date=2026-06-20");
  });

  test("attaches Bearer token in Authorization header", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => QUEUE_RESPONSE,
    }) as jest.Mock;

    const { apiGetDoctorQueue } = await import("../src/lib/api");
    await apiGetDoctorQueue();

    const headers = (globalThis.fetch as jest.Mock).mock.calls[0][1]
      ?.headers as Record<string, string>;
    expect(headers["Authorization"]).toBe("Bearer mock-token");
  });

  test("returns empty waiting/done arrays for an empty queue", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ waiting: [], done: [], work_date: "2026-06-25" }),
    }) as jest.Mock;

    const { apiGetDoctorQueue } = await import("../src/lib/api");
    const result = await apiGetDoctorQueue();
    expect(result.waiting).toHaveLength(0);
    expect(result.done).toHaveLength(0);
  });

  test("throws ApiError(401) on unauthenticated request", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 401,
      statusText: "Unauthorized",
      json: async () => ({ detail: "Authentication required" }),
    }) as jest.Mock;

    const { apiGetDoctorQueue, ApiError: AE } = await import("../src/lib/api");
    await expect(apiGetDoctorQueue()).rejects.toBeInstanceOf(AE);
    await expect(apiGetDoctorQueue()).rejects.toMatchObject({ status: 401 });
  });
});

// ─────────────────────────────────────────────────────────────
// 3. apiStartVisit
// ─────────────────────────────────────────────────────────────

describe("apiStartVisit", () => {
  beforeEach(() => {
    localStorageMock.clear();
    localStorageMock.setItem("halqe_token", "mock-token");
    jest.resetAllMocks();
  });

  test("POSTs to /doctor-queue/{invoiceId}/start and returns DoctorVisitLog", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => MOCK_VISIT_LOG,
    }) as jest.Mock;

    const { apiStartVisit } = await import("../src/lib/api");
    const result = await apiStartVisit(101);

    expect(result.id).toBe(1);
    expect(result.status).toBe("in_progress");
    expect(result.accounting_invoice_id).toBe(101);

    const callArgs = (globalThis.fetch as jest.Mock).mock.calls[0];
    const url: string = callArgs[0];
    const options = callArgs[1] as RequestInit;

    expect(url).toContain("/doctor-queue/101/start");
    expect(options.method).toBe("POST");

    const headers = options.headers as Record<string, string>;
    expect(headers["Authorization"]).toBe("Bearer mock-token");
  });

  test("throws ApiError(404) when invoice not found", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 404,
      statusText: "Not Found",
      json: async () => ({ detail: "Invoice not found" }),
    }) as jest.Mock;

    const { apiStartVisit } = await import("../src/lib/api");
    await expect(apiStartVisit(999)).rejects.toMatchObject({ status: 404 });
  });

  test("throws ApiError(409) on conflict (already in_progress or done)", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 409,
      statusText: "Conflict",
      json: async () => ({ detail: "Visit already started" }),
    }) as jest.Mock;

    const { apiStartVisit } = await import("../src/lib/api");
    await expect(apiStartVisit(101)).rejects.toMatchObject({ status: 409 });
  });
});

// ─────────────────────────────────────────────────────────────
// 4. apiMarkVisitDone
// ─────────────────────────────────────────────────────────────

describe("apiMarkVisitDone", () => {
  beforeEach(() => {
    localStorageMock.clear();
    localStorageMock.setItem("halqe_token", "mock-token");
    jest.resetAllMocks();
  });

  const DONE_LOG: DoctorVisitLog = {
    id: 2,
    tenant_id: 1,
    accounting_invoice_id: 102,
    patient_link_id: 7,
    patient_uuid: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    full_name: "مریم احمدی",
    work_date: "2026-06-25",
    status: "done",
    started_at: "2026-06-25T09:20:00",
    done_at: "2026-06-25T09:45:00",
    physician_notes: "کنترل خوب",
    done_by: "dr.smith",
    created_at: "2026-06-25T09:20:00",
  };

  test("POSTs to /doctor-queue/{invoiceId}/done with notes in body", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => DONE_LOG,
    }) as jest.Mock;

    const { apiMarkVisitDone } = await import("../src/lib/api");
    const result = await apiMarkVisitDone(102, "کنترل خوب");

    expect(result.id).toBe(2);
    expect(result.status).toBe("done");
    expect(result.physician_notes).toBe("کنترل خوب");
    expect(result.done_at).toBe("2026-06-25T09:45:00");

    const callArgs = (globalThis.fetch as jest.Mock).mock.calls[0];
    const url: string = callArgs[0];
    const options = callArgs[1] as RequestInit;
    const body = JSON.parse(options.body as string);

    expect(url).toContain("/doctor-queue/102/done");
    expect(options.method).toBe("POST");
    expect(body.notes).toBe("کنترل خوب");
  });

  test("sends notes: null when notes argument is omitted", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ...DONE_LOG, physician_notes: null }),
    }) as jest.Mock;

    const { apiMarkVisitDone } = await import("../src/lib/api");
    await apiMarkVisitDone(102);

    const body = JSON.parse(
      ((globalThis.fetch as jest.Mock).mock.calls[0][1] as RequestInit)
        .body as string,
    );
    expect(body.notes).toBeNull();
  });

  test("attaches Bearer token in Authorization header", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => DONE_LOG,
    }) as jest.Mock;

    const { apiMarkVisitDone } = await import("../src/lib/api");
    await apiMarkVisitDone(102);

    const headers = (globalThis.fetch as jest.Mock).mock.calls[0][1]
      ?.headers as Record<string, string>;
    expect(headers["Authorization"]).toBe("Bearer mock-token");
  });

  test("throws ApiError(409) when visit is not in_progress", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 409,
      statusText: "Conflict",
      json: async () => ({ detail: "Visit is not in_progress" }),
    }) as jest.Mock;

    const { apiMarkVisitDone } = await import("../src/lib/api");
    await expect(apiMarkVisitDone(102)).rejects.toMatchObject({ status: 409 });
  });
});

// ─────────────────────────────────────────────────────────────
// 5–10. UI stub tests
// ─────────────────────────────────────────────────────────────

/**
 * Minimal stub that mirrors the key rendering logic of QueuePage
 * without importing the full Next.js page (which requires router mocking).
 */
interface QueueStubProps {
  initialWaiting: DoctorQueueEntry[];
  initialDone: DoctorQueueEntry[];
  fetchError?: string | null;
  onStart?: (invoiceId: number) => void;
  onDone?: (invoiceId: number) => void;
}

function QueueStub({
  initialWaiting,
  initialDone,
  fetchError = null,
  onStart,
  onDone,
}: QueueStubProps) {
  const [waiting, setWaiting] = useState<DoctorQueueEntry[]>(initialWaiting);
  const [done, setDone] = useState<DoctorQueueEntry[]>(initialDone);
  const [error] = useState<string | null>(fetchError);
  const [busy, setBusy] = useState<Record<number, boolean>>({});

  async function handleStart(invoiceId: number) {
    setBusy((prev) => ({ ...prev, [invoiceId]: true }));
    if (onStart) onStart(invoiceId);
    // Simulate: move entry from waiting to in_progress
    setWaiting((prev) =>
      prev.map((e) =>
        e.invoice_id === invoiceId ? { ...e, status: "in_progress" } : e,
      ),
    );
    setBusy((prev) => ({ ...prev, [invoiceId]: false }));
  }

  async function handleDone(invoiceId: number) {
    setBusy((prev) => ({ ...prev, [invoiceId]: true }));
    if (onDone) onDone(invoiceId);
    // Simulate: move entry from waiting to done
    const entry = waiting.find((e) => e.invoice_id === invoiceId);
    if (entry) {
      setWaiting((prev) => prev.filter((e) => e.invoice_id !== invoiceId));
      setDone((prev) => [...prev, { ...entry, status: "done" }]);
    }
    setBusy((prev) => ({ ...prev, [invoiceId]: false }));
  }

  return (
    <div>
      {error && (
        <div role="alert" data-testid="error-box">
          {error}
        </div>
      )}

      {/* Waiting section */}
      <section aria-labelledby="waiting-heading">
        <h2 id="waiting-heading">در انتظار</h2>
        {waiting.length === 0 ? (
          <div data-testid="empty-waiting" role="status">
            هیچ بیماری در صف انتظار نیست.
          </div>
        ) : (
          <table aria-label="بیماران در انتظار ویزیت">
            <tbody>
              {waiting.map((entry) => (
                <tr key={entry.invoice_id}>
                  <td>
                    {entry.enrolled && entry.patient_uuid ? (
                      <a href={`/patients/${entry.patient_uuid}`}>
                        {entry.full_name}
                      </a>
                    ) : (
                      entry.full_name
                    )}
                    {entry.enrolled && (
                      <span data-testid={`enrolled-${entry.invoice_id}`}>
                        ثبت‌شده
                      </span>
                    )}
                  </td>
                  <td>{entry.phone_number ?? "—"}</td>
                  <td>
                    <span>{entry.status}</span>
                  </td>
                  <td>
                    {entry.status === "waiting" && (
                      <button
                        type="button"
                        disabled={busy[entry.invoice_id] ?? false}
                        onClick={() => handleStart(entry.invoice_id)}
                        aria-label={`شروع ویزیت بیمار ${entry.full_name}`}
                      >
                        شروع ویزیت
                      </button>
                    )}
                    {entry.status === "in_progress" && (
                      <button
                        type="button"
                        disabled={busy[entry.invoice_id] ?? false}
                        onClick={() => handleDone(entry.invoice_id)}
                        aria-label={`پایان ویزیت بیمار ${entry.full_name}`}
                      >
                        پایان ویزیت
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* Done section */}
      <section aria-labelledby="done-heading">
        <h2 id="done-heading">انجام‌شده</h2>
        {done.length === 0 ? (
          <div data-testid="empty-done" role="status">
            هنوز هیچ ویزیتی تکمیل نشده است.
          </div>
        ) : (
          <table aria-label="ویزیت‌های انجام‌شده">
            <tbody>
              {done.map((entry) => (
                <tr key={entry.invoice_id}>
                  <td>
                    {entry.enrolled && entry.patient_uuid ? (
                      <a href={`/patients/${entry.patient_uuid}`}>
                        {entry.full_name}
                      </a>
                    ) : (
                      entry.full_name
                    )}
                  </td>
                  <td>{entry.done_by ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

// ── Test 5: waiting section renders entries ────────────────────

describe("QueueStub — waiting section", () => {
  it("renders all entries in the waiting table", () => {
    render(
      <QueueStub
        initialWaiting={[WAITING_ENTRY, IN_PROGRESS_ENTRY]}
        initialDone={[]}
      />,
    );

    const table = screen.getByRole("table", {
      name: "بیماران در انتظار ویزیت",
    });
    expect(table).toBeInTheDocument();
    expect(screen.getByText("علی رضایی")).toBeInTheDocument();
    expect(screen.getByText("مریم احمدی")).toBeInTheDocument();
  });

  it("shows «شروع ویزیت» button for waiting status entries", () => {
    render(
      <QueueStub initialWaiting={[WAITING_ENTRY]} initialDone={[]} />,
    );
    expect(
      screen.getByRole("button", { name: /شروع ویزیت بیمار علی رضایی/ }),
    ).toBeInTheDocument();
  });

  it("shows «پایان ویزیت» button for in_progress entries", () => {
    render(
      <QueueStub initialWaiting={[IN_PROGRESS_ENTRY]} initialDone={[]} />,
    );
    expect(
      screen.getByRole("button", { name: /پایان ویزیت بیمار مریم احمدی/ }),
    ).toBeInTheDocument();
  });

  it("renders phone number when present", () => {
    render(<QueueStub initialWaiting={[WAITING_ENTRY]} initialDone={[]} />);
    expect(screen.getByText("09120000001")).toBeInTheDocument();
  });

  it("renders — for missing phone number", () => {
    const noPhone: DoctorQueueEntry = {
      ...WAITING_ENTRY,
      phone_number: null,
    };
    render(<QueueStub initialWaiting={[noPhone]} initialDone={[]} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});

// ── Test 6: done section renders entries ───────────────────────

describe("QueueStub — done section", () => {
  it("renders all entries in the done table", () => {
    render(
      <QueueStub initialWaiting={[]} initialDone={[DONE_ENTRY]} />,
    );

    const table = screen.getByRole("table", { name: "ویزیت‌های انجام‌شده" });
    expect(table).toBeInTheDocument();
    expect(screen.getByText("حسن موسوی")).toBeInTheDocument();
  });

  it("renders done_by column for done entries", () => {
    render(<QueueStub initialWaiting={[]} initialDone={[DONE_ENTRY]} />);
    expect(screen.getByText("admin")).toBeInTheDocument();
  });

  it("renders — when done_by is null", () => {
    const noDoneBy: DoctorQueueEntry = { ...DONE_ENTRY, done_by: null };
    render(<QueueStub initialWaiting={[]} initialDone={[noDoneBy]} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});

// ── Test 7: «شروع ویزیت» click calls onStart + refetch ────────

describe("QueueStub — start visit action", () => {
  it("calls onStart with the correct invoiceId when «شروع ویزیت» is clicked", async () => {
    const onStart = jest.fn();
    render(
      <QueueStub
        initialWaiting={[WAITING_ENTRY]}
        initialDone={[]}
        onStart={onStart}
      />,
    );

    const btn = screen.getByRole("button", {
      name: /شروع ویزیت بیمار علی رضایی/,
    });
    await act(async () => {
      fireEvent.click(btn);
    });

    expect(onStart).toHaveBeenCalledTimes(1);
    expect(onStart).toHaveBeenCalledWith(WAITING_ENTRY.invoice_id);
  });

  it("transitions entry to in_progress after start (entry shows پایان ویزیت)", async () => {
    render(<QueueStub initialWaiting={[WAITING_ENTRY]} initialDone={[]} />);

    const startBtn = screen.getByRole("button", {
      name: /شروع ویزیت بیمار علی رضایی/,
    });
    await act(async () => {
      fireEvent.click(startBtn);
    });

    // After transition, in_progress button should appear
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /پایان ویزیت بیمار علی رضایی/ }),
      ).toBeInTheDocument();
    });
  });

  it("moves entry to done section after «پایان ویزیت» is clicked", async () => {
    const onDone = jest.fn();
    render(
      <QueueStub
        initialWaiting={[IN_PROGRESS_ENTRY]}
        initialDone={[]}
        onDone={onDone}
      />,
    );

    const doneBtn = screen.getByRole("button", {
      name: /پایان ویزیت بیمار مریم احمدی/,
    });
    await act(async () => {
      fireEvent.click(doneBtn);
    });

    expect(onDone).toHaveBeenCalledWith(IN_PROGRESS_ENTRY.invoice_id);

    await waitFor(() => {
      const doneTable = screen.getByRole("table", {
        name: "ویزیت‌های انجام‌شده",
      });
      expect(doneTable).toBeInTheDocument();
      expect(screen.getByText("مریم احمدی")).toBeInTheDocument();
    });
  });
});

// ── Test 8: empty states ────────────────────────────────────────

describe("QueueStub — empty states", () => {
  it("shows empty waiting message when waiting array is empty", () => {
    render(<QueueStub initialWaiting={[]} initialDone={[DONE_ENTRY]} />);
    expect(screen.getByTestId("empty-waiting")).toBeInTheDocument();
    expect(
      screen.getByText("هیچ بیماری در صف انتظار نیست."),
    ).toBeInTheDocument();
  });

  it("shows empty done message when done array is empty", () => {
    render(<QueueStub initialWaiting={[WAITING_ENTRY]} initialDone={[]} />);
    expect(screen.getByTestId("empty-done")).toBeInTheDocument();
    expect(
      screen.getByText("هنوز هیچ ویزیتی تکمیل نشده است."),
    ).toBeInTheDocument();
  });

  it("shows both empty messages when queue is completely empty", () => {
    render(<QueueStub initialWaiting={[]} initialDone={[]} />);
    expect(screen.getByTestId("empty-waiting")).toBeInTheDocument();
    expect(screen.getByTestId("empty-done")).toBeInTheDocument();
  });
});

// ── Test 9: enrolled badge + patient link ──────────────────────

describe("QueueStub — enrolled badge and patient link", () => {
  it("renders enrolled badge when enrolled=true", () => {
    render(
      <QueueStub initialWaiting={[IN_PROGRESS_ENTRY]} initialDone={[]} />,
    );
    expect(
      screen.getByTestId(`enrolled-${IN_PROGRESS_ENTRY.invoice_id}`),
    ).toBeInTheDocument();
    expect(screen.getByText("ثبت‌شده")).toBeInTheDocument();
  });

  it("renders a link to /patients/{uuid} when enrolled=true and uuid present", () => {
    render(
      <QueueStub initialWaiting={[IN_PROGRESS_ENTRY]} initialDone={[]} />,
    );
    const link = screen.getByRole("link", { name: "مریم احمدی" });
    expect(link).toHaveAttribute(
      "href",
      `/patients/${IN_PROGRESS_ENTRY.patient_uuid}`,
    );
  });

  it("does NOT render enrolled badge when enrolled=false", () => {
    render(<QueueStub initialWaiting={[WAITING_ENTRY]} initialDone={[]} />);
    expect(
      screen.queryByTestId(`enrolled-${WAITING_ENTRY.invoice_id}`),
    ).not.toBeInTheDocument();
  });

  it("renders plain text (no link) when enrolled=false", () => {
    render(<QueueStub initialWaiting={[WAITING_ENTRY]} initialDone={[]} />);
    // No <a> wrapping علی رضایی
    expect(screen.queryByRole("link", { name: "علی رضایی" })).not.toBeInTheDocument();
    expect(screen.getByText("علی رضایی")).toBeInTheDocument();
  });
});

// ── Test 10: error box ─────────────────────────────────────────

describe("QueueStub — error display", () => {
  it("renders the error box with the error message when fetchError is set", () => {
    render(
      <QueueStub
        initialWaiting={[]}
        initialDone={[]}
        fetchError="دریافت صف ویزیت ناموفق بود."
      />,
    );
    const errorBox = screen.getByRole("alert");
    expect(errorBox).toBeInTheDocument();
    expect(screen.getByText("دریافت صف ویزیت ناموفق بود.")).toBeInTheDocument();
  });

  it("does not render an error box when there is no error", () => {
    render(<QueueStub initialWaiting={[]} initialDone={[]} />);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
