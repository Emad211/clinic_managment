/**
 * تست‌های jest برای صفحهٔ /card/[token] — کارتِ بیمارِ عمومی
 *
 * سناریوها:
 *   (الف) رندرِ ویتال‌ها با رنگِ وضعیتِ درست + ارقامِ فارسی
 *   (ب)  next_appointment=null → «—» بدونِ crash
 *   (ج)  ۴۰۴ → پیامِ دوستانه، نه crash
 *   (د)  هیچ national_id/PHI در خروجی نباشد
 *   (ه)  عمومی بودن (getCard بدونِ Authorization header)
 *   (و)  vitals=[] → پیامِ «ثبت نشده» بدونِ crash
 *   (ز)  نامِ کوچک در سلام
 */

import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { ApiError, type CardResponse } from "@/lib/api";

// ─── مک‌کردنِ next/navigation ────────────────────────────────
jest.mock("next/navigation", () => ({
  useParams: jest.fn(),
  useRouter: jest.fn(() => ({ push: jest.fn() })),
  usePathname: jest.fn(() => "/card/test-token"),
}));

import { useParams } from "next/navigation";

// ─── مک‌کردنِ api.ts ────────────────────────────────────────
// فقط getCard مک می‌شود. بقیهٔ صادراتِ api.ts واقعی می‌مانند.
jest.mock("@/lib/api", () => {
  const actual = jest.requireActual("@/lib/api");
  return {
    ...actual,
    getCard: jest.fn(),
  };
});

import { getCard } from "@/lib/api";
const mockGetCard = getCard as jest.MockedFunction<typeof getCard>;

// ─── import صفحه (بعد از mock) ───────────────────────────────
import PatientCardPage from "@/app/card/[token]/page";

// ─── Helpers ─────────────────────────────────────────────────

function setupToken(token: string) {
  (useParams as jest.Mock).mockReturnValue({ token });
}

function makeCardResponse(overrides: Partial<CardResponse> = {}): CardResponse {
  return {
    first_name: "علی",
    clinic_name: "درمانگاهِ سیب",
    vitals: [
      { key: "fbs", label: "قند ناشتا", value: 130, unit: "mg/dL", status: "warn" },
      { key: "sbp", label: "فشار سیستول", value: 125, unit: "mmHg", status: "ok" },
    ],
    next_appointment: "2026-07-15",
    framing: "پیشنهاد — تأیید با پزشک",
    ...overrides,
  };
}

// ─── (الف) رندرِ ویتال‌ها با رنگِ وضعیت + ارقامِ فارسی ───────

