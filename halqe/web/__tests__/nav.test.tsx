/** Role gating, active paths and responsive interaction for the unified Nav. */
import React from "react";
import { fireEvent, render, screen, waitFor, act, within } from "@testing-library/react";
import "@testing-library/jest-dom";

const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (k: string) => store[k] ?? null,
    setItem: (k: string, v: string) => { store[k] = v; },
    removeItem: (k: string) => { delete store[k]; },
    clear: () => { store = {}; },
  };
})();
Object.defineProperty(globalThis, "localStorage", { value: localStorageMock, writable: true });

jest.mock("@/lib/api", () => ({ getRole: jest.fn() }));
jest.mock("next/link", () => {
  const MockLink = ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>{children}</a>
  );
  MockLink.displayName = "MockLink";
  return MockLink;
});
jest.mock("@/components/nav.module.css", () => ({}), { virtual: true });

import Nav from "@/components/Nav";
import { getRole } from "@/lib/api";

const MANAGER_LABELS = ["اتاقِ کنترل", "گزارشِ outcome", "صفِ تعامل", "تنظیمات مالی"];
const ACCOUNTING_LABELS = ["پذیرش", "فاکتورها", "پرستاری", "پروسیجر", "تسویه"];
const UNIVERSAL_LABELS = ["داشبورد", "صف ویزیت", "بیماران", "پیگیری‌ها"];
const noop = () => {};

async function renderNav(props: Partial<React.ComponentProps<typeof Nav>> = {}) {
  await act(async () => {
    render(<Nav currentPath="/dashboard" onLogout={noop} {...props} />);
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  localStorageMock.clear();
});

describe("Nav — universal links", () => {
  it("renders all daily-operation links regardless of role", async () => {
    (getRole as jest.Mock).mockReturnValue(null);
    await renderNav();
    for (const label of UNIVERSAL_LABELS) expect(screen.getByText(label)).toBeInTheDocument();
  });
});

describe("Nav — role groups", () => {
  it("shows accounting for reception and hides management", async () => {
    (getRole as jest.Mock).mockReturnValue("reception");
    await renderNav();
    await waitFor(() => expect(screen.getByLabelText("حسابداری")).toBeInTheDocument());
    const group = screen.getByLabelText("حسابداری");
    for (const label of ACCOUNTING_LABELS) expect(group).toHaveTextContent(label);
    expect(screen.queryByLabelText("مدیریت")).not.toBeInTheDocument();
  });

  it("shows both accounting and management for manager", async () => {
    (getRole as jest.Mock).mockReturnValue("manager");
    await renderNav();
    const accounting = await screen.findByLabelText("حسابداری");
    const management = screen.getByLabelText("مدیریت");
    for (const label of ACCOUNTING_LABELS) expect(accounting).toHaveTextContent(label);
    for (const label of MANAGER_LABELS) expect(management).toHaveTextContent(label);
  });

  it("hides privileged groups for staff", async () => {
    (getRole as jest.Mock).mockReturnValue("staff");
    await renderNav();
    await waitFor(() => expect(getRole).toHaveBeenCalled());
    expect(screen.queryByLabelText("حسابداری")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("مدیریت")).not.toBeInTheDocument();
  });

  it("honours explicit management visibility override", async () => {
    (getRole as jest.Mock).mockReturnValue("staff");
    await renderNav({ showManagerLinks: true });
    expect(screen.getByLabelText("مدیریت")).toBeInTheDocument();
  });
});

describe("Nav — responsive menu contract", () => {
  it("exposes an aria-controlled toggle and closes after path change", async () => {
    (getRole as jest.Mock).mockReturnValue("manager");
    const { rerender } = render(<Nav currentPath="/dashboard" onLogout={noop} />);
    const toggle = screen.getByRole("button", { name: /منو/ });
    expect(toggle).toHaveAttribute("aria-controls", "halqe-main-navigation");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("navigation", { name: "ناوبری اصلی" })).toHaveAttribute(
      "id",
      "halqe-main-navigation",
    );
    rerender(<Nav currentPath="/patients" onLogout={noop} />);
    await waitFor(() => expect(toggle).toHaveAttribute("aria-expanded", "false"));
  });

  it("uses native details/summary for keyboard-accessible grouped menus", async () => {
    (getRole as jest.Mock).mockReturnValue("manager");
    await renderNav();
    const group = screen.getByLabelText("حسابداری");
    expect(group.tagName).toBe("DETAILS");
    expect(within(group).getByText("حسابداری").closest("summary")).toBeInTheDocument();
  });
});

describe("Nav — active path", () => {
  it("marks exact and nested paths with aria-current", async () => {
    (getRole as jest.Mock).mockReturnValue("manager");
    await renderNav({ currentPath: "/accounting/invoices/42" });
    expect(screen.getByText("فاکتورها").closest("a")).toHaveAttribute("aria-current", "page");
    expect(screen.getByText("پذیرش").closest("a")).not.toHaveAttribute("aria-current");
  });
});
