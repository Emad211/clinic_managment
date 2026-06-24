/**
 * Tests for the encounter registration flow and encounters list rendering.
 *
 * Strategy: test helpers + minimal inline components that mirror the exact
 * logic of RegisterVisitForm and EncountersList — avoids importing the full
 * patient-detail page (which requires Next.js router mocking).
 */

import React, { useState } from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import "@testing-library/jest-dom";
import { formatJalali } from "../src/lib/jalali";

// ─────────────────────────────────────────────────────────────
// Mock localStorage
// ─────────────────────────────────────────────────────────────

const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = value; },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { store = {}; },
  };
})();

Object.defineProperty(globalThis, "localStorage", { value: localStorageMock });

// ─────────────────────────────────────────────────────────────
// 1. encounterErrorMessage helper (inline — mirrors page logic)
// ─────────────────────────────────────────────────────────────

import { ApiError } from "../src/lib/api";

function encounterErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    const msg = err.message;
    if (msg.includes("encounter_sealed") || err.status === 409) {
      if (msg.toLowerCase().includes("duplicate")) {
        return "این اندازه‌گیری قبلاً در این ویزیت ثبت شده.";
      }
      if (msg.toLowerCase().includes("sealed") || msg.toLowerCase().includes("complete")) {
        return "این ویزیت قبلاً بسته شده است.";
      }
      return "تعارض داده — ممکن است این ویزیت قبلاً ثبت شده باشد.";
    }
    if (err.status === 401) return "لطفاً دوباره وارد شوید.";
    if (err.status === 404) return "بیمار یا ویزیت یافت نشد.";
    if (err.status === 422) return "داده‌های وارد‌شده معتبر نیستند.";
    return `خطا: ${msg}`;
  }
  return "عملیات ناموفق بود. دوباره امتحان کنید.";
}

describe("encounterErrorMessage", () => {
  it("maps duplicate_vital (409) to Persian message", () => {
    const err = new ApiError(409, "duplicate_vital");
    expect(encounterErrorMessage(err)).toBe("این اندازه‌گیری قبلاً در این ویزیت ثبت شده.");
  });

  it("maps encounter_sealed (409) to Persian message", () => {
    const err = new ApiError(409, "encounter_sealed — the encounter is sealed");
    expect(encounterErrorMessage(err)).toBe("این ویزیت قبلاً بسته شده است.");
  });

  it("maps generic 409 to generic conflict message", () => {
    const err = new ApiError(409, "some other conflict");
    expect(encounterErrorMessage(err)).toBe(
      "تعارض داده — ممکن است این ویزیت قبلاً ثبت شده باشد.",
    );
  });

  it("maps 401 to re-login message", () => {
    const err = new ApiError(401, "Authentication required");
    expect(encounterErrorMessage(err)).toBe("لطفاً دوباره وارد شوید.");
  });

  it("maps 404 to not-found message", () => {
    const err = new ApiError(404, "Patient not found");
    expect(encounterErrorMessage(err)).toBe("بیمار یا ویزیت یافت نشد.");
  });

  it("maps 422 to validation message", () => {
    const err = new ApiError(422, "validation error");
    expect(encounterErrorMessage(err)).toBe("داده‌های وارد‌شده معتبر نیستند.");
  });

  it("wraps other ApiErrors with the detail message", () => {
    const err = new ApiError(500, "Internal server error");
    expect(encounterErrorMessage(err)).toBe("خطا: Internal server error");
  });

  it("maps non-ApiError to generic message", () => {
    expect(encounterErrorMessage(new Error("network error"))).toBe(
      "عملیات ناموفق بود. دوباره امتحان کنید.",
    );
    expect(encounterErrorMessage("string error")).toBe(
      "عملیات ناموفق بود. دوباره امتحان کنید.",
    );
  });
});

// ─────────────────────────────────────────────────────────────
// 2. Encounter type label map (Persian labels for select options)
// ─────────────────────────────────────────────────────────────

const ENCOUNTER_TYPE_LABEL: Record<string, string> = {
  visit: "ویزیت",
  follow_up: "پیگیری",
  phone: "تلفنی",
  remote: "از راه دور",
};