describe("PatientCardPage — رندرِ پایه", () => {
  beforeEach(() => {
    setupToken("abc123");
  });

  it("ویتال‌ها را رندر می‌کند", async () => {
    mockGetCard.mockResolvedValueOnce(makeCardResponse());
    render(<PatientCardPage />);

    await waitFor(() =>
      expect(screen.getByTestId("vital-card-fbs")).toBeInTheDocument()
    );

    expect(screen.getByTestId("vital-card-sbp")).toBeInTheDocument();
  });

  it("مقدارِ ویتال را با ارقامِ فارسی نمایش می‌دهد (warn=۱۳۰)", async () => {
    mockGetCard.mockResolvedValueOnce(makeCardResponse());
    render(<PatientCardPage />);

    await waitFor(() =>
      expect(screen.getByTestId("vital-value-fbs")).toBeInTheDocument()
    );

    // 130 → ۱۳۰ (ارقامِ فارسی)
    expect(screen.getByTestId("vital-value-fbs")).toHaveTextContent("۱۳۰");
  });

  it("ویتالِ ok با رنگِ درست (data-status=ok)", async () => {
    mockGetCard.mockResolvedValueOnce(makeCardResponse());
    render(<PatientCardPage />);

    await waitFor(() =>
      expect(screen.getByTestId("vital-card-sbp")).toBeInTheDocument()
    );

    expect(screen.getByTestId("vital-card-sbp")).toHaveAttribute("data-status", "ok");
  });

  it("ویتالِ warn با رنگِ درست (data-status=warn)", async () => {
    mockGetCard.mockResolvedValueOnce(makeCardResponse());
    render(<PatientCardPage />);

    await waitFor(() =>
      expect(screen.getByTestId("vital-card-fbs")).toBeInTheDocument()
    );

    expect(screen.getByTestId("vital-card-fbs")).toHaveAttribute("data-status", "warn");
  });

  it("ویتالِ danger با data-status=danger", async () => {
    mockGetCard.mockResolvedValueOnce(
      makeCardResponse({
        vitals: [
          { key: "hba1c", label: "هموگلوبین گلیکوزیله", value: 11.5, unit: "%", status: "danger" },
        ],
      })
    );
    render(<PatientCardPage />);

    await waitFor(() =>
      expect(screen.getByTestId("vital-card-hba1c")).toBeInTheDocument()
    );

    expect(screen.getByTestId("vital-card-hba1c")).toHaveAttribute("data-status", "danger");
  });

  it("برچسبِ وضعیت «احتیاط» برای warn نمایش می‌دهد", async () => {
    mockGetCard.mockResolvedValueOnce(makeCardResponse());
    render(<PatientCardPage />);

    await waitFor(() =>
      expect(screen.getByTestId("vital-status-fbs")).toBeInTheDocument()
    );

    expect(screen.getByTestId("vital-status-fbs")).toHaveTextContent("احتیاط");
  });

  it("برچسبِ وضعیت «عادی» برای ok نمایش می‌دهد", async () => {
    mockGetCard.mockResolvedValueOnce(makeCardResponse());
    render(<PatientCardPage />);

    await waitFor(() =>
      expect(screen.getByTestId("vital-status-sbp")).toBeInTheDocument()
    );

    expect(screen.getByTestId("vital-status-sbp")).toHaveTextContent("عادی");
  });

  it("نامِ کوچک در سلام نمایش می‌دهد", async () => {
    mockGetCard.mockResolvedValueOnce(makeCardResponse({ first_name: "مریم" }));
    render(<PatientCardPage />);

    await waitFor(() =>
      expect(screen.getByTestId("card-greeting")).toBeInTheDocument()
    );

    expect(screen.getByTestId("card-greeting")).toHaveTextContent("مریم");
  });

  it("framing را نمایش می‌دهد", async () => {
    mockGetCard.mockResolvedValueOnce(makeCardResponse());
    render(<PatientCardPage />);

    await waitFor(() =>
      expect(screen.getByTestId("card-framing")).toBeInTheDocument()
    );

    expect(screen.getByTestId("card-framing")).toHaveTextContent("پیشنهاد — تأیید با پزشک");
  });
});

// ─── (ب) next_appointment=null → «—» بدونِ crash ─────────────

describe("PatientCardPage — next_appointment=null", () => {
  beforeEach(() => {
    setupToken("abc123");
  });

  it("next_appointment=null → «—» بدونِ crash", async () => {
    mockGetCard.mockResolvedValueOnce(
      makeCardResponse({ next_appointment: null })
    );

    expect(() => render(<PatientCardPage />)).not.toThrow();

    await waitFor(() =>
      expect(screen.getByTestId("card-next-appointment")).toBeInTheDocument()
    );

    expect(screen.getByTestId("card-next-appointment")).toHaveTextContent("—");
  });

  it("next_appointment با تاریخِ Jalali (ارقامِ فارسی)", async () => {
    mockGetCard.mockResolvedValueOnce(
      makeCardResponse({ next_appointment: "2026-07-15" })
    );
    render(<PatientCardPage />);

    await waitFor(() =>
      expect(screen.getByTestId("card-next-appointment")).toBeInTheDocument()
    );

    // 2026-07-15 → ۱۴۰۵/۰۴/۲۴ — باید رقمِ فارسی داشته باشد
    const el = screen.getByTestId("card-next-appointment");
    expect(el.textContent).toMatch(/[۰-۹]/);
    // نباید «—» باشد
    expect(el).not.toHaveTextContent("—");
  });
});

// ─── (ج) ۴۰۴ → پیامِ دوستانه، نه crash ──────────────────────

