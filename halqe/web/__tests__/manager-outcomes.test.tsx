/**
 * Manager Outcomes dashboard — /manager/outcomes  (cluster K, step 50).
 *
 * Renders the ACTUAL page component to lock down the honesty contract:
 *   (a) both regions + all 5 sections render with mocked responses;
 *   (b) a null rate renders the "دادهٔ ناکافی" copy — NOT 0;
 *   (c) the global non-causal banner is present;
 *   (d) a non-manager (role !== "manager") sees «دسترسی محدود»;
 *   (e) a control-trend bucket with null pct renders a gap/grey (img with
 *       "دادهٔ ناکافی" label), not a zero point;
 *   (f) acceptance (process) and outcome (state) live in separate regions —
 *       never combined in one card/chart.
 *
 * Mocks:
 *   - @/lib/api       : 5 client fns + getRole + ApiError (no real HTTP)
 *   - @/hooks/useAuth : ready=true, logout spy
 *   - next/navigation : usePathname → fixed string
 *   - @/components/Nav: lightweight stub (avoids Link/css internals)
 */

import React from "react";
import { render, screen, waitFor, act, within } from "@testing-library/react";
import "@testing-library/jest-dom";

// ── localStorage stub (api.ts reads token on import) ──
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (k: string) => store[k] ?? null,
    setItem: (k: string, v: string) => {
      store[k] = v;
    },
    removeItem: (k: string) => {
      delete store[k];
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

// ── Module mocks (declared before page import) ──
jest.mock("@/lib/api", () => ({
  getRole: jest.fn(),
  getSuggestionStats: jest.fn(),
  getConversion: jest.fn(),
  getLapsedReturn: jest.fn(),
  getCohortOutcomes: jest.fn(),
  getControlTrend: jest.fn(),
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
  usePathname: () => "/manager/outcomes",
}));

// Lightweight Nav stub
jest.mock("@/components/Nav", () => {
  const MockNav = ({ showManagerLinks }: { showManagerLinks?: boolean }) => (
    <header data-testid="nav" data-manager-links={showManagerLinks ? "yes" : "no"}>
      nav
    </header>
  );
  MockNav.displayName = "MockNav";
  return MockNav;
});

jest.mock("./outcomes.module.css", () => ({}), { virtual: true });

import ManagerOutcomesPage from "@/app/manager/outcomes/page";
import {
  getRole,
  getSuggestionStats,
  getConversion,
  getLapsedReturn,
  getCohortOutcomes,
  getControlTrend,
} from "@/lib/api";

// ─────────────────────────────────────────────────────────────
// Fixtures
// ─────────────────────────────────────────────────────────────

const STATS_OK = {
  generated_at: "2026-06-25T10:00:00+03:30",
  min_n_for_rate: 5,
  framing: "نرخ‌ها از میانِ اقداماتِ پزشک — نه معیارِ کیفیتِ قاعده.",
  rules: [
    {
      rule_code: "T2-MED-01",
      n_accepted: 8,
      n_dismissed: 2,
      n_pending: 1,
      n_acted: 10,
      n_fired_patient_days: 40,
      acceptance_rate_of_acted: 80,
      rate_reliable: true,
      impression_acceptance_rate: 20,
      impression_rate_reliable: true,
      last_action_at: "2026-06-20T09:00:00+03:30",
    },
  ],
};

// All process metrics NULL → must show "دادهٔ ناکافی", never 0
const STATS_NULL = {
  generated_at: "2026-06-25T10:00:00+03:30",
  min_n_for_rate: 5,
  framing: "نرخ‌ها از میانِ اقداماتِ پزشک.",
  rules: [
    {
      rule_code: "T2-MED-99",
      n_accepted: 1,
      n_dismissed: 1,
      n_pending: 0,
      n_acted: 2, // < min_n → overall null
      n_fired_patient_days: 3,
      acceptance_rate_of_acted: null,
      rate_reliable: false,
      impression_acceptance_rate: null,
      impression_rate_reliable: false,
      last_action_at: null,
    },
  ],
};

const CONV_OK = {
  window_days: 30,
  generated: 120,
  generated_eligible: 90,
  resolved_done: 50,
  resolved_dismissed: 10,
  open_eligible: 30,
  to_visit: 40,
  contact_rate: 66.7,
  visit_rate_of_reached: 80,
  overall_conversion: 44.4,
  n_sufficient: true,
  framing: "بدونِ گروهِ کنترل — همبستگی نه علیت.",
};

const CONV_NULL = {
  window_days: 30,
  generated: 12,
  generated_eligible: 8, // < 30 → rates null
  resolved_done: 2,
  resolved_dismissed: 1,
  open_eligible: 5,
  to_visit: 1,
  contact_rate: null,
  visit_rate_of_reached: null,
  overall_conversion: null,
  n_sufficient: false,
  framing: "بدونِ گروهِ کنترل — همبستگی نه علیت.",
};

const LAPSED_OK = {
  denominator: 60,
  returned: 24,
  return_rate: 40,
  lapse_window_days: 180,
  return_window_days: 60,
  min_n: 20,
  framing: "توصیفی — نه اثرِ علّی.",
};

const LAPSED_NULL = {
  denominator: 8, // < min_n → rate null
  returned: 2,
  return_rate: null,
  lapse_window_days: 180,
  return_window_days: 60,
  min_n: 20,
  framing: "توصیفی — نه اثرِ علّی.",
};

const COHORT_OK = {
  tenant_id: 1,
  framing: "نمایِ تک‌گروهی، غیرعلّی (regression-to-mean).",
  caveat: "تمایزِ engagement-holdout از clinical-holdout.",
  n_sufficient: 1,
  conditions: [
    {
      condition_code: "DM",
      condition_label: "دیابت",
      anchor: "hba1c",
      n_cohort: 50,
      n_baseline: 40,
      reason: null,
      metrics: [
        {
          metric_key: "hba1c",
          metric_type: "mean_delta",
          unit: "٪",
          direction: "low",
          n_baseline: 40,
          m3: { n: 35, mean: 7.8, n_paired: 32, delta: -0.4, reason: null },
          m6: { n: 12, mean: null, n_paired: 8, delta: null, reason: "window_n_insufficient" },
        },
      ],
      stratification: null,
    },
  ],
};

const TREND_OK = {
  min_n: 10,
  framing: "روندِ توصیفی — بدونِ گروهِ کنترل.",
  buckets: [
    { ym: "2026-03", condition: "DM", assessable_n: 30, controlled_n: 18, pct_controlled: 60 },
    // null bucket → must render a gap/grey, NOT a zero point
    { ym: "2026-04", condition: "DM", assessable_n: 4, controlled_n: 1, pct_controlled: null },
    { ym: "2026-05", condition: "DM", assessable_n: 28, controlled_n: 20, pct_controlled: 71.4 },
  ],
};

function mockAllOk() {
  (getRole as jest.Mock).mockReturnValue("manager");
  (getSuggestionStats as jest.Mock).mockResolvedValue(STATS_OK);
  (getConversion as jest.Mock).mockResolvedValue(CONV_OK);
  (getLapsedReturn as jest.Mock).mockResolvedValue(LAPSED_OK);
  (getCohortOutcomes as jest.Mock).mockResolvedValue(COHORT_OK);
  (getControlTrend as jest.Mock).mockResolvedValue(TREND_OK);
}

async function renderAndSettle() {
  await act(async () => {
    render(<ManagerOutcomesPage />);
  });
  await waitFor(() => {
    expect(screen.queryByText("در حال بارگذاری…")).not.toBeInTheDocument();
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  localStorageMock.clear();
  localStorageMock.setItem("halqe_token", "test-token");
});

// ─────────────────────────────────────────────────────────────
// (a) both regions + 5 sections render
// ─────────────────────────────────────────────────────────────

describe("ManagerOutcomesPage — render (manager, all data present)", () => {
  beforeEach(mockAllOk);

  it("renders both regions: «فعالیت و پذیرشِ ما» and «وضعیتِ بیماران»", async () => {
    await renderAndSettle();
    expect(screen.getByRole("region", { name: "فعالیت و پذیرشِ ما" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "وضعیتِ بیماران" })).toBeInTheDocument();
  });

  it("renders all 5 sections", async () => {
    await renderAndSettle();
    // Region A
    expect(screen.getByRole("region", { name: "پذیرشِ پیشنهادها" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "قیفِ پیگیری به ویزیت" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "بازگشتِ بیمارانِ غیبت‌کرده" })).toBeInTheDocument();
    // Region B
    expect(screen.getByRole("region", { name: "وضعیتِ توصیفیِ کوهورت" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "روندِ زمانیِ کنترلِ بیماری" })).toBeInTheDocument();
  });

  it("calls all 5 endpoints exactly once", async () => {
    await renderAndSettle();
    expect(getSuggestionStats).toHaveBeenCalledTimes(1);
    expect(getConversion).toHaveBeenCalledTimes(1);
    expect(getLapsedReturn).toHaveBeenCalledTimes(1);
    expect(getCohortOutcomes).toHaveBeenCalledTimes(1);
    expect(getControlTrend).toHaveBeenCalledTimes(1);
  });

  it("passes showManagerLinks to Nav for managers", async () => {
    await renderAndSettle();
    expect(screen.getByTestId("nav")).toHaveAttribute("data-manager-links", "yes");
  });
});

// ─────────────────────────────────────────────────────────────
// (c) global non-causal banner present
// ─────────────────────────────────────────────────────────────

describe("ManagerOutcomesPage — non-causal banner", () => {
  beforeEach(mockAllOk);

  it("shows the global non-causal banner", async () => {
    await renderAndSettle();
    const banner = screen.getByRole("note", { name: "هشدارِ غیرعلّی بودنِ داده‌ها" });
    expect(banner).toBeInTheDocument();
    expect(banner).toHaveTextContent("این داده‌ها علّی نیستند");
    expect(banner).toHaveTextContent(/گروهِ کنترل\/holdout/);
  });
});

// ─────────────────────────────────────────────────────────────
// (b) null rate → «دادهٔ ناکافی», never 0
// ─────────────────────────────────────────────────────────────

describe("ManagerOutcomesPage — NULL handling (insufficient data, never 0)", () => {
  beforeEach(() => {
    (getRole as jest.Mock).mockReturnValue("manager");
    (getSuggestionStats as jest.Mock).mockResolvedValue(STATS_NULL);
    (getConversion as jest.Mock).mockResolvedValue(CONV_NULL);
    (getLapsedReturn as jest.Mock).mockResolvedValue(LAPSED_NULL);
    (getCohortOutcomes as jest.Mock).mockResolvedValue(COHORT_OK);
    (getControlTrend as jest.Mock).mockResolvedValue(TREND_OK);
  });

  it("renders «دادهٔ ناکافی» copy for null acceptance, funnel and lapsed-return", async () => {
    await renderAndSettle();
    const insufficient = screen.getAllByText(/دادهٔ ناکافی برای نتیجه‌گیری/);
    // at least: acceptance + 3 funnel rows + lapsed-return + cohort m6 window
    expect(insufficient.length).toBeGreaterThanOrEqual(5);
  });

  it("does NOT render a «۰٪» / «0٪» value where data is insufficient (acceptance card)", async () => {
    await renderAndSettle();
    const acceptance = screen.getByRole("region", { name: "پذیرشِ پیشنهادها" });
    // The acceptance card must NOT show a literal zero percent value.
    expect(within(acceptance).queryByText("۰٪")).not.toBeInTheDocument();
    expect(within(acceptance).queryByText("0٪")).not.toBeInTheDocument();
    // It MUST show the insufficient copy instead.
    expect(within(acceptance).getByText(/دادهٔ ناکافی برای نتیجه‌گیری/)).toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────
// (e) control-trend null bucket → gap/grey img, not a zero point
// ─────────────────────────────────────────────────────────────

describe("ManagerOutcomesPage — control-trend null bucket renders a gap", () => {
  beforeEach(mockAllOk);

  it("labels the null month as «دادهٔ ناکافی» inside the SVG (title), not 0", async () => {
    await renderAndSettle();
    const trendRegion = screen.getByRole("region", { name: "روندِ زمانیِ کنترلِ بیماری" });
    // The whole month chart is an img with an aria-label; the null bucket has a
    // <title> reading "دادهٔ ناکافی". Query the SVG title text directly.
    const titles = trendRegion.querySelectorAll("title");
    const titleTexts = Array.from(titles).map((t) => t.textContent ?? "");
    const hasNullTitle = titleTexts.some((t) => t.includes("دادهٔ ناکافی"));
    expect(hasNullTitle).toBe(true);
    // The null bucket must NOT be coerced into an exact "۰٪ کنترل‌شده" value.
    // (anchored: a leading non-digit / start, so «۶۰٪» does not match — only a
    //  standalone zero would). This proves null ≠ a zero data point.
    const hasZeroPct = titleTexts.some((t) => /(^|[^۰-۹])۰٪ کنترل‌شده/.test(t));
    expect(hasZeroPct).toBe(false);
  });
});

// ─────────────────────────────────────────────────────────────
// (f) acceptance (process) and outcome (state) live in SEPARATE regions
// ─────────────────────────────────────────────────────────────

describe("ManagerOutcomesPage — process and outcome are separated (no false causality)", () => {
  beforeEach(mockAllOk);

  it("acceptance is inside region A and NOT inside region B", async () => {
    await renderAndSettle();
    const regionA = screen.getByRole("region", { name: "فعالیت و پذیرشِ ما" });
    const regionB = screen.getByRole("region", { name: "وضعیتِ بیماران" });

    // Acceptance card lives in Region A
    expect(within(regionA).getByRole("region", { name: "پذیرشِ پیشنهادها" })).toBeInTheDocument();
    expect(within(regionB).queryByRole("region", { name: "پذیرشِ پیشنهادها" })).not.toBeInTheDocument();

    // Cohort outcome card lives in Region B
    expect(within(regionB).getByRole("region", { name: "وضعیتِ توصیفیِ کوهورت" })).toBeInTheDocument();
    expect(within(regionA).queryByRole("region", { name: "وضعیتِ توصیفیِ کوهورت" })).not.toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────
// (d) non-manager → access restricted
// ─────────────────────────────────────────────────────────────

describe("ManagerOutcomesPage — non-manager access gate", () => {
  beforeEach(() => {
    (getRole as jest.Mock).mockReturnValue("staff");
  });

  it("shows «دسترسی محدود» and does NOT fetch any outcome endpoint", async () => {
    await act(async () => {
      render(<ManagerOutcomesPage />);
    });
    expect(screen.getByText("دسترسی محدود")).toBeInTheDocument();
    expect(getSuggestionStats).not.toHaveBeenCalled();
    expect(getConversion).not.toHaveBeenCalled();
    expect(getLapsedReturn).not.toHaveBeenCalled();
    expect(getCohortOutcomes).not.toHaveBeenCalled();
    expect(getControlTrend).not.toHaveBeenCalled();
  });

  it("does NOT pass showManagerLinks to Nav for staff", async () => {
    await act(async () => {
      render(<ManagerOutcomesPage />);
    });
    expect(screen.getByTestId("nav")).toHaveAttribute("data-manager-links", "no");
  });
});
