/**
 * Tests for suggestion prior_action state:
 *   1. Pure-logic helpers: normalisePriorAction + buildInitialActed
 *   2. Visual rendering: accepted / dismissed / null states
 *
 * Tests the full three-state rendering via a minimal inline component that
 * mirrors the exact three-branch logic from RuleCard (which is not exported
 * from the page, so we test the logic + rendering behaviour here, not the
 * full page that requires Next.js router mocks).
 */

import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import {
  normalisePriorAction,
  buildInitialActed,
  type ActedState,
} from "../src/lib/suggestion-utils";
import type { SuggestionsResponseDTO } from "../src/lib/api";

// ─────────────────────────────────────────────────────────────
// 1. Pure-logic: normalisePriorAction
// ─────────────────────────────────────────────────────────────

describe("normalisePriorAction", () => {
  it("returns 'accepted' for 'accepted'", () => {
    expect(normalisePriorAction("accepted")).toBe("accepted");
  });

  it("returns 'dismissed' for 'dismissed'", () => {
    expect(normalisePriorAction("dismissed")).toBe("dismissed");
  });

  it("returns undefined for null", () => {
    expect(normalisePriorAction(null)).toBeUndefined();
  });

  it("returns undefined for undefined", () => {
    expect(normalisePriorAction(undefined)).toBeUndefined();
  });

  it("returns undefined for 'pending' (defensive — unknown value)", () => {
    expect(normalisePriorAction("pending")).toBeUndefined();
  });

  it("returns undefined for arbitrary unknown strings", () => {
    expect(normalisePriorAction("unknown_value")).toBeUndefined();
    expect(normalisePriorAction("")).toBeUndefined();
  });
});

// ─────────────────────────────────────────────────────────────
// 2. Pure-logic: buildInitialActed
// ─────────────────────────────────────────────────────────────

const makeSuggestions = (
  rules: Array<{ rule_code: string; prior_action: string | null }>,
): SuggestionsResponseDTO => ({
  patient_link_id: 42,
  count: rules.length,
  has_redflag: false,
  framing: "پیشنهاد — تأیید با پزشک",
  sections: [
    {
      key: "test",
      label: "تست",
      rules: rules.map((r) => ({
        rule_code: r.rule_code,
        title: `عنوان ${r.rule_code}`,
        category: "test",
        condition_code: "DM",
        recommendation: null,
        dosage_titration: null,
        monitoring: null,
        contraindications: null,
        evidence_level: null,
        action_type: "review",
        severity: "info" as const,
        priority: 1,
        source_ref: null,
        section: "test",
        suggestion_only: true,
        prior_action: r.prior_action as "accepted" | "dismissed" | null,
      })),
    },
  ],
});

describe("buildInitialActed", () => {
  it("seeds 'accepted' rules into the map", () => {
    const suggestions = makeSuggestions([
      { rule_code: "R-001", prior_action: "accepted" },
    ]);
    const map = buildInitialActed(suggestions);
    expect(map["R-001"]).toBe("accepted");
  });

  it("seeds 'dismissed' rules into the map", () => {
    const suggestions = makeSuggestions([
      { rule_code: "R-002", prior_action: "dismissed" },
    ]);
    const map = buildInitialActed(suggestions);
    expect(map["R-002"]).toBe("dismissed");
  });

  it("omits rules with null prior_action from the map", () => {
    const suggestions = makeSuggestions([
      { rule_code: "R-003", prior_action: null },
    ]);
    const map = buildInitialActed(suggestions);
    expect(map["R-003"]).toBeUndefined();
  });

  it("omits rules with unknown prior_action values (defensive)", () => {
    const suggestions = makeSuggestions([
      { rule_code: "R-004", prior_action: "pending" },
    ]);
    const map = buildInitialActed(suggestions);
    expect(map["R-004"]).toBeUndefined();
  });

  it("handles mixed prior_action values across rules in one pass", () => {
    const suggestions = makeSuggestions([
      { rule_code: "R-A", prior_action: "accepted" },
      { rule_code: "R-B", prior_action: "dismissed" },
      { rule_code: "R-C", prior_action: null },
      { rule_code: "R-D", prior_action: "pending" },
    ]);
    const map = buildInitialActed(suggestions);
    expect(map["R-A"]).toBe("accepted");
    expect(map["R-B"]).toBe("dismissed");
    expect(map["R-C"]).toBeUndefined();
    expect(map["R-D"]).toBeUndefined();
  });

  it("returns an empty map for empty sections", () => {
    const suggestions: SuggestionsResponseDTO = {
      patient_link_id: 1,
      count: 0,
      has_redflag: false,
      framing: "پیشنهاد",
      sections: [],
    };
    expect(buildInitialActed(suggestions)).toEqual({});
  });
});