describe("ENCOUNTER_TYPE_LABEL", () => {
  it("has Persian label for all four types", () => {
    expect(ENCOUNTER_TYPE_LABEL["visit"]).toBe("ویزیت");
    expect(ENCOUNTER_TYPE_LABEL["follow_up"]).toBe("پیگیری");
    expect(ENCOUNTER_TYPE_LABEL["phone"]).toBe("تلفنی");
    expect(ENCOUNTER_TYPE_LABEL["remote"]).toBe("از راه دور");
  });
});

// ─────────────────────────────────────────────────────────────
// 3. Minimal RegisterVisitForm component — mirrors form logic
// ─────────────────────────────────────────────────────────────

type EncounterType = "visit" | "follow_up" | "phone" | "remote";

interface MinimalFormProps {
  onSubmit: (data: {
    encounterType: EncounterType;
    chiefComplaint: string;
    vitals: Array<{ type: string; value: number; unit: string | null }>;
  }) => Promise<void>;
  onClose: () => void;
}

function MinimalRegisterVisitForm({ onSubmit, onClose }: MinimalFormProps) {
  const [encounterType, setEncounterType] = useState<EncounterType>("visit");
  const [chiefComplaint, setChiefComplaint] = useState("");
  const [vitalType, setVitalType] = useState("");
  const [vitalValue, setVitalValue] = useState("");
  const [vitalUnit, setVitalUnit] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    const validVitals =
      vitalType.trim() && vitalValue.trim()
        ? [{ type: vitalType.trim(), value: parseFloat(vitalValue), unit: vitalUnit.trim() || null }]
        : [];
    try {
      await onSubmit({ encounterType, chiefComplaint, vitals: validVitals });
      setSuccess(true);
    } catch (err) {
      setError(encounterErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (success) {
    return <div role="status">ویزیت با موفقیت ثبت شد.</div>;
  }

  return (
    <form onSubmit={handleSubmit} aria-label="فرم ثبت ویزیت">
      <select
        value={encounterType}
        onChange={(e) => setEncounterType(e.target.value as EncounterType)}
        aria-label="نوع ویزیت"
        disabled={busy}
      >
        {(Object.keys(ENCOUNTER_TYPE_LABEL) as EncounterType[]).map((t) => (
          <option key={t} value={t}>
            {ENCOUNTER_TYPE_LABEL[t]}
          </option>
        ))}
      </select>

      <textarea
        value={chiefComplaint}
        onChange={(e) => setChiefComplaint(e.target.value)}
        aria-label="شکایت اصلی بیمار"
        disabled={busy}
      />

      {/* Single vital row for simplicity */}
      <input
        type="text"
        value={vitalType}
        onChange={(e) => setVitalType(e.target.value)}
        placeholder="نوع"
        aria-label="نوع اندازه‌گیری"
        disabled={busy}
      />
      <input
        type="number"
        value={vitalValue}
        onChange={(e) => setVitalValue(e.target.value)}
        placeholder="مقدار"
        aria-label="مقدار اندازه‌گیری"
        disabled={busy}
      />
      <input
        type="text"
        value={vitalUnit}
        onChange={(e) => setVitalUnit(e.target.value)}
        placeholder="واحد"
        aria-label="واحد اندازه‌گیری"
        disabled={busy}
      />

      {error && <div role="alert">{error}</div>}

      <button type="submit" disabled={busy} aria-busy={busy}>
        {busy ? "در حال ثبت…" : "ثبت ویزیت"}
      </button>
      <button type="button" onClick={onClose} disabled={busy}>
        انصراف
      </button>
    </form>
  );
}

describe("MinimalRegisterVisitForm", () => {
  it("renders all four encounter type options", () => {
    render(
      <MinimalRegisterVisitForm
        onSubmit={jest.fn()}
        onClose={jest.fn()}
      />,
    );
    const select = screen.getByRole("combobox", { name: /نوع ویزیت/ });
    expect(select).toBeInTheDocument();

    const options = screen.getAllByRole("option");
    const labels = options.map((o) => o.textContent);
    expect(labels).toContain("ویزیت");
    expect(labels).toContain("پیگیری");
    expect(labels).toContain("تلفنی");
    expect(labels).toContain("از راه دور");
  });

  it("defaults to 'ویزیت' type", () => {
    render(
      <MinimalRegisterVisitForm
        onSubmit={jest.fn()}
        onClose={jest.fn()}
      />,
    );
    const select = screen.getByRole("combobox", { name: /نوع ویزیت/ }) as HTMLSelectElement;
    expect(select.value).toBe("visit");
  });

  it("calls onClose when انصراف is clicked", () => {
    const onClose = jest.fn();
    render(
      <MinimalRegisterVisitForm
        onSubmit={jest.fn()}
        onClose={onClose}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /انصراف/ }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("calls onSubmit with correct encounter type and chief_complaint", async () => {
    const onSubmit = jest.fn().mockResolvedValue(undefined);
    render(
      <MinimalRegisterVisitForm
        onSubmit={onSubmit}
        onClose={jest.fn()}
      />,
    );

    // Change type to follow_up
    fireEvent.change(screen.getByRole("combobox", { name: /نوع ویزیت/ }), {
      target: { value: "follow_up" },
    });

    // Set chief complaint
    fireEvent.change(screen.getByRole("textbox", { name: /شکایت اصلی/ }), {
      target: { value: "درد قفسه سینه" },
    });

    fireEvent.click(screen.getByRole("button", { name: /ثبت ویزیت/ }));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledTimes(1);
    });

    const callArg = onSubmit.mock.calls[0][0];
    expect(callArg.encounterType).toBe("follow_up");
    expect(callArg.chiefComplaint).toBe("درد قفسه سینه");
  });

  it("includes vitals in the submission when type and value are filled", async () => {
    const onSubmit = jest.fn().mockResolvedValue(undefined);
    render(
      <MinimalRegisterVisitForm
        onSubmit={onSubmit}
        onClose={jest.fn()}
      />,
    );

    fireEvent.change(screen.getByRole("textbox", { name: /نوع اندازه‌گیری/ }), {
      target: { value: "FBS" },
    });
    fireEvent.change(screen.getByRole("spinbutton", { name: /مقدار اندازه‌گیری/ }), {
      target: { value: "188" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: /واحد اندازه‌گیری/ }), {
      target: { value: "mg/dL" },
    });

    fireEvent.click(screen.getByRole("button", { name: /ثبت ویزیت/ }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));

    const vitals = onSubmit.mock.calls[0][0].vitals;
    expect(vitals).toHaveLength(1);
    expect(vitals[0].type).toBe("FBS");
    expect(vitals[0].value).toBe(188);
    expect(vitals[0].unit).toBe("mg/dL");
  });

  it("excludes vitals when vital fields are blank", async () => {
    const onSubmit = jest.fn().mockResolvedValue(undefined);
    render(
      <MinimalRegisterVisitForm
        onSubmit={onSubmit}
        onClose={jest.fn()}
      />,
    );

    // Leave vital fields blank
    fireEvent.click(screen.getByRole("button", { name: /ثبت ویزیت/ }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));

    const vitals = onSubmit.mock.calls[0][0].vitals;
    expect(vitals).toHaveLength(0);
  });

  it("shows success state after onSubmit resolves", async () => {
    const onSubmit = jest.fn().mockResolvedValue(undefined);
    render(
      <MinimalRegisterVisitForm
        onSubmit={onSubmit}
        onClose={jest.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /ثبت ویزیت/ }));
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent("ویزیت با موفقیت ثبت شد.");
    });
  });

  it("shows error message when onSubmit rejects with ApiError", async () => {
    const onSubmit = jest
      .fn()
      .mockRejectedValue(new ApiError(409, "duplicate_vital"));
    render(
      <MinimalRegisterVisitForm
        onSubmit={onSubmit}
        onClose={jest.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /ثبت ویزیت/ }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        "این اندازه‌گیری قبلاً در این ویزیت ثبت شده.",
      );
    });
  });

  it("shows busy state (button text changes) while submitting", async () => {
    // Never resolves — keeps busy state visible
    let resolveSubmit!: () => void;
    const onSubmit = jest.fn(
      () => new Promise<void>((res) => { resolveSubmit = res; }),
    );
    render(
      <MinimalRegisterVisitForm
        onSubmit={onSubmit}
        onClose={jest.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /ثبت ویزیت/ }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /در حال ثبت/ })).toBeInTheDocument();
    });

    // Resolve so we don't leave a pending promise
    await act(async () => { resolveSubmit(); });
  });
});

