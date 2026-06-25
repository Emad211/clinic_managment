/**
 * تست‌های jest برای PatientCardShare — افزونهٔ staffِ کارتِ بیمار (قدم ۴۸، خوشهٔ J)
 *
 * سناریوها:
 *   (الف) صدورِ توکن → لینک نمایش داده شود
 *   (ب)  دکمهٔ «کپیِ لینکِ کارت» کار کند (navigator.clipboard.writeText صدا زده شود)
 *   (ج)  دکمهٔ «ارسالِ پیامک» disabled باشد + هیچ ارسالِ واقعی/فراخوانیِ SMS نشود
 *   (د)  نوتِ KYC کنارِ دکمهٔ SMS دیده شود
 *   (ه)  خطای صدور → پیامِ خطا، نه crash
 */

import React from "react";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { ApiError, type CardTokenOut } from "@/lib/api";

// ─── مک‌کردنِ api.ts — فقط issueCardToken ────────────────────
jest.mock("@/lib/api", () => {
  const actual = jest.requireActual("@/lib/api");
  return {
    ...actual,
    issueCardToken: jest.fn(),
  };
});

import { issueCardToken } from "@/lib/api";
const mockIssue = issueCardToken as jest.MockedFunction<typeof issueCardToken>;

import { PatientCardShare } from "@/components/PatientCardShare";

// ─── Helpers ─────────────────────────────────────────────────

function makeTokenOut(overrides: Partial<CardTokenOut> = {}): CardTokenOut {
  return {
    token: "tok_ABC123xyz",
    expires_at: "2026-06-26T18:00:00",
    card_url: "/card/tok_ABC123xyz",
    ...overrides,
  };
}

const UUID = "11111111-1111-1111-1111-111111111111";

beforeEach(() => {
  mockIssue.mockReset();
});

// ─── (الف) صدورِ توکن → لینک نمایش داده شود ──────────────────

describe("PatientCardShare — صدورِ توکن", () => {
  it("کلیکِ صدور → لینکِ کارت نمایش داده می‌شود", async () => {
    mockIssue.mockResolvedValueOnce(makeTokenOut());
    render(<PatientCardShare uuid={UUID} />);

    fireEvent.click(screen.getByTestId("card-issue-btn"));

    await waitFor(() =>
      expect(screen.getByTestId("card-token-box")).toBeInTheDocument(),
    );

    const field = screen.getByTestId("card-link-field") as HTMLInputElement;
    // لینک باید path توکن را داشته باشد
    expect(field.value).toContain("/card/tok_ABC123xyz");
  });

  it("issueCardToken دقیقاً با uuid فراخوانی می‌شود", async () => {
    mockIssue.mockResolvedValueOnce(makeTokenOut());
    render(<PatientCardShare uuid={UUID} />);

    fireEvent.click(screen.getByTestId("card-issue-btn"));

    await waitFor(() => expect(mockIssue).toHaveBeenCalledWith(UUID));
  });

  it("هیچ PHI (کد ملی) در لینک نیست — فقط توکن", async () => {
    mockIssue.mockResolvedValueOnce(makeTokenOut());
    render(<PatientCardShare uuid={UUID} />);

    fireEvent.click(screen.getByTestId("card-issue-btn"));

    await waitFor(() =>
      expect(screen.getByTestId("card-link-field")).toBeInTheDocument(),
    );

    const field = screen.getByTestId("card-link-field") as HTMLInputElement;
    expect(field.value).not.toMatch(/\d{10}/); // کد ملی ۱۰ رقمی
    expect(field.value).not.toMatch(/09\d{9}/); // شمارهٔ موبایل
  });
});

// ─── (ب) کپیِ لینک کار کند ──────────────────────────────────

describe("PatientCardShare — کپیِ لینک", () => {
  it("کلیکِ کپی → navigator.clipboard.writeText با لینک صدا زده می‌شود", async () => {
    mockIssue.mockResolvedValueOnce(makeTokenOut());

    const writeText = jest.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    render(<PatientCardShare uuid={UUID} />);
    fireEvent.click(screen.getByTestId("card-issue-btn"));

    await waitFor(() =>
      expect(screen.getByTestId("card-copy-btn")).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByTestId("card-copy-btn"));

    await waitFor(() => expect(writeText).toHaveBeenCalled());
    // متنِ کپی‌شده باید path توکن را داشته باشد
    expect(writeText.mock.calls[0][0]).toContain("/card/tok_ABC123xyz");
  });

  it("بعد از کپی برچسبِ دکمه به «کپی شد» تغییر می‌کند", async () => {
    mockIssue.mockResolvedValueOnce(makeTokenOut());
    const writeText = jest.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    render(<PatientCardShare uuid={UUID} />);
    fireEvent.click(screen.getByTestId("card-issue-btn"));

    await waitFor(() =>
      expect(screen.getByTestId("card-copy-btn")).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByTestId("card-copy-btn"));

    await waitFor(() =>
      expect(screen.getByTestId("card-copy-btn")).toHaveTextContent("کپی شد"),
    );
  });
});

