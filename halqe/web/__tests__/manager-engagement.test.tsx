/**
 * Manager Engagement — /manager/engagement  (cluster L, step 52).
 *
 * Renders the ACTUAL page component to lock the anti rubber-stamping +
 * simulation contract:
 *   (a) a pending card shows patient name, event_label, verbatim message,
 *       and the opt-out + consent badges;
 *   (b) approve/reject/send call the right client fns and the item leaves
 *       the queue;
 *   (c) there is NO «approve all» bulk action;
 *   (d) a successful send in simulation shows «ثبت‌شده (شبیه‌سازی)», never
 *       «ارسال شد»;
 *   (e) the persistent simulation banner is present;
 *   (f) a non-manager sees «دسترسی محدود» and fetches NOTHING;
 *   (g) settings tab: switching a channel to sms asks for confirmation;
 *   (h) a stale item (last_contact_at on/after due) shows the warning label.
 *
 * Mocks: @/lib/api, @/hooks/useAuth, next/navigation, @/components/Nav, css.
 */

import React from "react";
import {
  render,
  screen,
  waitFor,
  act,
  within,
  fireEvent,
} from "@testing-library/react";
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
  getEngagementApprovals: jest.fn(),
  approveEngagementApproval: jest.fn(),
  rejectEngagementApproval: jest.fn(),
  sendEngagementApproval: jest.fn(),
  getEngagementEvents: jest.fn(),
  updateEngagementEvent: jest.fn(),
  getEngagementSettings: jest.fn(),
  updateEngagementSettings: jest.fn(),
  ENGAGEMENT_CHANNEL_LABEL: {
    sms: "پیامک",
    worklist: "کارِ روزانه",
    both: "هردو",
    off: "خاموش",
  },
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
  usePathname: () => "/manager/engagement",
}));

jest.mock("@/components/Nav", () => {
  const MockNav = ({ showManagerLinks }: { showManagerLinks?: boolean }) => (
    <header data-testid="nav" data-manager-links={showManagerLinks ? "yes" : "no"}>
      nav
    </header>
  );
  MockNav.displayName = "MockNav";
  return MockNav;
});

jest.mock("./engagement.module.css", () => ({}), { virtual: true });

import ManagerEngagementPage from "@/app/manager/engagement/page";
import {
  getRole,
  getEngagementApprovals,
  approveEngagementApproval,
  rejectEngagementApproval,
  sendEngagementApproval,
  getEngagementEvents,
  updateEngagementEvent,
  getEngagementSettings,
} from "@/lib/api";

// ─────────────────────────────────────────────────────────────
// Fixtures
// ─────────────────────────────────────────────────────────────

const VERBATIM =
  "سلام؛ زمانِ آزمایشِ دوره‌ایِ شما فرارسیده است. لطفاً با کلینیک تماس بگیرید.";

const APPROVAL_PENDING = {
  id: 1,
  patient_link_id: 10,
  event_key: "lab_due",
  event_label: "آزمایشِ دوره‌ای",
  patient_name: "زهرا محمدی",
  message: VERBATIM,
  channel: "sms",
  due_date: "2026-06-20",
  status: "pending",
  sms_opt_out: true, // → red opt-out badge
  sms_consent: false, // → consent warning badge
  last_contact_at: null,
  decided_by: null,
  decided_at: null,
};

const APPROVAL_APPROVED = {
  id: 2,
  patient_link_id: 11,
  event_key: "appt_reminder",
  event_label: "یادآوریِ نوبت",
  patient_name: "علی رضایی",
  message: "نوبتِ شما فردا است.",
  channel: "sms",
  due_date: "2026-06-25",
  status: "approved", // → send enabled
  sms_opt_out: false,
  sms_consent: true,
  last_contact_at: null,
  decided_by: "admin",
  decided_at: "2026-06-24T10:00:00+03:30",
};

// Stale: last contact on/after the due date → warning label.
const APPROVAL_STALE = {
  id: 3,
  patient_link_id: 12,
  event_key: "lab_due",
  event_label: "آزمایشِ دوره‌ای",
  patient_name: "مریم کریمی",
  message: "یادآوریِ آزمایش.",
  channel: "sms",
  due_date: "2026-06-10",
  status: "pending",
  sms_opt_out: false,
  sms_consent: true,
  last_contact_at: "2026-06-15T09:00:00+03:30", // newer than due
  decided_by: null,
  decided_at: null,
};

const EVENTS = [
  {
    event_key: "lab_due",
    label: "آزمایشِ دوره‌ای",
    category: "monitoring",
    channel: "worklist", // OFF sms → toggling to sms must confirm
    cooldown_days: 30,
  },
  {
    event_key: "appt_reminder",
    label: "یادآوریِ نوبت",
    category: "appointment",
    channel: "both",
    cooldown_days: 1,
  },
];

const SETTINGS = {
  quiet_start: "08:00",
  quiet_end: "21:00",
  daily_cap: 3,
};

