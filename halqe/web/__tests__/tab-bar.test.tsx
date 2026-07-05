/**
 * TabBar / TabPanel — accessibility + behaviour render tests (فاز ۱ cockpit).
 *
 * Covers the ARIA tabs contract the cockpit relies on:
 *   - tablist / tab / tabpanel roles + aria-selected + aria-controls/labelledby
 *   - roving tabindex (only the active tab is tabbable)
 *   - the count badge appears + is folded into the aria-label
 *   - clicking a tab calls onChange
 *   - keyboard: ArrowLeft advances in the RTL strip, Home/End jump
 *   - inactive panels stay MOUNTED but hidden (DOM retention)
 */

import React, { useState } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { TabBar, TabPanel, type TabDef } from "@/components/TabBar";

type K = "overview" | "trends" | "record";
const TABS: TabDef<K>[] = [
  { key: "overview", label: "نمای‌کلی" },
  { key: "trends", label: "روند" },
  { key: "record", label: "پرونده", count: 3 },
];
const PREFIX = "test-cockpit";

/** Harness wiring TabBar + panels with local state, mirroring the page. */
function Harness() {
  const [active, setActive] = useState<K>("overview");
  return (
    <>
      <TabBar
        tabs={TABS}
        active={active}
        onChange={setActive}
        ariaLabel="بخش‌های پرونده"
        idPrefix={PREFIX}
      />
      <TabPanel idPrefix={PREFIX} tabKey="overview" active={active}>
        <div data-testid="overview-content">نمای‌کلی</div>
      </TabPanel>
      <TabPanel idPrefix={PREFIX} tabKey="trends" active={active}>
        <div data-testid="trends-content">روند</div>
      </TabPanel>
      <TabPanel idPrefix={PREFIX} tabKey="record" active={active}>
        <div data-testid="record-content">پرونده</div>
      </TabPanel>
    </>
  );
}

describe("TabBar — ARIA structure", () => {
  it("renders a tablist with one tab per def", () => {
    render(<Harness />);
    expect(screen.getByRole("tablist", { name: "بخش‌های پرونده" })).toBeInTheDocument();
    expect(screen.getAllByRole("tab")).toHaveLength(3);
  });

  it("the active tab has aria-selected=true, others false", () => {
    render(<Harness />);
    expect(screen.getByTestId("tab-overview")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("tab-trends")).toHaveAttribute("aria-selected", "false");
  });

  it("each tab points at its panel via aria-controls, and the panel back at the tab", () => {
    render(<Harness />);
    const tab = screen.getByTestId("tab-overview");
    const panelId = tab.getAttribute("aria-controls");
    expect(panelId).toBe(`${PREFIX}-panel-overview`);
    const panel = document.getElementById(panelId!);
    expect(panel).toHaveAttribute("aria-labelledby", tab.id);
  });

  it("roving tabindex: only the active tab is tabbable (0), rest are -1", () => {
    render(<Harness />);
    expect(screen.getByTestId("tab-overview")).toHaveAttribute("tabindex", "0");
    expect(screen.getByTestId("tab-trends")).toHaveAttribute("tabindex", "-1");
    expect(screen.getByTestId("tab-record")).toHaveAttribute("tabindex", "-1");
  });
});

describe("TabBar — count badge", () => {
  it("shows the pending-work count badge on the record tab", () => {
    render(<Harness />);
    const recordTab = screen.getByTestId("tab-record");
    expect(recordTab).toHaveTextContent("3");
    // count is folded into the aria-label so it is announced
    expect(recordTab.getAttribute("aria-label")).toContain("3 مورد در انتظار");
  });

  it("does NOT render a count badge when count is 0/absent", () => {
    const tabs: TabDef<K>[] = [
      { key: "overview", label: "نمای‌کلی", count: 0 },
      { key: "trends", label: "روند" },
      { key: "record", label: "پرونده" },
    ];
    render(
      <TabBar tabs={tabs} active="overview" onChange={() => {}} ariaLabel="x" idPrefix={PREFIX} />,
    );
    // no aria-label override (label is plain) and no badge text beyond the label
    expect(screen.getByTestId("tab-overview")).not.toHaveAttribute("aria-label");
  });
});

describe("TabBar — interaction", () => {
  it("clicking a tab switches the active panel; inactive panels stay mounted but hidden", () => {
    render(<Harness />);
    // initially overview visible, others hidden
    expect(screen.getByTestId("tabpanel-overview")).not.toHaveAttribute("hidden");
    expect(screen.getByTestId("tabpanel-trends")).toHaveAttribute("hidden");

    fireEvent.click(screen.getByTestId("tab-trends"));

    expect(screen.getByTestId("tab-trends")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("tabpanel-trends")).not.toHaveAttribute("hidden");
    expect(screen.getByTestId("tabpanel-overview")).toHaveAttribute("hidden");

    // DOM retention: the hidden overview panel is still in the DOM
    expect(screen.getByTestId("overview-content")).toBeInTheDocument();
  });

  it("ArrowLeft advances to the next tab in the RTL strip", () => {
    render(<Harness />);
    const list = screen.getByRole("tablist");
    fireEvent.keyDown(list, { key: "ArrowLeft" });
    expect(screen.getByTestId("tab-trends")).toHaveAttribute("aria-selected", "true");
  });

  it("ArrowRight goes back (wraps) in the RTL strip", () => {
    render(<Harness />);
    const list = screen.getByRole("tablist");
    // from overview (idx 0) ArrowRight wraps to last (record)
    fireEvent.keyDown(list, { key: "ArrowRight" });
    expect(screen.getByTestId("tab-record")).toHaveAttribute("aria-selected", "true");
  });

  it("End jumps to the last tab, Home back to the first", () => {
    render(<Harness />);
    const list = screen.getByRole("tablist");
    fireEvent.keyDown(list, { key: "End" });
    expect(screen.getByTestId("tab-record")).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(list, { key: "Home" });
    expect(screen.getByTestId("tab-overview")).toHaveAttribute("aria-selected", "true");
  });
});
