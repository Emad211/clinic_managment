/**
 * Public marketing landing page — "/"  (step 58).
 *
 * Renders the ACTUAL page component to lock down the HONESTY contract that
 * mirrors `halqe/docs/demo_script.md` (step 57, advisor-vetted):
 *   (a) the honest value-prop text is present (read-only accounting +
 *       suggestion-only + no SMS without consent);
 *   (b) the "ورود به پنل" CTA links to /login;
 *   (c) the suggestion-only framing «پیشنهاد — تأیید با پزشک» appears;
 *   (d) a schema.org JSON-LD <script> is present with valid, honest JSON;
 *   (e) NO forbidden claims: no "تشخیص خودکار" / "هوش مصنوعی" / a hard ROI %
 *       ("٪ بیشتر" / "X% more").
 *
 * The landing is a pure server component with no client deps (no router, no
 * api, no localStorage) — so it renders directly without mocks.
 */

import React from "react";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// next/link → render a plain <a> so href assertions work in jsdom.
jest.mock("next/link", () => {
  return {
    __esModule: true,
    default: ({
      href,
      children,
      ...rest
    }: {
      href: string;
      children: React.ReactNode;
    } & React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
      <a href={href} {...rest}>
        {children}
      </a>
    ),
  };
});

import LandingPage from "../src/app/page";

describe("Public landing page", () => {
  it("renders the honest value-prop: read-only accounting + suggestion-only", () => {
    render(<LandingPage />);

    // Hero headline mentions bringing lapsed chronic patients back.
    expect(
      screen.getByRole("heading", { level: 1 }),
    ).toHaveTextContent(/بیمارانِ مزمنی/);

    // Read-only accounting boundary (the data-trust differentiator).
    expect(screen.getByText(/پل حسابداری فقط‌خواندنی/)).toBeInTheDocument();

    // No SMS without the clinic's consent (appears as a hero chip and a
    // feature heading — assert at least one is present).
    expect(
      screen.getAllByText(/پیامک فقط با اجازهٔ شما/).length,
    ).toBeGreaterThan(0);
  });

  it("links the «ورود به پنل» CTA to /login", () => {
    render(<LandingPage />);

    const ctas = screen.getAllByRole("link", { name: "ورود به پنل" });
    expect(ctas.length).toBeGreaterThan(0);
    // Every "ورود به پنل" link points at /login (the app entry).
    ctas.forEach((cta) => {
      expect(cta).toHaveAttribute("href", "/login");
    });
  });

  it("frames decision support as suggestion-only (تأیید با پزشک)", () => {
    render(<LandingPage />);

    // The sacred suggestion-only phrasing appears as a hero chip…
    expect(screen.getByText("پیشنهاد — تأیید با پزشک")).toBeInTheDocument();
    // …and the engine card says it does NOT diagnose/prescribe.
    expect(
      screen.getByText(/این سامانه تشخیص یا تجویز نمی‌کند/),
    ).toBeInTheDocument();
  });

  it("exposes a demo-request CTA and a mailto-based form (no fabricated submit)", () => {
    const { container } = render(<LandingPage />);

    const demoLinks = screen.getAllByRole("link", { name: "درخواست دمو" });
    expect(demoLinks.length).toBeGreaterThan(0);
    demoLinks.forEach((link) =>
      expect(link).toHaveAttribute("href", "#demo"),
    );

    const form = container.querySelector("form[action^='mailto:']");
    expect(form).not.toBeNull();
  });

  it("includes a schema.org JSON-LD script with valid, honest JSON", () => {
    const { container } = render(<LandingPage />);

    const ld = container.querySelector(
      'script[type="application/ld+json"]',
    );
    expect(ld).not.toBeNull();

    const parsed = JSON.parse(ld!.innerHTML);
    expect(parsed["@context"]).toBe("https://schema.org");
    const graph = parsed["@graph"] as Array<{ "@type": string }>;
    const types = graph.map((n) => n["@type"]);
    expect(types).toContain("SoftwareApplication");
    expect(types).toContain("Organization");

    // Honesty in structured data: no aggregateRating / offers / fabricated
    // install counts.
    const raw = ld!.innerHTML;
    expect(raw).not.toMatch(/aggregateRating/i);
    expect(raw).not.toMatch(/"offers"/i);
  });

  it("loads NO analytics by default (privacy-first, env-gated, no third party)", () => {
    // step 59: the analytics script renders ONLY when NEXT_PUBLIC_ANALYTICS_SRC
    // + NEXT_PUBLIC_ANALYTICS_DOMAIN are set at build time. In the test env they
    // are unset → there must be NO tracking script and NO third-party request.
    const { container } = render(<LandingPage />);

    // No Plausible/Umami-style script (identified by data-domain or an external
    // src). The only <script> present should be the JSON-LD (type=…/ld+json).
    expect(container.querySelector("script[data-domain]")).toBeNull();
    expect(container.querySelector("script[src]")).toBeNull();
    const scripts = Array.from(container.querySelectorAll("script"));
    scripts.forEach((s) =>
      expect(s.getAttribute("type")).toBe("application/ld+json"),
    );
  });

  it("contains NO forbidden hype/AI/ROI claims", () => {
    const { container } = render(<LandingPage />);
    const text = container.textContent ?? "";
    const html = container.innerHTML;

    // No "automatic diagnosis" / "AI" language.
    expect(text).not.toMatch(/تشخیص خودکار/);
    expect(text).not.toMatch(/هوش مصنوعی/);
    expect(html).not.toMatch(/هوش مصنوعی/);

    // No causal/lift/ROI percentage claims ("٪ بیشتر", "X% more").
    expect(text).not.toMatch(/٪\s*بیشتر/);
    expect(text).not.toMatch(/درصد\s*بیشتر/);
    expect(text).not.toMatch(/\d+\s*%\s*more/i);

    // Never claim the un-built /control-room page.
    expect(text).not.toMatch(/اتاق\s*کنترل/);
    expect(html).not.toMatch(/control-room/);
  });
});