function mockManagerQueue(items: unknown[]) {
  (getRole as jest.Mock).mockReturnValue("manager");
  (getEngagementApprovals as jest.Mock).mockResolvedValue({
    items,
    total: items.length,
  });
  (getEngagementEvents as jest.Mock).mockResolvedValue(EVENTS);
  (getEngagementSettings as jest.Mock).mockResolvedValue(SETTINGS);
}

async function renderAndSettle() {
  await act(async () => {
    render(<ManagerEngagementPage />);
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
// (a) pending card content
// ─────────────────────────────────────────────────────────────

describe("ManagerEngagementPage — pending card content", () => {
  beforeEach(() => mockManagerQueue([APPROVAL_PENDING]));

  it("shows patient name, human event_label (not raw key), and verbatim message", async () => {
    await renderAndSettle();
    expect(screen.getByText("زهرا محمدی")).toBeInTheDocument();
    expect(screen.getByText("آزمایشِ دوره‌ای")).toBeInTheDocument();
    // The raw event_key must NOT be shown.
    expect(screen.queryByText("lab_due")).not.toBeInTheDocument();
    // Verbatim message present, exactly.
    expect(screen.getByText(VERBATIM)).toBeInTheDocument();
  });

  it("shows the opt-out and no-consent badges", async () => {
    await renderAndSettle();
    expect(screen.getByText("انصراف از پیامک")).toBeInTheDocument();
    expect(screen.getByText("بدونِ رضایتِ پیامک")).toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────
// (c) NO «approve all» bulk action
// ─────────────────────────────────────────────────────────────

describe("ManagerEngagementPage — no rubber-stamping", () => {
  beforeEach(() => mockManagerQueue([APPROVAL_PENDING, APPROVAL_STALE]));

  it("has no «approve all» / bulk approve control", async () => {
    await renderAndSettle();
    expect(screen.queryByText(/تأیید همه/)).not.toBeInTheDocument();
    expect(screen.queryByText(/تاییدِ همه/)).not.toBeInTheDocument();
    // Each card has its own تأیید button — one per pending item.
    expect(screen.getAllByRole("button", { name: "تأیید" })).toHaveLength(2);
  });
});

// ─────────────────────────────────────────────────────────────
// (b) approve / reject call the right fns + exit the queue
// ─────────────────────────────────────────────────────────────

describe("ManagerEngagementPage — approve/reject exit the queue", () => {
  it("approve calls approveEngagementApproval and removes the card", async () => {
    mockManagerQueue([APPROVAL_PENDING]);
    (approveEngagementApproval as jest.Mock).mockResolvedValue({
      ...APPROVAL_PENDING,
      status: "approved",
    });
    await renderAndSettle();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "تأیید" }));
    });

    expect(approveEngagementApproval).toHaveBeenCalledWith(1);
    await waitFor(() => {
      expect(screen.queryByText("زهرا محمدی")).not.toBeInTheDocument();
    });
  });

  it("reject opens a modal, calls rejectEngagementApproval, and removes the card", async () => {
    mockManagerQueue([APPROVAL_PENDING]);
    (rejectEngagementApproval as jest.Mock).mockResolvedValue({
      ...APPROVAL_PENDING,
      status: "rejected",
    });
    await renderAndSettle();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "رد" }));
    });
    // modal confirm button
    const dialog = screen.getByRole("dialog", { name: "ردِ پیام" });
    await act(async () => {
      fireEvent.click(within(dialog).getByRole("button", { name: "ردِ پیام" }));
    });

    expect(rejectEngagementApproval).toHaveBeenCalledWith(1, undefined);
    await waitFor(() => {
      expect(screen.queryByText("زهرا محمدی")).not.toBeInTheDocument();
    });
  });
});

// ─────────────────────────────────────────────────────────────
// (d) send in simulation → «ثبت‌شده (شبیه‌سازی)», never «ارسال شد»
// ─────────────────────────────────────────────────────────────

describe("ManagerEngagementPage — send is simulated", () => {
  it("send requires confirm, then shows «ثبت‌شده (شبیه‌سازی)» and never «ارسال شد»", async () => {
    mockManagerQueue([APPROVAL_APPROVED]);
    (sendEngagementApproval as jest.Mock).mockResolvedValue({ ok: true });
    await renderAndSettle();

    // The approved card's send button is enabled.
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "ارسال" }));
    });
    const dialog = screen.getByRole("dialog", { name: "تأییدِ ارسال" });
    await act(async () => {
      fireEvent.click(within(dialog).getByRole("button", { name: "ثبتِ ارسال" }));
    });

    expect(sendEngagementApproval).toHaveBeenCalledWith(2);
    await waitFor(() => {
      expect(screen.getByText("ثبت‌شده (شبیه‌سازی)")).toBeInTheDocument();
    });
    expect(screen.queryByText("ارسال شد")).not.toBeInTheDocument();
  });

  it("send blocked by opt_out shows «ردشده: انصراف»", async () => {
    mockManagerQueue([APPROVAL_APPROVED]);
    (sendEngagementApproval as jest.Mock).mockResolvedValue({
      ok: false,
      reason: "opt_out",
    });
    await renderAndSettle();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "ارسال" }));
    });
    const dialog = screen.getByRole("dialog", { name: "تأییدِ ارسال" });
    await act(async () => {
      fireEvent.click(within(dialog).getByRole("button", { name: "ثبتِ ارسال" }));
    });

    await waitFor(() => {
      expect(screen.getByText("ردشده: انصراف")).toBeInTheDocument();
    });
  });

  it("disables send for a pending (not yet approved) item", async () => {
    mockManagerQueue([APPROVAL_PENDING]);
    await renderAndSettle();
    expect(screen.getByRole("button", { name: "ارسال" })).toBeDisabled();
  });
});