describe("PatientCardPage — ۴۰۴ / خطا", () => {
  beforeEach(() => {
    setupToken("expired-token");
  });

  it("۴۰۴ → پیامِ دوستانهٔ فارسی نمایش می‌دهد", async () => {
    mockGetCard.mockRejectedValueOnce(new ApiError(404, "Not Found", "not_found"));

    expect(() => render(<PatientCardPage />)).not.toThrow();

    await waitFor(() =>
      expect(screen.getByTestId("card-expired-message")).toBeInTheDocument()
    );

    // پیامِ دوستانه — نه stack trace
    const el = screen.getByTestId("card-expired-message");
    expect(el).toHaveTextContent("منقضی");
    expect(el).toHaveTextContent("درمانگاه");
  });

  it("۴۰۴ crash نمی‌کند", async () => {
    mockGetCard.mockRejectedValueOnce(new ApiError(404, "Not Found"));
    expect(() => render(<PatientCardPage />)).not.toThrow();
    // کافی است که رندرِ اولیه (loading state) بدونِ throw باشد
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("خطای غیر ۴۰۴ → پیامِ خطا (نه crash)", async () => {
    mockGetCard.mockRejectedValueOnce(new ApiError(500, "Server Error"));

    expect(() => render(<PatientCardPage />)).not.toThrow();

    await waitFor(() =>
      // هر alert‌ای که رندر شده باشد
      expect(screen.getByRole("alert")).toBeInTheDocument()
    );
  });
});

// ─── (د) هیچ national_id / PHI در خروجی ─────────────────────

describe("PatientCardPage — نبودِ PHI", () => {
  beforeEach(() => {
    setupToken("abc123");
  });

  it("national_id در DOM نیست", async () => {
    mockGetCard.mockResolvedValueOnce(makeCardResponse());
    render(<PatientCardPage />);

    await waitFor(() =>
      expect(screen.getByTestId("card-vitals-section")).toBeInTheDocument()
    );

    const body = document.body.innerHTML;
    // هیچ الگوی ۱۰-رقمیِ کد ملی نباشد
    expect(body).not.toMatch(/\d{10}/);
  });

  it("اطلاعاتِ تماس (phone) در DOM نیست", async () => {
    mockGetCard.mockResolvedValueOnce(makeCardResponse());
    render(<PatientCardPage />);

    await waitFor(() =>
      expect(screen.getByTestId("card-vitals-section")).toBeInTheDocument()
    );

    const body = document.body.innerHTML;
    // شمارهٔ تلفن ایرانی معمولاً با 09 شروع می‌شود
    expect(body).not.toMatch(/09\d{9}/);
  });

  it("پاسخِ API حاویِ national_id نیست (بررسیِ mock)", () => {
    const resp = makeCardResponse();
    // CardResponse نباید national_id داشته باشد
    expect(Object.keys(resp)).not.toContain("national_id");
    expect(Object.keys(resp)).not.toContain("phone_number");
    expect(Object.keys(resp)).not.toContain("phone");
  });
});

// ─── (ه) عمومی بودن: بدونِ Authorization ────────────────────

describe("PatientCardPage — عمومی بودن", () => {
  beforeEach(() => {
    setupToken("public-token");
  });

  it("getCard بدونِ JWT فراخوانی می‌شود", async () => {
    mockGetCard.mockResolvedValueOnce(makeCardResponse());
    render(<PatientCardPage />);

    await waitFor(() =>
      expect(mockGetCard).toHaveBeenCalled()
    );

    // getCard باید دقیقاً با token فراخوانی شده باشد (بدونِ JWT)
    expect(mockGetCard).toHaveBeenCalledWith("public-token");
    // تابعِ getCard هیچ‌وقت getToken را call نمی‌کند — این را در تستِ جداگانه verify کنید
  });

  it("useAuth / hook احراز هویت در صفحهٔ کارت import نمی‌شود", () => {
    // صفحهٔ کارت نباید از useAuth یا getToken import کند.
    // بررسیِ ایستا: فایلِ page.tsx نباید import statement آن‌ها را داشته باشد.
    const fs = require("fs");
    const path = require("path");
    const pageSource = fs.readFileSync(
      path.resolve(__dirname, "../src/app/card/[token]/page.tsx"),
      "utf-8"
    ) as string;

    // فقط خطوطِ import را بررسی کن (نه کامنت‌ها)
    const importLines = pageSource
      .split("\n")
      .filter((line: string) => line.trim().startsWith("import "));

    const hasUseAuthImport = importLines.some((line: string) =>
      line.includes("useAuth")
    );
    const hasGetTokenImport = importLines.some((line: string) =>
      line.includes("getToken")
    );

    expect(hasUseAuthImport).toBe(false);
    expect(hasGetTokenImport).toBe(false);
  });
});

// ─── (و) vitals=[] → پیامِ «ثبت نشده» بدونِ crash ──────────

describe("PatientCardPage — vitals خالی", () => {
  beforeEach(() => {
    setupToken("abc123");
  });

  it("vitals=[] → رندر بدونِ crash", async () => {
    mockGetCard.mockResolvedValueOnce(makeCardResponse({ vitals: [] }));
    expect(() => render(<PatientCardPage />)).not.toThrow();

    await waitFor(() =>
      expect(screen.getByTestId("card-no-vitals")).toBeInTheDocument()
    );
  });

  it("vitals=[] → پیامِ «ثبت نشده»", async () => {
    mockGetCard.mockResolvedValueOnce(makeCardResponse({ vitals: [] }));
    render(<PatientCardPage />);

    await waitFor(() =>
      expect(screen.getByTestId("card-no-vitals")).toBeInTheDocument()
    );

    expect(screen.getByTestId("card-no-vitals")).toHaveTextContent("ثبت نشده");
  });
});

// ─── (ح) یادآورِ غربالگری — reminder_message (قدم ۴۸، خوشهٔ J) ──

describe("PatientCardPage — یادآورِ غربالگری (reminder_message)", () => {
  beforeEach(() => {
    setupToken("abc123");
  });

  const REMINDER_TEXT =
    "چند موردِ مراقبتِ دوره‌ای به موعد رسیده است؛ برای هماهنگی با کلینیک تماس بگیرید.";

  // (الف) reminder_message غیرnull → بخشِ یادآور با همان متن رندر شود
  it("reminder_message غیرnull → بخشِ یادآور با همان متنِ دقیق رندر می‌شود", async () => {
    mockGetCard.mockResolvedValueOnce(
      makeCardResponse({ reminder_message: REMINDER_TEXT }),
    );
    render(<PatientCardPage />);

    await waitFor(() =>
      expect(screen.getByTestId("card-reminder-section")).toBeInTheDocument(),
    );

    // متن دقیقاً همان رشتهٔ بک‌اند — هیچ‌چیز اضافه/استنتاج نشده
    expect(screen.getByTestId("card-reminder-text")).toHaveTextContent(
      REMINDER_TEXT,
    );
  });

  // (ب) reminder_message=null → بخشِ یادآور نباشد
  it("reminder_message=null → بخشِ یادآور رندر نمی‌شود", async () => {
    mockGetCard.mockResolvedValueOnce(
      makeCardResponse({ reminder_message: null }),
    );
    render(<PatientCardPage />);

    // صبر کن صفحه بارگذاری شود (vitals دیده شوند)
    await waitFor(() =>
      expect(screen.getByTestId("card-vitals-section")).toBeInTheDocument(),
    );

    expect(screen.queryByTestId("card-reminder-section")).not.toBeInTheDocument();
  });

  // (ب-۲) فیلدِ غایب (undefined، backward-compat با بک‌اندِ فعلی) → بخش نباشد
  it("reminder_message غایب (undefined) → بخشِ یادآور رندر نمی‌شود", async () => {
    mockGetCard.mockResolvedValueOnce(makeCardResponse());
    render(<PatientCardPage />);

    await waitFor(() =>
      expect(screen.getByTestId("card-vitals-section")).toBeInTheDocument(),
    );

    expect(screen.queryByTestId("card-reminder-section")).not.toBeInTheDocument();
  });

  // (ب-۳) رشتهٔ خالی → بخش نباشد (خالیِ falsy)
  it("reminder_message رشتهٔ خالی → بخشِ یادآور رندر نمی‌شود", async () => {
    mockGetCard.mockResolvedValueOnce(
      makeCardResponse({ reminder_message: "" }),
    );
    render(<PatientCardPage />);

    await waitFor(() =>
      expect(screen.getByTestId("card-vitals-section")).toBeInTheDocument(),
    );

    expect(screen.queryByTestId("card-reminder-section")).not.toBeInTheDocument();
  });

  // (ج) یادآور رنگِ danger/هم‌سطحِ ویتالِ خطر نگیرد — کلاسِ خنثی
  it("بخشِ یادآور کلاسِ danger نمی‌گیرد و role=note دارد (نه alert)", async () => {
    mockGetCard.mockResolvedValueOnce(
      makeCardResponse({ reminder_message: REMINDER_TEXT }),
    );
    render(<PatientCardPage />);

    await waitFor(() =>
      expect(screen.getByTestId("card-reminder-section")).toBeInTheDocument(),
    );

    const section = screen.getByTestId("card-reminder-section");
    // CSS modules در jest هش نمی‌شوند → className خامِ کلاس‌هاست (identity-obj-proxy)
    expect(section.className).not.toMatch(/danger/i);
    expect(section.className).not.toMatch(/statusDanger/);
    // لحن informational، نه هشدار
    expect(section).toHaveAttribute("role", "note");
    expect(section).not.toHaveAttribute("role", "alert");
  });

  // یادآور هم‌سطحِ ویتالِ danger نباشد: هیچ data-status=danger روی بخشِ یادآور نباشد
  it("بخشِ یادآور data-status=danger ندارد", async () => {
    mockGetCard.mockResolvedValueOnce(
      makeCardResponse({ reminder_message: REMINDER_TEXT }),
    );
    render(<PatientCardPage />);

    await waitFor(() =>
      expect(screen.getByTestId("card-reminder-section")).toBeInTheDocument(),
    );

    expect(screen.getByTestId("card-reminder-section")).not.toHaveAttribute(
      "data-status",
      "danger",
    );
  });

  // یادآور هرگز نام/عدد اضافه نکند: فقط همان رشته، بدونِ first_name در آن
  it("بخشِ یادآور فقط همان رشته است — نامِ بیمار را تکرار نمی‌کند", async () => {
    mockGetCard.mockResolvedValueOnce(
      makeCardResponse({ first_name: "بهرام", reminder_message: REMINDER_TEXT }),
    );
    render(<PatientCardPage />);

    await waitFor(() =>
      expect(screen.getByTestId("card-reminder-text")).toBeInTheDocument(),
    );

    const text = screen.getByTestId("card-reminder-text").textContent ?? "";
    expect(text).toBe(REMINDER_TEXT);
    expect(text).not.toContain("بهرام");
  });
});

// ─── (ز) ارقامِ فارسی واقعی ─────────────────────────────────

describe("PatientCardPage — ارقامِ فارسی", () => {
  beforeEach(() => {
    setupToken("abc123");
  });

  it("مقدارِ عددیِ ویتال با رقمِ فارسی نمایش می‌دهد", async () => {
    mockGetCard.mockResolvedValueOnce(
      makeCardResponse({
        vitals: [
          { key: "fbs", label: "قند", value: 130, unit: "mg/dL", status: "warn" },
        ],
      })
    );
    render(<PatientCardPage />);

    await waitFor(() =>
      expect(screen.getByTestId("vital-value-fbs")).toBeInTheDocument()
    );

    const valueEl = screen.getByTestId("vital-value-fbs");
    // ۱۳۰ باید رقمِ فارسی باشد
    expect(valueEl.textContent).toMatch(/[۰-۹]/);
    // نباید ASCII digits باشد
    expect(valueEl.textContent).not.toMatch(/^[0-9]/);
  });

  it("مقدارِ اعشاری با ارقامِ فارسی (۱۱.۵ → ۱۱.۵)", async () => {
    mockGetCard.mockResolvedValueOnce(
      makeCardResponse({
        vitals: [
          { key: "hba1c", label: "هموگلوبین", value: 11.5, unit: "%", status: "danger" },
        ],
      })
    );
    render(<PatientCardPage />);

    await waitFor(() =>
      expect(screen.getByTestId("vital-value-hba1c")).toBeInTheDocument()
    );

    const valueEl = screen.getByTestId("vital-value-hba1c");
    expect(valueEl.textContent).toMatch(/[۰-۹]/);
  });
});
