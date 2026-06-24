/**
 * Pure helpers for suggestion prior-action state.
 * Kept separate so they can be unit-tested without importing the page component
 * (which has Next.js router and "use client" dependencies).
 */

import type { SuggestionsResponseDTO } from "./api";

export type ActedState = "accepted" | "dismissed" | "pending";
export type ActedMap = Record<string, ActedState>;

/**
 * Normalise a raw `prior_action` value from the server into a local ActedState.
 * Only 'accepted' and 'dismissed' are meaningful; anything else (null, 'pending',
 * unknown strings) → undefined (treated as no prior action / actionable state).
 */
export function normalisePriorAction(
  v: string | null | undefined,
): ActedState | undefined {
  if (v === "accepted" || v === "dismissed") return v;
  return undefined;
}

/**
 * Build an initial ActedMap from a SuggestionsResponseDTO, seeding every
 * rule that has a recognised prior_action so the panel reflects history
 * on first render without a separate fetch.
 */
export function buildInitialActed(suggestions: SuggestionsResponseDTO): ActedMap {
  const map: ActedMap = {};
  for (const sec of suggestions.sections) {
    for (const rule of sec.rules) {
      const s = normalisePriorAction(rule.prior_action);
      if (s !== undefined) {
        map[rule.rule_code] = s;
      }
    }
  }
  return map;
}