// ─────────────────────────────────────────────────────────────
// (e) persistent simulation banner
// ─────────────────────────────────────────────────────────────

describe("ManagerEngagementPage — simulation banner", () => {
  beforeEach(() => mockManagerQueue([APPROVAL_PENDING]));

  it("shows the persistent simulation banner", async () => {
    await renderAndSettle();
    const banner = screen.getByRole("note", { name: "هشدارِ حالتِ شبیه‌سازی" });
    expect(banner).toBeInTheDocument();
    expect(banner).toHaveTextContent("حالتِ شبیه‌سازی");
    expect(banner).toHaveTextContent(/KYC/);
  });
});

// ─────────────────────────────────────────────────────────────
// (h) stale item warning
// ─────────────────────────────────────────────────────────────

describe("ManagerEngagementPage — stale contact warning", () => {
  it("shows «ممکن است دیگر لازم نباشد» when last contact is on/after due", async () => {
    mockManagerQueue([APPROVAL_STALE]);
    await renderAndSettle();
    expect(screen.getByText("ممکن است دیگر لازم نباشد")).toBeInTheDocument();
  });

  it("does NOT show the stale label for a never-contacted item", async () => {
    mockManagerQueue([APPROVAL_PENDING]); // last_contact_at null
    await renderAndSettle();
    expect(
      screen.queryByText("ممکن است دیگر لازم نباشد"),
    ).not.toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────
// empty queue → positive message, not an error
// ─────────────────────────────────────────────────────────────

describe("ManagerEngagementPage — empty queue", () => {
  it("shows a positive «صف خالی است» message, not an error", async () => {
    mockManagerQueue([]);
    await renderAndSettle();
    expect(screen.getByText("صف خالی است")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────
// (g) settings tab: channel → sms asks for confirmation
// ─────────────────────────────────────────────────────────────

describe("ManagerEngagementPage — settings channel change", () => {
  beforeEach(() => mockManagerQueue([APPROVAL_PENDING]));

  it("switching a worklist event to پیامک opens a confirm dialog", async () => {
    await renderAndSettle();

    // Switch to the settings tab.
    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: /تنظیمات/ }));
    });
    await waitFor(() => {
      expect(screen.getByText("کانالِ هر رویداد")).toBeInTheDocument();
    });

    // The lab_due row's channel is currently worklist; click پیامک.
    const smsButtons = screen.getAllByRole("button", { name: "پیامک" });
    await act(async () => {
      fireEvent.click(smsButtons[0]);
    });

    // A confirm dialog appears — and the PUT did NOT fire yet.
    expect(
      screen.getByRole("dialog", { name: "تأییدِ تغییرِ کانال" }),
    ).toBeInTheDocument();
    expect(updateEngagementEvent).not.toHaveBeenCalled();

    // Confirm → the PUT fires with the new channel.
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "بله، تغییر بده" }));
    });
    expect(updateEngagementEvent).toHaveBeenCalledWith("lab_due", {
      channel: "sms",
      cooldown_days: 30,
    });
  });
});

// ─────────────────────────────────────────────────────────────
// (f) non-manager → access restricted, no fetch
// ─────────────────────────────────────────────────────────────

describe("ManagerEngagementPage — non-manager gate", () => {
  beforeEach(() => {
    (getRole as jest.Mock).mockReturnValue("staff");
  });

  it("shows «دسترسی محدود» and fetches nothing", async () => {
    await act(async () => {
      render(<ManagerEngagementPage />);
    });
    expect(screen.getByText("دسترسی محدود")).toBeInTheDocument();
    expect(getEngagementApprovals).not.toHaveBeenCalled();
    expect(getEngagementEvents).not.toHaveBeenCalled();
    expect(getEngagementSettings).not.toHaveBeenCalled();
  });

  it("does NOT pass showManagerLinks to Nav for staff", async () => {
    await act(async () => {
      render(<ManagerEngagementPage />);
    });
    expect(screen.getByTestId("nav")).toHaveAttribute(
      "data-manager-links",
      "no",
    );
  });
});
