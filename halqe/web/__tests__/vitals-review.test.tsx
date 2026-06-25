/**
 * تست‌های jest — VitalsReview (خوشهٔ J، قدم ۴۷)
 * UIِ تأییدِ پزشک برای دادهٔ خوداظهارِ بیمار.
 *
 * سناریوها:
 *   (الف) آیتمِ pendingِ خوداظهار در صندوقِ تأیید با دکمه‌های «تأیید»/«رد» ظاهر شود.
 *   (ب)  «تأیید» → فراخوانیِ verifyVital(uuid, vitalId) + onReviewed صدا زده شود.
 *   (ج)  «رد» → فراخوانیِ rejectVital(uuid, vitalId) + onReviewed.
 *   (د)  هشدارِ اختلاف وقتی خوداظهار با clinicِ قبلی خیلی فرق دارد؛ و نبودِ هشدار وقتی نزدیک است.
 *   (ه)  خوداظهارِ approved در جدول برچسبِ «خوداظهارِ تأییدشده» بگیرد؛ rejected → «ردشده».
 *   (و)  صندوق وقتی هیچ pendingای نیست رندر نشود (نه سکشنِ خالی).
 *   (ز)  verify که 409 برمی‌گرداند → پیامِ فارسیِ «قبلاً تأیید شده».
 *   (ح)  واحدِ خالصِ discrepancyHint (پیورِ تابع) — آستانه‌های fbs و bp_systolic.
 */

import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";

// ─── mock localStorage (api.ts getToken touches it) ─────────────
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (k: string) => store[k] ?? null,
    setItem: (k: string, v: string) => { store[k] = v; },
    removeItem: (k: string) => { delete store[k]; },
    clear: () => { store = {}; },
  };
})();
Object.defineProperty(globalThis, "localStorage", { value: localStorageMock });

// ─── mock api.ts — only verifyVital / rejectVital are stubbed ───
// Everything else (ApiError, vitalReviewState, types) stays real.
jest.mock("@/lib/api", () => {
  const actual = jest.requireActual("@/lib/api");
  return {
    ...actual,
    verifyVital: jest.fn(),
    rejectVital: jest.fn(),
  };
});

import {
  verifyVital,
  rejectVital,
  ApiError,
  type VitalReadingDTO,
} from "@/lib/api";
import {
  VerificationInbox,
  RecentVitalsTable,
  discrepancyHint,
} from "@/components/VitalsReview";

const mockVerify = verifyVital as jest.MockedFunction<typeof verifyVital>;
const mockReject = rejectVital as jest.MockedFunction<typeof rejectVital>;

const UUID = "11111111-2222-3333-4444-555555555555";

// ─── factory for a vital reading ────────────────────────────────
function makeVital(overrides: Partial<VitalReadingDTO> = {}): VitalReadingDTO {
  return {
    id: 1,
    patient_link_id: 10,
    type: "fbs",
    value: 130,
    unit: "mg/dL",
    measured_at: "2026-06-24T08:00:00",
    source: "patient_self",
    notes: null,
    level: null,
    verified: false,
    rejected_at: null,
    ...overrides,
  };
}

beforeEach(() => {
  jest.clearAllMocks();
});