// ─── (ج) دکمهٔ SMS — گِیت‌شده، disabled، بدونِ ارسالِ واقعی ───

describe("PatientCardShare — دکمهٔ SMSِ گِیت‌شده", () => {
  it("دکمهٔ ارسالِ پیامک disabled است", async () => {
    mockIssue.mockResolvedValueOnce(makeTokenOut());
    render(<PatientCardShare uuid={UUID} />);

    fireEvent.click(screen.getByTestId("card-issue-btn"));

    await waitFor(() =>
      expect(screen.getByTestId("card-sms-btn")).toBeInTheDocument(),
    );

    const smsBtn = screen.getByTestId("card-sms-btn") as HTMLButtonElement;
    expect(smsBtn).toBeDisabled();
    expect(smsBtn).toHaveAttribute("aria-disabled", "true");
  });

  it("کلیک روی دکمهٔ SMSِ disabled هیچ فراخوانیِ APIـی ایجاد نمی‌کند", async () => {
    mockIssue.mockResolvedValueOnce(makeTokenOut());

    // اگر تابعِ ارسالِ SMSـی روی api وجود داشته باشد، نباید صدا زده شود.
    // هیچ تابعِ SMS برای کارت ساخته نشده — این تست تضمین می‌کند چنین چیزی صدا زده نمی‌شود.
    render(<PatientCardShare uuid={UUID} />);
    fireEvent.click(screen.getByTestId("card-issue-btn"));

    await waitFor(() =>
      expect(screen.getByTestId("card-sms-btn")).toBeInTheDocument(),
    );

    const callsBefore = mockIssue.mock.calls.length;
    fireEvent.click(screen.getByTestId("card-sms-btn"));
    // disabled button: هیچ صدور مجددی هم نباید رخ دهد
    expect(mockIssue.mock.calls.length).toBe(callsBefore);
  });
});

// ─── (د) نوتِ KYC دیده شود ──────────────────────────────────

describe("PatientCardShare — نوتِ KYC", () => {
  it("نوتِ KYC کنارِ دکمهٔ SMS دیده می‌شود", async () => {
    mockIssue.mockResolvedValueOnce(makeTokenOut());
    render(<PatientCardShare uuid={UUID} />);

    fireEvent.click(screen.getByTestId("card-issue-btn"));

    await waitFor(() =>
      expect(screen.getByTestId("card-sms-gate-note")).toBeInTheDocument(),
    );

    const note = screen.getByTestId("card-sms-gate-note");
    expect(note).toHaveTextContent("احراز هویت");
    expect(note).toHaveTextContent("KYC");
  });

  it("دکمهٔ SMS با aria-describedby به نوتِ KYC اشاره می‌کند", async () => {
    mockIssue.mockResolvedValueOnce(makeTokenOut());
    render(<PatientCardShare uuid={UUID} />);

    fireEvent.click(screen.getByTestId("card-issue-btn"));

    await waitFor(() =>
      expect(screen.getByTestId("card-sms-btn")).toBeInTheDocument(),
    );

    const smsBtn = screen.getByTestId("card-sms-btn");
    const note = screen.getByTestId("card-sms-gate-note");
    expect(smsBtn).toHaveAttribute("aria-describedby", note.id);
  });
});

// ─── (ه) خطای صدور → پیامِ خطا، نه crash ─────────────────────

describe("PatientCardShare — خطا", () => {
  it("خطای صدور → پیامِ خطا (نه crash)", async () => {
    mockIssue.mockRejectedValueOnce(new ApiError(500, "Server Error"));

    expect(() => render(<PatientCardShare uuid={UUID} />)).not.toThrow();

    fireEvent.click(screen.getByTestId("card-issue-btn"));

    await waitFor(() =>
      expect(screen.getByTestId("card-share-error")).toBeInTheDocument(),
    );

    expect(screen.getByTestId("card-share-error")).toHaveTextContent("ناموفق");
  });

  it("قبل از صدور هیچ token-box نمایش داده نمی‌شود", () => {
    render(<PatientCardShare uuid={UUID} />);
    expect(screen.queryByTestId("card-token-box")).not.toBeInTheDocument();
  });
});
