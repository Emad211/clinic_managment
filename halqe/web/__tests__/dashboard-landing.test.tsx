/**
 * Dashboard — role-aware landing (step 86, U3).
 *
 * Renders the ACTUAL dashboard page to lock the role-gated landing contract:
 *   (a) manager → «اقدامِ اولِ روز» links to /control-room and the manager
 *       block (control-room / outcomes / engagement cards) is present;
 *   (b) staff → «اقدامِ اولِ روز» links to /queue and the manager block is
 *       ABSENT;
 *   (c) the care StatCards (بیماران / پیگیری‌ها) render for BOTH roles
 *       (care must not be withheld).
 *
 * Mocks:
 *   - @/lib/api       : getRole + apiGetPatients + apiGetWorklist + ApiError
 *   - @/hooks/useAuth : ready=true, logout spy
 *   - next/navigation : usePathname → fixed string
 *   - @/components/Nav: lightweight stub
 *   - @/lib/jalali    : toFarsiDigits passthrough
 */

import React from "react";
import { render, screen, waitFor, act } from "@testing-library/react";
import "@testing-library/jest-dom";

// ── localStorage stub ──
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

jest.mock("@/lib/api", () => ({
  getRole: jest.fn(),
  apiGetPatients: jest.fn(),
  apiGetWorklist: jest.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.name = "ApiError";
      this.status = status;
    }
  },
}));

const mockLogout = jest.fn();
jest.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ ready: true, logout: mockLogout }),
}));

jest.mock("next/navigation", () => ({
  usePathname: () => "/dashboard",
}));

// next/link → passthrough anchor (preserves href for assertions)
jest.mock("next/link", () => {
  const MockLink = ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: React.ReactNode;
  }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  );
  MockLink.displayName = "MockLink";
  return MockLink;
});

jest.mock("@/components/Nav", () => {
  const MockNav = () => <header data-testid="nav">nav</header>;
  MockNav.displayName = "MockNav";
  return MockNav;
});

jest.mock("./dashboard.module.css", () => ({}), { virtual: true });
jest.mock("@/app/dashboard/dashboard.module.css", () => ({}), { virtual: true });

import DashboardPage from "@/app/dashboard/page";
import { getRole, apiGetPatients, apiGetWorklist } from "@/lib/api";

beforeEach(() => {
  jest.clearAllMocks();
  localStorageMock.clear();
  localStorageMock.setItem("halqe_token", "test-token");
  (apiGetPatients as jest.Mock).mockResolvedValue({ total: 12, items: [] });
  (apiGetWorklist as jest.Mock).mockResolvedValue({ total: 3, items: [] });
});

async function renderAndSettle() {
  await act(async () => {
    render(<DashboardPage />);
  });
  await waitFor(() => expect(getRole).toHaveBeenCalled());
}

describe("DashboardPage — manager landing", () => {
  beforeEach(() => {
    (getRole as jest.Mock).mockReturnValue("manager");
  });

  it("primary action links to /control-room", async () => {
    await renderAndSettle();
    const action = await screen.findByLabelText(
      "اتاقِ کنترل — بیمارانِ پراولویت",
    );
    expect(action).toHaveAttribute("href", "/control-room");
  });

  it("shows the manager block with outcomes + engagement + control-room cards", async () => {
    await renderAndSettle();
    const block = await screen.findByRole("region", { name: "مدیریت" });
    expect(block).toBeInTheDocument();
    expect(block).toHaveTextContent("گزارشِ outcome");
    expect(block).toHaveTextContent("صفِ تعامل");
    expect(block).toHaveTextContent("اتاقِ کنترل");
  });

  it("still shows the care StatCards (بیماران / پیگیری‌ها) for managers", async () => {
    await renderAndSettle();
    expect(screen.getByRole("region", { name: "بیماران ثبت‌نام‌شده" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "پیگیری‌های سررسیدشده" })).toBeInTheDocument();
  });
});

describe("DashboardPage — staff landing", () => {
  beforeEach(() => {
    (getRole as jest.Mock).mockReturnValue("staff");
  });

  it("primary action links to /queue", async () => {
    await renderAndSettle();
    const action = await screen.findByLabelText("صف ویزیتِ امروز");
    expect(action).toHaveAttribute("href", "/queue");
  });

  it("does NOT render the manager block", async () => {
    await renderAndSettle();
    expect(screen.queryByRole("region", { name: "مدیریت" })).not.toBeInTheDocument();
  });

  it("still shows the care StatCards (بیماران / پیگیری‌ها) for staff", async () => {
    await renderAndSettle();
    expect(screen.getByRole("region", { name: "بیماران ثبت‌نام‌شده" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "پیگیری‌های سررسیدشده" })).toBeInTheDocument();
  });
});