// ─────────────────────────────────────────────────────────────
// 3. Component rendering: three visual states
//
// We mirror the exact three-branch logic from RuleCard here so tests
// are stable without importing the full page (which requires Next.js
// router mocking).
// ─────────────────────────────────────────────────────────────

interface MinimalRuleCardProps {
  title: string;
  acted: ActedState | undefined;
  onAccept: () => void;
  onDismiss: () => void;
}

/** Minimal component mirroring RuleCard's three-branch action area. */
function MinimalRuleCard({ title, acted, onAccept, onDismiss }: MinimalRuleCardProps) {
  return (
    <article aria-label={title}>
      <h4>{title}</h4>
      <div role="group" aria-label="اقدام روی پیشنهاد">
        {acted === "accepted" ? (
          <span role="status">تأیید شد</span>
        ) : acted === "dismissed" ? (
          <span role="status">رد شد</span>
        ) : (
          <>
            <button aria-label={`تأیید پیشنهاد: ${title}`} onClick={onAccept}>
              تأیید
            </button>
            <button aria-label={`رد پیشنهاد: ${title}`} onClick={onDismiss}>
              رد
            </button>
          </>
        )}
      </div>
    </article>
  );
}

describe("suggestion prior_action visual rendering", () => {
  it("renders 'تأیید شد' badge when prior_action is 'accepted'", () => {
    render(
      <MinimalRuleCard
        title="تست"
        acted="accepted"
        onAccept={jest.fn()}
        onDismiss={jest.fn()}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("تأیید شد");
    expect(screen.queryByRole("button", { name: /تأیید پیشنهاد/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /رد پیشنهاد/ })).toBeNull();
  });

  it("renders 'رد شد' badge when prior_action is 'dismissed'", () => {
    render(
      <MinimalRuleCard
        title="تست"
        acted="dismissed"
        onAccept={jest.fn()}
        onDismiss={jest.fn()}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("رد شد");
    expect(screen.queryByRole("button", { name: /تأیید پیشنهاد/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /رد پیشنهاد/ })).toBeNull();
  });

  it("renders action buttons when prior_action is null (no prior action)", () => {
    render(
      <MinimalRuleCard
        title="تست"
        acted={undefined}
        onAccept={jest.fn()}
        onDismiss={jest.fn()}
      />,
    );
    expect(screen.queryByRole("status")).toBeNull();
    expect(
      screen.getByRole("button", { name: /تأیید پیشنهاد/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /رد پیشنهاد/ }),
    ).toBeInTheDocument();
  });

  it("clicking Accept calls onAccept handler", () => {
    const onAccept = jest.fn();
    render(
      <MinimalRuleCard
        title="تست"
        acted={undefined}
        onAccept={onAccept}
        onDismiss={jest.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /تأیید پیشنهاد/ }));
    expect(onAccept).toHaveBeenCalledTimes(1);
  });

  it("clicking Dismiss calls onDismiss handler", () => {
    const onDismiss = jest.fn();
    render(
      <MinimalRuleCard
        title="تست"
        acted={undefined}
        onAccept={jest.fn()}
        onDismiss={onDismiss}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /رد پیشنهاد/ }));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("normalised 'pending' unknown value renders as actionable state (buttons shown)", () => {
    // 'pending' must be normalised to undefined by normalisePriorAction
    // — this test verifies the defensive handling end-to-end.
    const prior = normalisePriorAction("pending");
    render(
      <MinimalRuleCard
        title="تست"
        acted={prior}
        onAccept={jest.fn()}
        onDismiss={jest.fn()}
      />,
    );
    // Should show buttons, not a status badge
    expect(screen.queryByRole("status")).toBeNull();
    expect(
      screen.getByRole("button", { name: /تأیید پیشنهاد/ }),
    ).toBeInTheDocument();
  });
});
