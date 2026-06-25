/**
 * Unit tests for ScreeningTimeline component (step 37).
 *
 * Scenario coverage:
 *   (الف) رندرِ آیتم‌ها با برچسبِ وضعیت + تاریخِ Jalali
 *   (ب)  never_done با «هرگز» و سبکِ برجسته
 *   (ج)  last_done_at=null → «هرگز»/«—» بدونِ crash
 *   (د)  items=[] → state خالی
 *   (ه)  ترتیبِ سرور حفظ شود
 */

import React from "react";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { ScreeningTimeline } from "../ScreeningTimeline";
import type { ScreeningItem } from "@/lib/api";

// ── Helpers ─────────────────────────────────────────────────

const FRAMING = "یادآوریِ غربالگری — تأیید با پزشک";

function makeItem(overrides: Partial<ScreeningItem> = {}): ScreeningItem {
  return {
    item_key: "a1c",
    label_fa: "هموگلوبین گلیکوزیله",
    last_done_at: "2026-01-15",
    next_due_at: "2026-07-15",
    status: "overdue",
    interval_months: 6,
    condition_code: "DM",
    suggestion_only: true,
    ...overrides,
  };
}

// ── (الف) رندرِ آیتم‌ها با برچسبِ وضعیت + تاریخِ Jalali ────

describe("ScreeningTimeline — رندرِ پایه", () => {
  it("سکشن را رندر می‌کند و عنوان نمایش می‌دهد", () => {
    render(
      <ScreeningTimeline
        framing={FRAMING}
        items={[makeItem()]}
      />,
    );
    expect(screen.getByRole("region", { name: "تقویمِ غربالگری" })).toBeInTheDocument();
    expect(screen.getByText("تقویمِ غربالگری")).toBeInTheDocument();
  });

  it("framing را در یک banner با role=note نمایش می‌دهد", () => {
    render(
      <ScreeningTimeline framing={FRAMING} items={[makeItem()]} />,
    );
    const banner = screen.getByRole("note");
    expect(banner).toBeInTheDocument();
    expect(banner).toHaveTextContent(FRAMING);
  });

  it("label_fa آیتم را نمایش می‌دهد", () => {
    render(
      <ScreeningTimeline
        framing={FRAMING}
        items={[makeItem({ label_fa: "هموگلوبین گلیکوزیله" })]}
      />,
    );
    expect(screen.getByText("هموگلوبین گلیکوزیله")).toBeInTheDocument();
  });

  it("وضعیتِ overdue را با برچسبِ «گذشته» نمایش می‌دهد", () => {
    render(
      <ScreeningTimeline
        framing={FRAMING}
        items={[makeItem({ status: "overdue" })]}
      />,
    );
    expect(screen.getByTestId("screening-status-a1c")).toHaveTextContent("گذشته");
  });

  it("وضعیتِ due_soon را با برچسبِ «نزدیک به موعد» نمایش می‌دهد", () => {
    render(
      <ScreeningTimeline
        framing={FRAMING}
        items={[makeItem({ item_key: "uacr", status: "due_soon" })]}
      />,
    );
    expect(screen.getByTestId("screening-status-uacr")).toHaveTextContent("نزدیک به موعد");
  });

  it("وضعیتِ ok را با برچسبِ «به‌موقع» نمایش می‌دهد", () => {
    render(
      <ScreeningTimeline
        framing={FRAMING}
        items={[makeItem({ item_key: "eye", status: "ok" })]}
      />,
    );
    expect(screen.getByTestId("screening-status-eye")).toHaveTextContent("به‌موقع");
  });

  it("تاریخِ Jalali را برای last_done_at نمایش می‌دهد (۲۰۲۶-۰۱-۱۵ → ۱۴۰۴/۱۰/۲۶)", () => {
    render(
      <ScreeningTimeline
        framing={FRAMING}
        items={[makeItem({ last_done_at: "2026-01-15" })]}
      />,
    );
    // formatJalali("2026-01-15") → ۱۴۰۴/۱۰/۲۶
    expect(screen.getByTestId("screening-last-a1c")).toHaveTextContent("۱۴۰۴/۱۰/۲۶");
  });

  it("تاریخِ Jalali را برای next_due_at نمایش می‌دهد (عددِ فارسی، بدونِ crash)", () => {
    render(
      <ScreeningTimeline
        framing={FRAMING}
        items={[makeItem({ next_due_at: "2026-07-15" })]}
      />,
    );
    // formatJalali("2026-07-15") → تاریخِ Jalali با رقمِ فارسی؛ باید «—» نباشد
    const el = screen.getByTestId("screening-next-a1c");
    expect(el).not.toHaveTextContent("—");
    // باید رقمِ فارسی داشته باشد (۱۴۰۵ به فارسی)
    expect(el.textContent).toMatch(/[۰-۹]/);
  });

  it("چیپِ «پیشنهاد» را نمایش می‌دهد", () => {
    render(
      <ScreeningTimeline framing={FRAMING} items={[makeItem()]} />,
    );
    expect(screen.getByText("پیشنهاد")).toBeInTheDocument();
  });
});

// ── (ب) never_done با «هرگز» و سبکِ برجسته ─────────────────

