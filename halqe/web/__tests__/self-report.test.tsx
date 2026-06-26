/**
 * تست‌های jest برای صفحهٔ /report/[token] — فرمِ self-reportِ بیمار
 *
 * سناریوها (الزامی‌ها):
 *   (الف) رندرِ فرم + سه ورودی
 *   (ب)   batch فقط پرشده‌ها را می‌فرستد
 *   (ج)   مقدارِ خارج‌از‌بازه کلاینت‌ساید رد می‌شود
 *   (د)   ۲۰۰ → موفقیت + فرمِ مصرف‌شده
 *   (ه)   ۴۰۴/۴۲۲/۴۲۹ → پیامِ درست
 *   (و)   آفلاین → صف در localStorage
 *   (ز)   رویدادِ online → flush صف (۲۰۰ → فرمِ قفل)
 *
 * اضافه:
 *   (ح)   بدونِ PHI در URL / import
 *   (ط)   حداقل یک مقدار لازم
 *   (ی)   ارقامِ فارسی در placeholder/hint
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
import { ApiError } from "@/lib/api";

// ─── مک‌کردنِ next/navigation ────────────────────────────────
jest.mock("next/navigation", () => ({
  useParams: jest.fn(),
  useRouter: jest.fn(() => ({ push: jest.fn() })),
  usePathname: jest.fn(() => "/report/test-token"),
}));

import { useParams } from "next/navigation";

// ─── مک‌کردنِ submitReport در api.ts ────────────────────────
jest.mock("@/lib/api", () => {
  const actual = jest.requireActual("@/lib/api");
  return {
    ...actual,
    submitReport: jest.fn(),
  };
});

import { submitReport } from "@/lib/api";
const mockSubmitReport = submitReport as jest.MockedFunction<
  typeof submitReport
>;

// ─── import صفحه (بعد از mock) ───────────────────────────────
import SelfReportPage from "@/app/report/[token]/page";

// ─── Helper: تنظیمِ token ─────────────────────────────────────
function setupToken(token: string) {
  (useParams as jest.Mock).mockReturnValue({ token });
}

// ─── Helper: localStorage mock ───────────────────────────────
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: jest.fn<string | null, [string]>((key: string) => store[key] ?? null),
    setItem: jest.fn((key: string, value: string) => {
      store[key] = value;
    }),
    removeItem: jest.fn((key: string) => {
      delete store[key];
    }),
    clear: jest.fn(() => {
      store = {};
    }),
  };
})();

Object.defineProperty(window, "localStorage", { value: localStorageMock });

// ─── Helper: online/offline ───────────────────────────────────
function setOnline(online: boolean) {
  Object.defineProperty(navigator, "onLine", {
    configurable: true,
    get: () => online,
  });
}

// ─── Helper: fill input ───────────────────────────────────────
function fillInput(testId: string, value: string) {
  const el = screen.getByTestId(testId);
  fireEvent.change(el, { target: { value } });
}

// ─── beforeEach ──────────────────────────────────────────────
beforeEach(() => {
  setupToken("test-token-abc");
  mockSubmitReport.mockReset();
  localStorageMock.clear();
  // mock‌های قبلی getItem را هم پاک کن — از تداخلِ تست‌های (ز) جلوگیری می‌کند
  localStorageMock.getItem.mockImplementation((_key: string): string | null => null);
  setOnline(true);
  // suppress act() warnings برای async state
  jest.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  jest.restoreAllMocks();
});

// ════════════════════════════════════════════════════════════
// (الف) رندرِ فرم + سه ورودی
// ════════════════════════════════════════════════════════════

describe("(الف) رندرِ فرم + سه ورودی", () => {
  it("فرمِ self-report رندر می‌شود", () => {
    render(<SelfReportPage />);
    expect(screen.getByTestId("report-form")).toBeInTheDocument();
  });

  it("هر سه inputِ عددی وجود دارد", () => {
    render(<SelfReportPage />);
    expect(screen.getByTestId("input-fbs")).toBeInTheDocument();
    expect(screen.getByTestId("input-bp_systolic")).toBeInTheDocument();
    expect(screen.getByTestId("input-bp_diastolic")).toBeInTheDocument();
  });

  it("inputها inputMode=numeric دارند", () => {
    render(<SelfReportPage />);
    expect(screen.getByTestId("input-fbs")).toHaveAttribute(
      "inputMode",
      "numeric",
    );
    expect(screen.getByTestId("input-bp_systolic")).toHaveAttribute(
      "inputMode",
      "numeric",
    );
  });

  it("دکمهٔ ارسال وجود دارد", () => {
    render(<SelfReportPage />);
    expect(screen.getByTestId("report-submit-btn")).toBeInTheDocument();
  });

  it("عنوانِ صفحه فارسی است", () => {
    render(<SelfReportPage />);
    expect(screen.getByText("گزارشِ اندازه‌گیری")).toBeInTheDocument();
  });

  it("صفحه dir=rtl دارد", () => {
    render(<SelfReportPage />);
    // page div باید dir=rtl داشته باشد
    const page = screen.getByTestId("report-form").closest("[dir='rtl']");
    expect(page).toBeInTheDocument();
  });
});

// ════════════════════════════════════════════════════════════
// (ب) batch فقط پرشده‌ها
// ════════════════════════════════════════════════════════════

describe("(ب) batch فقط پرشده‌ها را می‌فرستد", () => {
  it("فقط fbs پر شده → submitReport با readings=[{type:fbs}] فراخوانی", async () => {
    mockSubmitReport.mockResolvedValueOnce({
      status: "ok",
      accepted: [{ type: "fbs", value: 120 }],
      count: 1,
      message: "ثبت شد",
    });

    render(<SelfReportPage />);
    fillInput("input-fbs", "120");
    fireEvent.click(screen.getByTestId("report-submit-btn"));

    await waitFor(() => expect(mockSubmitReport).toHaveBeenCalledTimes(1));

    const [calledToken, calledReadings] = mockSubmitReport.mock.calls[0];
    expect(calledToken).toBe("test-token-abc");
    expect(calledReadings).toHaveLength(1);
    expect(calledReadings[0]).toMatchObject({ type: "fbs", value: 120 });
    // bp_systolic و bp_diastolic نباید در readings باشند
    expect(
      calledReadings.find(
        (r: { type: string }) => r.type === "bp_systolic",
      ),
    ).toBeUndefined();
  });

  it("همهٔ سه فیلد پر شده → readings طولِ ۳ دارد", async () => {
    mockSubmitReport.mockResolvedValueOnce({
      status: "ok",
      accepted: [],
      count: 3,
      message: "ثبت شد",
    });

    render(<SelfReportPage />);
    fillInput("input-fbs", "110");
    fillInput("input-bp_systolic", "130");
    fillInput("input-bp_diastolic", "85");
    fireEvent.click(screen.getByTestId("report-submit-btn"));

    await waitFor(() => expect(mockSubmitReport).toHaveBeenCalled());

    const [, readings] = mockSubmitReport.mock.calls[0];
    expect(readings).toHaveLength(3);
  });

  it("هیچ فیلدی پر نشده → submit نمی‌شود (پیامِ خطا)", async () => {
    render(<SelfReportPage />);
    fireEvent.click(screen.getByTestId("report-submit-btn"));

    await waitFor(() =>
      expect(screen.getByTestId("error-form")).toBeInTheDocument(),
    );
    expect(mockSubmitReport).not.toHaveBeenCalled();
  });

  it("ارقامِ فارسی در ورودی parse می‌شوند (۱۲۰ → 120)", async () => {
    mockSubmitReport.mockResolvedValueOnce({
      status: "ok",
      accepted: [{ type: "fbs", value: 120 }],
      count: 1,
      message: "ثبت شد",
    });

    render(<SelfReportPage />);
    fillInput("input-fbs", "۱۲۰"); // رقمِ فارسی
    fireEvent.click(screen.getByTestId("report-submit-btn"));

    await waitFor(() => expect(mockSubmitReport).toHaveBeenCalled());

    const [, readings] = mockSubmitReport.mock.calls[0];
    expect(readings[0].value).toBe(120); // باید عددِ ASCII باشد
  });
});

// ════════════════════════════════════════════════════════════
// (ج) validation کلاینت — خارج‌از‌بازه
// ════════════════════════════════════════════════════════════

describe("(ج) validation کلاینت — خارج‌از‌بازه", () => {
  it("fbs=10 (زیرِ ۲۰) → پیامِ خطا + submitReport فراخوانی نمی‌شود", async () => {
    render(<SelfReportPage />);
    fillInput("input-fbs", "10");
    fireEvent.click(screen.getByTestId("report-submit-btn"));

    await waitFor(() =>
      expect(screen.getByTestId("error-fbs")).toBeInTheDocument(),
    );
    expect(mockSubmitReport).not.toHaveBeenCalled();
  });

  it("fbs=900 (بیشتر از ۸۰۰) → پیامِ خطا", async () => {
    render(<SelfReportPage />);
    fillInput("input-fbs", "900");
    fireEvent.click(screen.getByTestId("report-submit-btn"));

    await waitFor(() =>
      expect(screen.getByTestId("error-fbs")).toBeInTheDocument(),
    );
    expect(mockSubmitReport).not.toHaveBeenCalled();
  });

  it("bp_systolic=40 (زیرِ ۵۰) → خطا", async () => {
    render(<SelfReportPage />);
    fillInput("input-bp_systolic", "40");
    fireEvent.click(screen.getByTestId("report-submit-btn"));

    await waitFor(() =>
      expect(screen.getByTestId("error-bp_systolic")).toBeInTheDocument(),
    );
  });

  it("bp_systolic=350 (بیشتر از ۳۰۰) → خطا", async () => {
    render(<SelfReportPage />);
    fillInput("input-bp_systolic", "350");
    fireEvent.click(screen.getByTestId("report-submit-btn"));

    await waitFor(() =>
      expect(screen.getByTestId("error-bp_systolic")).toBeInTheDocument(),
    );
  });

  it("bp_diastolic=10 (زیرِ ۲۰) → خطا", async () => {
    render(<SelfReportPage />);
    fillInput("input-bp_diastolic", "10");
    fireEvent.click(screen.getByTestId("report-submit-btn"));

    await waitFor(() =>
      expect(screen.getByTestId("error-bp_diastolic")).toBeInTheDocument(),
    );
  });

  it("bp_diastolic=250 (بیشتر از ۲۰۰) → خطا", async () => {
    render(<SelfReportPage />);
    fillInput("input-bp_diastolic", "250");
    fireEvent.click(screen.getByTestId("report-submit-btn"));

    await waitFor(() =>
      expect(screen.getByTestId("error-bp_diastolic")).toBeInTheDocument(),
    );
  });

  it("مقدارِ غیرعددی → خطا", async () => {
    render(<SelfReportPage />);
    fillInput("input-fbs", "abc");
    fireEvent.click(screen.getByTestId("report-submit-btn"));

    await waitFor(() =>
      expect(screen.getByTestId("error-fbs")).toBeInTheDocument(),
    );
  });

  it("مقدارِ معتبر در بازه → خطایی نیست", async () => {
    mockSubmitReport.mockResolvedValueOnce({
      status: "ok",
      accepted: [{ type: "fbs", value: 120 }],
      count: 1,
      message: "ثبت شد",
    });

    render(<SelfReportPage />);
    fillInput("input-fbs", "120");
    fireEvent.click(screen.getByTestId("report-submit-btn"));

    await waitFor(() => expect(mockSubmitReport).toHaveBeenCalled());
    expect(screen.queryByTestId("error-fbs")).not.toBeInTheDocument();
  });
});

// ════════════════════════════════════════════════════════════
// (د) ۲۰۰ → موفقیت + فرمِ مصرف‌شده
// ════════════════════════════════════════════════════════════

describe("(د) پاسخِ ۲۰۰ — موفقیت + قفل", () => {
  it("۲۰۰ → جعبهٔ موفقیت نمایش می‌دهد", async () => {
    mockSubmitReport.mockResolvedValueOnce({
      status: "ok",
      accepted: [{ type: "fbs", value: 120 }],
      count: 1,
      message: "ثبت شد",
    });

    render(<SelfReportPage />);
    fillInput("input-fbs", "120");
    fireEvent.click(screen.getByTestId("report-submit-btn"));

    await waitFor(() =>
      expect(screen.getByTestId("report-success-box")).toBeInTheDocument(),
    );
  });

  it("۲۰۰ → پیامِ «ثبت شد» فارسی", async () => {
    mockSubmitReport.mockResolvedValueOnce({
      status: "ok",
      accepted: [],
      count: 1,
      message: "ok",
    });

    render(<SelfReportPage />);
    fillInput("input-fbs", "120");
    fireEvent.click(screen.getByTestId("report-submit-btn"));

    await waitFor(() =>
      expect(screen.getByTestId("report-success-box")).toBeInTheDocument(),
    );

    expect(screen.getByTestId("report-success-box")).toHaveTextContent("ثبت شد");
  });

  it("۲۰۰ → فرم دیگر وجود ندارد (قفل/مصرف‌شده)", async () => {
    mockSubmitReport.mockResolvedValueOnce({
      status: "ok",
      accepted: [],
      count: 1,
      message: "ok",
    });

    render(<SelfReportPage />);
    fillInput("input-fbs", "120");
    fireEvent.click(screen.getByTestId("report-submit-btn"));

    await waitFor(() =>
      expect(screen.getByTestId("report-success-box")).toBeInTheDocument(),
    );
    // فرم نباید دیگر وجود داشته باشد
    expect(screen.queryByTestId("report-form")).not.toBeInTheDocument();
  });

  it("۲۰۰ → پزشک بررسی خواهد کرد", async () => {
    mockSubmitReport.mockResolvedValueOnce({
      status: "ok",
      accepted: [],
      count: 1,
      message: "ok",
    });

    render(<SelfReportPage />);
    fillInput("input-fbs", "120");
    fireEvent.click(screen.getByTestId("report-submit-btn"));

    await waitFor(() =>
      expect(screen.getByTestId("report-success-box")).toBeInTheDocument(),
    );

    expect(screen.getByTestId("report-success-box")).toHaveTextContent(
      "پزشک",
    );
  });
});

// ════════════════════════════════════════════════════════════
// (ه) ۴۰۴/۴۲۲/۴۲۹ → پیامِ درست
// ════════════════════════════════════════════════════════════

describe("(ه) کدهای خطا — پیام‌های درست", () => {
  it("۴۰۴ → جعبهٔ expired با پیامِ لینک استفاده‌شده", async () => {
    mockSubmitReport.mockRejectedValueOnce(
      new ApiError(404, "Not Found", "not_found"),
    );

    render(<SelfReportPage />);
    fillInput("input-fbs", "120");
    fireEvent.click(screen.getByTestId("report-submit-btn"));

    await waitFor(() =>
      expect(screen.getByTestId("report-expired-box")).toBeInTheDocument(),
    );

    expect(screen.getByTestId("report-expired-box")).toHaveTextContent(
      "استفاده شده",
    );
    expect(screen.getByTestId("report-expired-box")).toHaveTextContent(
      "درمانگاه",
    );
  });

  it("۴۰۴ → فرمِ جدید نمایش نمی‌دهد", async () => {
    mockSubmitReport.mockRejectedValueOnce(new ApiError(404, "Not Found"));

    render(<SelfReportPage />);
    fillInput("input-fbs", "120");
    fireEvent.click(screen.getByTestId("report-submit-btn"));

    await waitFor(() =>
      expect(screen.getByTestId("report-expired-box")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("report-form")).not.toBeInTheDocument();
  });

  it("۴۲۲ → پیامِ خطای validation + فرم باقی است", async () => {
    mockSubmitReport.mockRejectedValueOnce(
      new ApiError(422, "مقدار خارج از بازه", "validation_error"),
    );

    render(<SelfReportPage />);
    fillInput("input-fbs", "120");
    fireEvent.click(screen.getByTestId("report-submit-btn"));

    await waitFor(() =>
      expect(screen.getByTestId("report-submit-error")).toBeInTheDocument(),
    );

    // فرم باید هنوز باشد
    expect(screen.queryByTestId("report-form")).toBeInTheDocument();
    // موفقیت نباشد
    expect(screen.queryByTestId("report-success-box")).not.toBeInTheDocument();
  });

  it("۴۲۹ → پیامِ rate-limit", async () => {
    mockSubmitReport.mockRejectedValueOnce(
      new ApiError(429, "Too Many Requests"),
    );

    render(<SelfReportPage />);
    fillInput("input-fbs", "120");
    fireEvent.click(screen.getByTestId("report-submit-btn"));

    await waitFor(() =>
      expect(screen.getByTestId("report-rate-limit")).toBeInTheDocument(),
    );

    expect(screen.getByTestId("report-rate-limit")).toHaveTextContent("کمی بعد");
  });
});

// ════════════════════════════════════════════════════════════
// (و) آفلاین → صف در localStorage
// ════════════════════════════════════════════════════════════

describe("(و) آفلاین — صف در localStorage", () => {
  beforeEach(() => {
    setOnline(false);
    localStorageMock.clear();
  });

  it("آفلاین → submitReport فراخوانی نمی‌شود", async () => {
    render(<SelfReportPage />);
    fillInput("input-fbs", "120");
    fireEvent.click(screen.getByTestId("report-submit-btn"));

    await waitFor(() =>
      expect(screen.getByTestId("report-queued-msg")).toBeInTheDocument(),
    );

    expect(mockSubmitReport).not.toHaveBeenCalled();
  });

  it("آفلاین → پیامِ «ذخیره شد» نمایش می‌دهد", async () => {
    render(<SelfReportPage />);
    fillInput("input-fbs", "120");
    fireEvent.click(screen.getByTestId("report-submit-btn"));

    await waitFor(() =>
      expect(screen.getByTestId("report-queued-msg")).toBeInTheDocument(),
    );

    expect(screen.getByTestId("report-queued-msg")).toHaveTextContent(
      "ذخیره شد",
    );
    expect(screen.getByTestId("report-queued-msg")).toHaveTextContent(
      "اتصال",
    );
  });

  it("آفلاین → داده در localStorage ذخیره می‌شود", async () => {
    render(<SelfReportPage />);
    fillInput("input-fbs", "120");
    fillInput("input-bp_systolic", "130");
    fireEvent.click(screen.getByTestId("report-submit-btn"));

    await waitFor(() =>
      expect(screen.getByTestId("report-queued-msg")).toBeInTheDocument(),
    );

    // باید در localStorage ذخیره شده باشد
    expect(localStorageMock.setItem).toHaveBeenCalledWith(
      "halqe_report_queue",
      expect.stringContaining("test-token-abc"),
    );

    // readings در صف باید درست باشند
    const savedRaw = localStorageMock.setItem.mock.calls.slice(-1)[0][1] as string;
    const queue = JSON.parse(savedRaw) as Array<{
      token: string;
      readings: Array<{ type: string; value: number }>;
    }>;
    expect(queue).toHaveLength(1);
    expect(queue[0].token).toBe("test-token-abc");
    const types = queue[0].readings.map((r) => r.type);
    expect(types).toContain("fbs");
    expect(types).toContain("bp_systolic");
    expect(types).not.toContain("bp_diastolic"); // خالی است
  });
});

// ════════════════════════════════════════════════════════════
// (ز) رویدادِ online → flush صف
// ════════════════════════════════════════════════════════════

describe("(ز) رویدادِ online — flush صف", () => {
  it("رویدادِ online → submitReport با داده‌های صف فراخوانی می‌شود", async () => {
    // ابتدا صف را پر کن
    const queueData = JSON.stringify([
      {
        token: "test-token-abc",
        readings: [{ type: "fbs", value: 150 }],
        queuedAt: Date.now(),
      },
    ]);
    localStorageMock.getItem.mockImplementation((key: string): string | null =>
      key === "halqe_report_queue" ? queueData : null,
    );

    mockSubmitReport.mockResolvedValueOnce({
      status: "ok",
      accepted: [{ type: "fbs", value: 150 }],
      count: 1,
      message: "ثبت شد",
    });

    setOnline(true);
    render(<SelfReportPage />);

    // flush باید در mount (چون آنلاین) یا رویدادِ online انجام شود
    // رویدادِ online را شبیه‌سازی کن
    await act(async () => {
      window.dispatchEvent(new Event("online"));
    });

    await waitFor(() => expect(mockSubmitReport).toHaveBeenCalled(), {
      timeout: 3000,
    });

    const [calledToken, calledReadings] = mockSubmitReport.mock.calls[0];
    expect(calledToken).toBe("test-token-abc");
    expect(calledReadings[0]).toMatchObject({ type: "fbs", value: 150 });
  });

  it("flush موفق → فرم قفل می‌شود (success phase)", async () => {
    const queueData = JSON.stringify([
      {
        token: "test-token-abc",
        readings: [{ type: "fbs", value: 150 }],
        queuedAt: Date.now(),
      },
    ]);
    localStorageMock.getItem.mockImplementation((key: string): string | null =>
      key === "halqe_report_queue" ? queueData : null,
    );

    mockSubmitReport.mockResolvedValueOnce({
      status: "ok",
      accepted: [{ type: "fbs", value: 150 }],
      count: 1,
      message: "ثبت شد",
    });

    setOnline(true);
    render(<SelfReportPage />);

    await act(async () => {
      window.dispatchEvent(new Event("online"));
    });

    await waitFor(
      () =>
        expect(screen.getByTestId("report-success-box")).toBeInTheDocument(),
      { timeout: 3000 },
    );
  });

  it("flush با ۴۰۴ → expired نمایش می‌دهد", async () => {
    const queueData = JSON.stringify([
      {
        token: "test-token-abc",
        readings: [{ type: "fbs", value: 150 }],
        queuedAt: Date.now(),
      },
    ]);
    localStorageMock.getItem.mockImplementation((key: string): string | null =>
      key === "halqe_report_queue" ? queueData : null,
    );

    mockSubmitReport.mockRejectedValueOnce(new ApiError(404, "Not Found"));

    setOnline(true);
    render(<SelfReportPage />);

    await act(async () => {
      window.dispatchEvent(new Event("online"));
    });

    await waitFor(
      () =>
        expect(screen.getByTestId("report-expired-box")).toBeInTheDocument(),
      { timeout: 3000 },
    );
  });
});

// ════════════════════════════════════════════════════════════
// (ح) بدونِ PHI — ایمنیِ معماری
// ════════════════════════════════════════════════════════════

describe("(ح) نبودِ PHI / ایمنیِ معماری", () => {
  it("صفحهٔ self-report از useAuth یا getToken import نمی‌کند", () => {
    const fs = require("fs");
    const path = require("path");
    const pageSource = fs.readFileSync(
      path.resolve(__dirname, "../src/app/report/[token]/page.tsx"),
      "utf-8",
    ) as string;

    const importLines = pageSource
      .split("\n")
      .filter((line: string) => line.trim().startsWith("import "));

    expect(
      importLines.some((line: string) => line.includes("useAuth")),
    ).toBe(false);
    expect(
      importLines.some((line: string) => line.includes("getToken")),
    ).toBe(false);
  });

  it("submitReport عمومی است (بدونِ Authorization در api.ts)", () => {
    const fs = require("fs");
    const path = require("path");
    // Cleanup step 8: submitReport now lives in its own per-domain module
    // (src/lib/api/self-report.ts); the public `@/lib/api` barrel re-exports it.
    // This source-level architecture guard reads the module that actually
    // DEFINES submitReport so the invariant (no apiFetch / no Authorization)
    // is still enforced on the real implementation.
    const apiSource = fs.readFileSync(
      path.resolve(__dirname, "../src/lib/api/self-report.ts"),
      "utf-8",
    ) as string;

    // تابعِ submitReport باید بدونِ apiFetch باشد (که JWT می‌زند)
    const submitReportSection = apiSource.slice(
      apiSource.indexOf("export async function submitReport"),
    );
    const endIdx = submitReportSection.indexOf(
      "\nexport async function",
      1,
    );
    const fnBody =
      endIdx > 0 ? submitReportSection.slice(0, endIdx) : submitReportSection;

    // کامنت‌ها را حذف کن — فقط خطوطِ کد
    const codeOnly = fnBody
      .split("\n")
      .filter((line) => !line.trim().startsWith("//"))
      .join("\n");

    // نباید از apiFetch (که JWT می‌زند) استفاده کند
    expect(codeOnly).not.toContain("apiFetch(");
    // باید از fetch مستقیم استفاده کند
    expect(codeOnly).toContain("fetch(");
    // نباید Authorization header دستی در کد (نه کامنت) باشد
    expect(codeOnly).not.toContain("Authorization");
  });

  it("national_id در DOM رندرشده نیست", async () => {
    mockSubmitReport.mockResolvedValueOnce({
      status: "ok",
      accepted: [],
      count: 1,
      message: "ok",
    });

    render(<SelfReportPage />);

    // حتی بعد از موفقیت
    fillInput("input-fbs", "120");
    fireEvent.click(screen.getByTestId("report-submit-btn"));
    await waitFor(() =>
      expect(screen.getByTestId("report-success-box")).toBeInTheDocument(),
    );

    const body = document.body.innerHTML;
    // هیچ کدِ ملیِ ۱۰-رقمی
    expect(body).not.toMatch(/\d{10}/);
    // هیچ شمارهٔ تلفنِ ایرانی
    expect(body).not.toMatch(/09\d{9}/);
  });
});

// ════════════════════════════════════════════════════════════
// (ط) حداقل یک مقدار
// ════════════════════════════════════════════════════════════

describe("(ط) حداقل یک مقدار الزامی", () => {
  it("هیچ فیلدی پر نشده → پیامِ «حداقل یک مقدار»", async () => {
    render(<SelfReportPage />);
    fireEvent.click(screen.getByTestId("report-submit-btn"));

    await waitFor(() =>
      expect(screen.getByTestId("error-form")).toBeInTheDocument(),
    );

    expect(screen.getByTestId("error-form")).toHaveTextContent("حداقل");
    expect(mockSubmitReport).not.toHaveBeenCalled();
  });

  it("یک فیلدِ معتبر → submit انجام می‌شود", async () => {
    mockSubmitReport.mockResolvedValueOnce({
      status: "ok",
      accepted: [{ type: "bp_diastolic", value: 85 }],
      count: 1,
      message: "ok",
    });

    render(<SelfReportPage />);
    fillInput("input-bp_diastolic", "85");
    fireEvent.click(screen.getByTestId("report-submit-btn"));

    await waitFor(() => expect(mockSubmitReport).toHaveBeenCalled());
    expect(screen.queryByTestId("error-form")).not.toBeInTheDocument();
  });
});

// ════════════════════════════════════════════════════════════
// (ی) hint در بازهٔ مجاز با ارقامِ فارسی
// ════════════════════════════════════════════════════════════

describe("(ی) ارقامِ فارسی در hint‌ها", () => {
  it("hint قند ناشتا حاویِ رقمِ فارسی است", () => {
    render(<SelfReportPage />);
    // hint باید حاویِ بازهٔ مجاز با رقمِ فارسی باشد
    const hints = screen.getAllByText(/بازهٔ مجاز/);
    expect(hints.length).toBeGreaterThan(0);
    // بررسیِ رقمِ فارسی
    const fbsHintEl = hints.find((el) => el.textContent?.includes("۲۰"));
    expect(fbsHintEl).toBeTruthy();
  });
});