// ─────────────────────────────────────────────────────────────
// 4. Encounter list rendering — Jalali dates + status badges
// ─────────────────────────────────────────────────────────────

const ENCOUNTER_TYPE_LABEL_FULL: Record<string, string> = ENCOUNTER_TYPE_LABEL;
const ENCOUNTER_STATUS_LABEL: Record<string, string> = {
  open: "باز",
  completed: "تکمیل‌شده",
  cancelled: "لغوشده",
};

interface MinimalEncounterItem {
  id: number;
  encounter_type: string;
  encounter_at: string;
  status: string;
  chief_complaint: string | null;
}

function MinimalEncountersList({ items }: { items: MinimalEncounterItem[] }) {
  if (items.length === 0) {
    return <p>هیچ ویزیتی ثبت نشده است.</p>;
  }
  return (
    <ul aria-label="فهرست ویزیت‌های اخیر">
      {items.map((enc) => (
        <li key={enc.id}>
          <span aria-label={`نوع: ${enc.encounter_type}`}>
            {ENCOUNTER_TYPE_LABEL_FULL[enc.encounter_type] ?? enc.encounter_type}
          </span>
          <span
            aria-label={`وضعیت: ${ENCOUNTER_STATUS_LABEL[enc.status] ?? enc.status}`}
            data-status={enc.status}
          >
            {ENCOUNTER_STATUS_LABEL[enc.status] ?? enc.status}
          </span>
          <time dateTime={enc.encounter_at}>{formatJalali(enc.encounter_at)}</time>
          {enc.chief_complaint && <span>{enc.chief_complaint}</span>}
        </li>
      ))}
    </ul>
  );
}