describe("ScreeningTimeline — وضعیتِ never_done", () => {
  it("وضعیتِ never_done را با برچسبِ «هرگز انجام نشده» نمایش می‌دهد", () => {
    render(
      <ScreeningTimeline
        framing={FRAMING}
        items={[makeItem({ item_key: "foot", status: "never_done" })]}
      />,
    );
    expect(screen.getByTestId("screening-status-foot")).toHaveTextContent(
      "هرگز انجام نشده",
    );
  });

  it("last_done_at=null با status=never_done را با «هرگز» نمایش می‌دهد", () => {
    render(
      <ScreeningTimeline
        framing={FRAMING}
        items={[
          makeItem({ item_key: "foot", status: "never_done", last_done_at: null }),
        ]}
      />,
    );
    expect(screen.getByTestId("screening-last-foot")).toHaveTextContent("هرگز");
  });

  it("آیتمِ never_done باید data-status=never_done داشته باشد (برایِ CSS برجسته)", () => {
    render(
      <ScreeningTimeline
        framing={FRAMING}
        items={[makeItem({ item_key: "foot", status: "never_done", last_done_at: null })]}
      />,
    );
    const listItem = screen.getByRole("listitem");
    expect(listItem).toHaveAttribute("data-status", "never_done");
  });
});

// ── (ج) last_done_at=null / next_due_at=null بدونِ crash ────

describe("ScreeningTimeline — مقادیرِ null بدونِ crash", () => {
  it("last_done_at=null → «هرگز» بدونِ crash", () => {
    expect(() =>
      render(
        <ScreeningTimeline
          framing={FRAMING}
          items={[makeItem({ last_done_at: null })]}
        />,
      ),
    ).not.toThrow();

    expect(screen.getByTestId("screening-last-a1c")).toHaveTextContent("هرگز");
  });

  it("next_due_at=null → «—» بدونِ crash", () => {
    expect(() =>
      render(
        <ScreeningTimeline
          framing={FRAMING}
          items={[makeItem({ next_due_at: null })]}
        />,
      ),
    ).not.toThrow();

    expect(screen.getByTestId("screening-next-a1c")).toHaveTextContent("—");
  });

  it("هر دو null بدونِ crash", () => {
    expect(() =>
      render(
        <ScreeningTimeline
          framing={FRAMING}
          items={[makeItem({ last_done_at: null, next_due_at: null })]}
        />,
      ),
    ).not.toThrow();
  });
});

// ── (د) items=[] → state خالی ───────────────────────────────

describe("ScreeningTimeline — آرایهٔ خالی", () => {
  it("وقتِ items=[] سکشن رندر می‌شود (نه خطا)", () => {
    render(<ScreeningTimeline framing={FRAMING} items={[]} />);
    expect(
      screen.getByTestId("screening-timeline-section"),
    ).toBeInTheDocument();
  });

  it("وقتِ items=[] state خالیِ تمیز نمایش می‌دهد", () => {
    render(<ScreeningTimeline framing={FRAMING} items={[]} />);
    expect(screen.getByTestId("screening-empty")).toBeInTheDocument();
  });

  it("وقتِ items=[] هیچ list item‌ای نباشد", () => {
    render(<ScreeningTimeline framing={FRAMING} items={[]} />);
    expect(screen.queryByTestId("screening-list")).not.toBeInTheDocument();
  });

  it("وقتِ items=[] framing را باز هم نمایش می‌دهد", () => {
    render(<ScreeningTimeline framing={FRAMING} items={[]} />);
    expect(screen.getByRole("note")).toHaveTextContent(FRAMING);
  });
});

// ── (ه) ترتیبِ سرور حفظ شود ────────────────────────────────

describe("ScreeningTimeline — ترتیبِ سرور", () => {
  const items: ScreeningItem[] = [
    makeItem({ item_key: "a1c", label_fa: "هموگلوبین گلیکوزیله", status: "never_done" }),
    makeItem({ item_key: "eye", label_fa: "معاینهٔ چشم", status: "overdue" }),
    makeItem({ item_key: "uacr", label_fa: "آلبومینوری", status: "due_soon" }),
    makeItem({ item_key: "foot", label_fa: "معاینهٔ پا", status: "ok" }),
  ];

  it("آیتم‌ها را به همان ترتیبِ ورودی رندر می‌کند", () => {
    render(<ScreeningTimeline framing={FRAMING} items={items} />);

    const listItems = screen.getAllByRole("listitem");
    expect(listItems).toHaveLength(4);

    // ترتیب: never_done اول (طبقِ ترتیبِ سرور)
    expect(listItems[0]).toHaveTextContent("هموگلوبین گلیکوزیله");
    expect(listItems[1]).toHaveTextContent("معاینهٔ چشم");
    expect(listItems[2]).toHaveTextContent("آلبومینوری");
    expect(listItems[3]).toHaveTextContent("معاینهٔ پا");
  });

  it("تعداد آیتم‌ها درست است", () => {
    render(<ScreeningTimeline framing={FRAMING} items={items} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(4);
  });

  it("کامپوننت ترتیبِ سرور را تغییر نمی‌دهد", () => {
    // never_done و overdue از سرور اول می‌آیند — کامپوننت نباید مرتب‌سازی کند
    const statusOrder = items.map((i) => i.status);
    render(<ScreeningTimeline framing={FRAMING} items={items} />);
    const listItems = screen.getAllByRole("listitem");

    statusOrder.forEach((status, idx) => {
      expect(listItems[idx]).toHaveAttribute("data-status", status);
    });
  });
});
