/**
 * Nav — shared top navigation bar (step 86, U3).
 *
 * Locks the structural, forget-proof role gating:
 *   (a) role === "manager" (resolved in effect) → manager links appear
 *       («اتاقِ کنترل», «گزارشِ outcome», «صفِ تعامل»);
 *   (b) role === "staff"/null → manager links hidden, universal NAV_LINKS shown;
 *   (c) explicit `showManagerLinks` prop overrides the role read (back-compat);
 *   (d) aria-current="page" on the active link.
 *
 * Mocks:
 *   - @/lib/api       : getRole (no real token decode / HTTP)
 *   - next/link       : passthrough <a> (avoids Next router internals)
 */

import React from "react";
import { render, screen, waitFor, act } from "@testing-library/react";
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

jest.mock("@/lib/api", () => ({
  getRole: jest.fn(),
}));

// next/link → plain anchor passthrough
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

jest.mock("@/components/nav.module.css", () => ({}), { virtual: true });

import Nav from "@/components/Nav";
import { getRole } from "@/lib/api";

const MANAGER_LABELS = ["اتاقِ کنترل", "گزارشِ outcome", "صفِ تعامل"];
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

describe("Nav — universal links always present", () => {
  it("renders all universal NAV_LINKS regardless of role", async () => {
    (getRole as jest.Mock).mockReturnValue(null);
    await renderNav();
    for (const label of UNIVERSAL_LABELS) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });
});

describe("Nav — manager role (no prop) shows manager group", () => {
  beforeEach(() => {
    (getRole as jest.Mock).mockReturnValue("manager");
  });

  it("shows the manager links once the role resolves in effect", async () => {
    await renderNav();
    for (const label of MANAGER_LABELS) {
      await waitFor(() =>
        expect(screen.getByText(label)).toBeInTheDocument(),
      );
    }
  });

  it("wraps the manager links in a semantic group labelled «مدیریت»", async () => {
    await renderNav();
    await waitFor(() =>
      expect(screen.getByText("گزارشِ outcome")).toBeInTheDocument(),
    );
    const group = screen.getByLabelText("مدیریت");
    expect(group).toBeInTheDocument();
    for (const label of MANAGER_LABELS) {
      expect(group).toHaveTextContent(label);
    }
  });
});

describe("Nav — staff / null role hides manager group", () => {
  it("hides manager links for staff", async () => {
    (getRole as jest.Mock).mockReturnValue("staff");
    await renderNav();
    // settle any effect
    await waitFor(() => expect(getRole).toHaveBeenCalled());
    for (const label of MANAGER_LABELS) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
    expect(screen.queryByLabelText("مدیریت")).not.toBeInTheDocument();
  });

  it("hides manager links when role is null", async () => {
    (getRole as jest.Mock).mockReturnValue(null);
    await renderNav();
    await waitFor(() => expect(getRole).toHaveBeenCalled());
    for (const label of MANAGER_LABELS) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
  });
});

describe("Nav — explicit showManagerLinks overrides role", () => {
  it("shows manager links even for staff when showManagerLinks={true}", async () => {
    (getRole as jest.Mock).mockReturnValue("staff");
    await renderNav({ showManagerLinks: true });
    for (const label of MANAGER_LABELS) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("hides manager links even for managers when showManagerLinks={false}", async () => {
    (getRole as jest.Mock).mockReturnValue("manager");
    await renderNav({ showManagerLinks: false });
    await waitFor(() => expect(getRole).toHaveBeenCalled());
    for (const label of MANAGER_LABELS) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
  });
});

describe("Nav — active link aria-current", () => {
  it("marks the current path link with aria-current=page", async () => {
    (getRole as jest.Mock).mockReturnValue("staff");
    await renderNav({ currentPath: "/patients" });
    const active = screen.getByText("بیماران").closest("a");
    expect(active).toHaveAttribute("aria-current", "page");
    // a non-active link must NOT carry aria-current
    const inactive = screen.getByText("داشبورد").closest("a");
    expect(inactive).not.toHaveAttribute("aria-current");
  });

  it("activates a parent link for nested paths (e.g. /patients/uuid)", async () => {
    (getRole as jest.Mock).mockReturnValue("staff");
    await renderNav({ currentPath: "/patients/abc-123" });
    const active = screen.getByText("بیماران").closest("a");
    expect(active).toHaveAttribute("aria-current", "page");
  });
});