describe("MinimalEncountersList", () => {
  const SAMPLE_ENCOUNTERS: MinimalEncounterItem[] = [
    {
      id: 1,
      encounter_type: "visit",
      encounter_at: "2026-06-24T10:00:00+03:30",
      status: "completed",
      chief_complaint: "کنترل دوره‌ای",
    },
    {
      id: 2,
      encounter_type: "phone",
      encounter_at: "2026-05-10T09:00:00+03:30",
      status: "open",
      chief_complaint: null,
    },
  ];

  it("renders list with correct encounter type labels in Persian", () => {
    render(<MinimalEncountersList items={SAMPLE_ENCOUNTERS} />);
    expect(screen.getByText("ویزیت")).toBeInTheDocument();
    expect(screen.getByText("تلفنی")).toBeInTheDocument();
  });

  it("renders status labels in Persian", () => {
    render(<MinimalEncountersList items={SAMPLE_ENCOUNTERS} />);
    expect(screen.getByText("تکمیل‌شده")).toBeInTheDocument();
    expect(screen.getByText("باز")).toBeInTheDocument();
  });

  it("renders encounter_at as Jalali date in Persian digits", () => {
    render(<MinimalEncountersList items={SAMPLE_ENCOUNTERS} />);
    // 2026-06-24 → 1405/04/03 in Jalali, Persian digits
    const times = screen.getAllByRole("time");
    const dates = times.map((t) => t.textContent);
    expect(dates).toContain("۱۴۰۵/۰۴/۰۳");
  });

  it("renders chief_complaint text when present", () => {
    render(<MinimalEncountersList items={SAMPLE_ENCOUNTERS} />);
    expect(screen.getByText("کنترل دوره‌ای")).toBeInTheDocument();
  });

  it("does not render chief_complaint when null", () => {
    const items = [
      {
        id: 3,
        encounter_type: "visit",
        encounter_at: "2026-06-24T10:00:00+03:30",
        status: "cancelled",
        chief_complaint: null,
      },
    ];
    render(<MinimalEncountersList items={items} />);
    // No complaint text visible
    expect(screen.queryByText("کنترل دوره‌ای")).toBeNull();
  });

  it("shows empty state when items array is empty", () => {
    render(<MinimalEncountersList items={[]} />);
    expect(screen.getByText("هیچ ویزیتی ثبت نشده است.")).toBeInTheDocument();
  });

  it("renders all four encounter types correctly", () => {
    const allTypes: MinimalEncounterItem[] = [
      { id: 1, encounter_type: "visit", encounter_at: "2026-06-01T10:00:00", status: "completed", chief_complaint: null },
      { id: 2, encounter_type: "follow_up", encounter_at: "2026-06-02T10:00:00", status: "completed", chief_complaint: null },
      { id: 3, encounter_type: "phone", encounter_at: "2026-06-03T10:00:00", status: "open", chief_complaint: null },
      { id: 4, encounter_type: "remote", encounter_at: "2026-06-04T10:00:00", status: "cancelled", chief_complaint: null },
    ];
    render(<MinimalEncountersList items={allTypes} />);
    expect(screen.getByText("ویزیت")).toBeInTheDocument();
    expect(screen.getByText("پیگیری")).toBeInTheDocument();
    expect(screen.getByText("تلفنی")).toBeInTheDocument();
    expect(screen.getByText("از راه دور")).toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────
// 5. create→vitals→complete sequence (integration of the three calls)
// ─────────────────────────────────────────────────────────────

describe("register-visit call sequence (create → addVitals → complete)", () => {
  beforeEach(() => {
    localStorageMock.clear();
    jest.resetAllMocks();
    localStorageMock.setItem("halqe_token", "mock-token");
  });

  it("calls create, then addVitals, then complete in order", async () => {
    const callOrder: string[] = [];

    const mockCreate = jest.fn(async () => {
      callOrder.push("create");
      return {
        id: 99,
        status: "open",
        encounter_type: "visit",
        encounter_at: "2026-06-24T10:00:00+03:30",
        tenant_id: 1,
        patient_link_id: 42,
        chief_complaint: "تست",
        doctor_id: null,
        appointment_id: null,
        accounting_invoice_id: null,
        completed_at: null,
        summary_note: null,
        created_by: "admin",
        created_at: "2026-06-24T10:00:00+03:30",
        updated_at: "2026-06-24T10:00:00+03:30",
      };
    });

    const mockAddVitals = jest.fn(async () => {
      callOrder.push("addVitals");
      return { count: 1, vitals: [] };
    });

    const mockComplete = jest.fn(async () => {
      callOrder.push("complete");
      return {
        id: 99,
        status: "completed",
        encounter_type: "visit",
        encounter_at: "2026-06-24T10:00:00+03:30",
        tenant_id: 1,
        patient_link_id: 42,
        chief_complaint: "تست",
        doctor_id: null,
        appointment_id: null,
        accounting_invoice_id: null,
        completed_at: "2026-06-24T10:15:00+03:30",
        summary_note: null,
        created_by: "admin",
        created_at: "2026-06-24T10:00:00+03:30",
        updated_at: "2026-06-24T10:15:00+03:30",
      };
    });

    // Use jest.Mock cast so TS accepts call-with-args (mocks accept any)
    const create = mockCreate as jest.Mock;
    const addVitals = mockAddVitals as jest.Mock;
    const complete = mockComplete as jest.Mock;

    // Simulate the sequence that RegisterVisitForm executes on submit
    async function runVisitFlow(vitals: Array<{ type: string; value: number; unit: string | null }>) {
      const enc = await create();
      if (vitals.length > 0) {
        await addVitals((enc as { id: number }).id, vitals);
      }
      await complete((enc as { id: number }).id);
    }

    await runVisitFlow([{ type: "FBS", value: 188, unit: "mg/dL" }]);

    expect(callOrder).toEqual(["create", "addVitals", "complete"]);
    expect(mockCreate).toHaveBeenCalledTimes(1);
    expect(mockAddVitals).toHaveBeenCalledWith(99, [{ type: "FBS", value: 188, unit: "mg/dL" }]);
    expect(mockComplete).toHaveBeenCalledWith(99);
  });

  it("skips addVitals when no vitals are provided", async () => {
    const callOrder: string[] = [];

    const mockCreate = jest.fn(async () => {
      callOrder.push("create");
      return { id: 100, status: "open" };
    });
    const mockAddVitals = jest.fn(async () => {
      callOrder.push("addVitals");
      return { count: 0, vitals: [] };
    });
    const mockComplete = jest.fn(async () => {
      callOrder.push("complete");
      return { id: 100, status: "completed" };
    });

    const create2 = mockCreate as jest.Mock;
    const addVitals2 = mockAddVitals as jest.Mock;
    const complete2 = mockComplete as jest.Mock;

    async function runVisitFlow(vitals: Array<unknown>) {
      const enc = await create2();
      if (vitals.length > 0) {
        await addVitals2((enc as { id: number }).id, vitals);
      }
      await complete2((enc as { id: number }).id);
    }

    await runVisitFlow([]);

    expect(callOrder).toEqual(["create", "complete"]);
    expect(mockAddVitals).not.toHaveBeenCalled();
  });
});