// ─────────────────────────────────────────────────────────────
// (و) inbox hidden when no pending
// ─────────────────────────────────────────────────────────────
describe("VerificationInbox — visibility", () => {
  it("does NOT render when there is no pending self-report", () => {
    const vitals = [
      makeVital({ id: 1, source: "clinic", verified: true }),       // clinic approved
      makeVital({ id: 2, verified: true }),                          // self approved
      makeVital({ id: 3, verified: false, rejected_at: "2026-06-25T09:00:00" }), // self rejected
    ];
    const { container } = render(
      <VerificationInbox vitals={vitals} uuid={UUID} onReviewed={jest.fn()} />,
    );
    // Component returns null → nothing in the DOM.
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByText(/صندوقِ تأیید/)).not.toBeInTheDocument();
  });

  it("does NOT treat clinic-source pending rows as inbox items", () => {
    // A clinic row that is somehow unverified must not appear in the self-report inbox.
    const vitals = [makeVital({ id: 1, source: "clinic", verified: false })];
    const { container } = render(
      <VerificationInbox vitals={vitals} uuid={UUID} onReviewed={jest.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

// ─────────────────────────────────────────────────────────────
// (الف) pending item shows with buttons + count
// ─────────────────────────────────────────────────────────────
describe("VerificationInbox — pending item rendering", () => {
  it("renders a pending self-report with verify/reject buttons and count", () => {
    const vitals = [
      makeVital({ id: 1 }),                                    // pending self-report
      makeVital({ id: 2, verified: true }),                    // approved (not counted)
    ];
    render(<VerificationInbox vitals={vitals} uuid={UUID} onReviewed={jest.fn()} />);

    expect(screen.getByText(/صندوقِ تأیید/)).toBeInTheDocument();
    // count = 1, in Farsi digits
    expect(screen.getByText(/۱ موردِ تأییدنشدهٔ خوداظهار/)).toBeInTheDocument();
    // self-report pending badge
    expect(screen.getByText("خوداظهارِ بیمار — تأییدنشده")).toBeInTheDocument();
    // action buttons
    expect(screen.getByRole("button", { name: "تأیید" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "رد" })).toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────
// (ب) verify → calls verifyVital + onReviewed
// (ج) reject → calls rejectVital + onReviewed
// ─────────────────────────────────────────────────────────────
describe("VerificationInbox — actions", () => {
  it("verify calls verifyVital(uuid, vitalId) and onReviewed on success", async () => {
    mockVerify.mockResolvedValueOnce({} as never);
    const onReviewed = jest.fn();
    const vitals = [makeVital({ id: 42 })];
    render(<VerificationInbox vitals={vitals} uuid={UUID} onReviewed={onReviewed} />);

    fireEvent.click(screen.getByRole("button", { name: "تأیید" }));

    await waitFor(() => expect(mockVerify).toHaveBeenCalledTimes(1));
    expect(mockVerify).toHaveBeenCalledWith(UUID, 42);
    await waitFor(() => expect(onReviewed).toHaveBeenCalledTimes(1));
    // reject not called
    expect(mockReject).not.toHaveBeenCalled();
  });

  it("reject calls rejectVital(uuid, vitalId) and onReviewed on success", async () => {
    mockReject.mockResolvedValueOnce({} as never);
    const onReviewed = jest.fn();
    const vitals = [makeVital({ id: 77 })];
    render(<VerificationInbox vitals={vitals} uuid={UUID} onReviewed={onReviewed} />);

    fireEvent.click(screen.getByRole("button", { name: "رد" }));

    await waitFor(() => expect(mockReject).toHaveBeenCalledTimes(1));
    expect(mockReject).toHaveBeenCalledWith(UUID, 77);
    await waitFor(() => expect(onReviewed).toHaveBeenCalledTimes(1));
    expect(mockVerify).not.toHaveBeenCalled();
  });

  it("disables both buttons (aria-busy) while verify is in flight", async () => {
    // never-resolving promise to keep busy state.
    mockVerify.mockReturnValueOnce(new Promise(() => {}) as never);
    const vitals = [makeVital({ id: 5 })];
    render(<VerificationInbox vitals={vitals} uuid={UUID} onReviewed={jest.fn()} />);

    const verifyBtn = screen.getByRole("button", { name: "تأیید" });
    fireEvent.click(verifyBtn);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "در حال تأیید…" })).toBeDisabled();
      expect(screen.getByRole("button", { name: "رد" })).toBeDisabled();
    });
  });
});

// ─────────────────────────────────────────────────────────────
// (ز) verify 409 → Persian "already verified" message
// ─────────────────────────────────────────────────────────────
describe("VerificationInbox — 409 handling", () => {
  it("shows «قبلاً تأیید شده» message when verify returns 409", async () => {
    mockVerify.mockRejectedValueOnce(new ApiError(409, "already verified", "conflict"));
    const onReviewed = jest.fn();
    const vitals = [makeVital({ id: 9 })];
    render(<VerificationInbox vitals={vitals} uuid={UUID} onReviewed={onReviewed} />);

    fireEvent.click(screen.getByRole("button", { name: "تأیید" }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("این مورد قبلاً تأیید شده است."),
    );
    // onReviewed NOT called on error → item stays
    expect(onReviewed).not.toHaveBeenCalled();
    // buttons re-enabled
    expect(screen.getByRole("button", { name: "تأیید" })).not.toBeDisabled();
  });
});

// ─────────────────────────────────────────────────────────────
// (د) discrepancy hint
// ─────────────────────────────────────────────────────────────
describe("VerificationInbox — discrepancy hint (render)", () => {
  it("shows the hint when self-report fbs diverges >30% from latest clinic value", () => {
    const vitals = [
      makeVital({ id: 1, type: "fbs", value: 220 }),                                  // pending self
      makeVital({ id: 2, type: "fbs", value: 130, source: "clinic", verified: true,  // clinic
                  measured_at: "2026-06-20T08:00:00" }),
    ];
    render(<VerificationInbox vitals={vitals} uuid={UUID} onReviewed={jest.fn()} />);
    // 220 vs 130 → 69% diff > 30% → hint visible, showing the clinic value 130
    const note = screen.getByRole("note");
    expect(note).toHaveTextContent("اختلافِ چشمگیر با آخرین مقدارِ مطب");
    expect(note).toHaveTextContent("۱۳۰");
  });

  it("does NOT show the hint when self-report fbs is close to clinic value", () => {
    const vitals = [
      makeVital({ id: 1, type: "fbs", value: 135 }),                                  // pending self
      makeVital({ id: 2, type: "fbs", value: 130, source: "clinic", verified: true,  // clinic
                  measured_at: "2026-06-20T08:00:00" }),
    ];
    render(<VerificationInbox vitals={vitals} uuid={UUID} onReviewed={jest.fn()} />);
    // 135 vs 130 → ~3.8% diff < 30% → no hint
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────
// (ح) discrepancyHint — pure-function unit tests
// ─────────────────────────────────────────────────────────────
describe("discrepancyHint (pure)", () => {
  it("returns null when there is no clinic reading of the same type", () => {
    const pending = makeVital({ id: 1, type: "fbs", value: 300 });
    expect(discrepancyHint(pending, [pending])).toBeNull();
  });

  it("ignores other self-reports as the comparison baseline", () => {
    const pending = makeVital({ id: 1, type: "fbs", value: 300 });
    const otherSelf = makeVital({ id: 2, type: "fbs", value: 100, source: "patient_self" });
    // No clinic baseline → null even though values diverge.
    expect(discrepancyHint(pending, [pending, otherSelf])).toBeNull();
  });

  it("ignores a rejected clinic-like reading as the baseline", () => {
    const pending = makeVital({ id: 1, type: "fbs", value: 300 });
    const rejectedClinic = makeVital({
      id: 2, type: "fbs", value: 100, source: "clinic",
      verified: false, rejected_at: "2026-06-25T09:00:00",
    });
    expect(discrepancyHint(pending, [pending, rejectedClinic])).toBeNull();
  });

  it("flags bp_systolic when absolute diff > 20 mmHg", () => {
    const pending = makeVital({ id: 1, type: "bp_systolic", value: 160, unit: "mmHg" });
    const clinic = makeVital({
      id: 2, type: "bp_systolic", value: 130, unit: "mmHg",
      source: "clinic", verified: true, measured_at: "2026-06-20T08:00:00",
    });
    expect(discrepancyHint(pending, [pending, clinic])).toContain("اختلافِ چشمگیر");
  });

  it("does NOT flag bp_systolic when diff <= 20 mmHg", () => {
    const pending = makeVital({ id: 1, type: "bp_systolic", value: 145, unit: "mmHg" });
    const clinic = makeVital({
      id: 2, type: "bp_systolic", value: 130, unit: "mmHg",
      source: "clinic", verified: true, measured_at: "2026-06-20T08:00:00",
    });
    expect(discrepancyHint(pending, [pending, clinic])).toBeNull();
  });

  it("picks the most-recent clinic reading by measured_at", () => {
    const pending = makeVital({ id: 1, type: "fbs", value: 90 });
    const oldClinic = makeVital({
      id: 2, type: "fbs", value: 300, source: "clinic", verified: true,
      measured_at: "2026-05-01T08:00:00",
    });
    const newClinic = makeVital({
      id: 3, type: "fbs", value: 95, source: "clinic", verified: true,
      measured_at: "2026-06-20T08:00:00",
    });
    // 90 vs newest (95) → ~5% < 30% → null (must use newest, not the old 300).
    expect(discrepancyHint(pending, [pending, oldClinic, newClinic])).toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────
// (ه) three-state badges in the recent-vitals table
// ─────────────────────────────────────────────────────────────
describe("RecentVitalsTable — three-state badges", () => {
  it("labels an approved self-report as «خوداظهارِ تأییدشده»", () => {
    const vitals = [makeVital({ id: 1, verified: true })]; // self approved
    render(<RecentVitalsTable vitals={vitals} />);
    expect(screen.getByText("خوداظهارِ تأییدشده")).toBeInTheDocument();
  });

  it("labels a rejected self-report as «ردشده»", () => {
    const vitals = [
      makeVital({ id: 1, verified: false, rejected_at: "2026-06-25T09:00:00" }),
    ];
    render(<RecentVitalsTable vitals={vitals} />);
    expect(screen.getByText("ردشده")).toBeInTheDocument();
  });

  it("shows the raw source for clinic readings (no self-report badge)", () => {
    const vitals = [makeVital({ id: 1, source: "clinic", verified: true })];
    render(<RecentVitalsTable vitals={vitals} />);
    expect(screen.queryByText("خوداظهارِ تأییدشده")).not.toBeInTheDocument();
    expect(screen.getByText("clinic")).toBeInTheDocument();
  });

  it("renders empty-note when there are no vitals", () => {
    render(<RecentVitalsTable vitals={[]} />);
    expect(screen.getByText("هیچ ویتالی ثبت نشده است.")).toBeInTheDocument();
  });
});
