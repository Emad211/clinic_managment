/**
 * SuggestionsPanel — right-column clinical suggestions panel.
 *
 * Exported so it can be unit-tested directly on the real component
 * (not a mirror). Consumed by the patient detail page.
 *
 * Framing contract:
 *   - Always shows a role="note" banner with "پیشنهاد" AND "تأیید با پزشک"
 *     whenever suggestions are loaded (not just when non-empty).
 *   - redflag → role="alert" strip rendered above cards.
 *   - All card interactions delegate to RuleCard (which owns acted state per rule).
 */

"use client";

import { useEffect, useRef, useState } from "react";
import { type SuggestionsResponseDTO, type DataGapDTO } from "@/lib/api";
import { buildInitialActed, type ActedMap } from "@/lib/suggestion-utils";
import { toFarsiDigits } from "@/lib/jalali";
import { RuleCard } from "@/components/RuleCard";
import styles from "@/app/patients/[uuid]/record.module.css";

/**
 * DataGapsBanner — informational transparency banner.
 *
 * Rendered only when `gaps` is a non-empty array. When empty (or absent),
 * nothing is added to the DOM — the absence itself signals to the physician
 * that the engine had all the data it needed.
 *
 * Framing contract:
 *   - Color / tone: info blue — not alarming red or warning amber.
 *   - role="note": informational, not urgent.
 *   - suggestion-only: no action buttons, no automatic consequence.
 *   - Counts shown in Persian digits via toFarsiDigits.
 */
function DataGapsBanner({ gaps }: { gaps?: DataGapDTO[] }) {
  if (!gaps || gaps.length === 0) return null;

  const gapList = gaps
    .map(
      (g) =>
        `${g.label} (${toFarsiDigits(g.affected_rules)} قاعده)`,
    )
    .join("، ");

  return (
    <div
      className={styles.dataGapsBanner}
      role="note"
      aria-label="داده‌های ناقص برای ارزیابی کامل‌تر"
      data-testid="data-gaps-banner"
    >
      <span className={styles.dataGapsIcon} aria-hidden="true">i</span>
      <span>
        برای ارزیابیِ کامل‌ترِ پیشنهادها، ثبتِ این داده‌ها کمک می‌کند:{" "}
        <strong>{gapList}</strong>
      </span>
    </div>
  );
}

export interface SuggestionsPanelProps {
  uuid: string;
  suggestions: SuggestionsResponseDTO | null;
  suggestionsLoading: boolean;
  suggestionsError: string | null;
}

export function SuggestionsPanel({
  uuid,
  suggestions,
  suggestionsLoading,
  suggestionsError,
}: SuggestionsPanelProps) {
  // Per-rule acted state: seeded from server prior_action on load,
  // then updated optimistically after user acts (no full-page reload).
  const [acted, setActed] = useState<ActedMap>({});

  // Track which suggestions object we last seeded from, so we only
  // rebuild the initial map when a genuinely new suggestions payload
  // arrives (not on every render).
  const seededForRef = useRef<SuggestionsResponseDTO | null>(null);

  useEffect(() => {
    if (suggestions && suggestions !== seededForRef.current) {
      seededForRef.current = suggestions;
      setActed((prev) => {
        // Merge server prior_action into local state, but don't overwrite
        // any action the physician has already taken in this session.
        const fromServer = buildInitialActed(suggestions);
        return { ...fromServer, ...prev };
      });
    }
  }, [suggestions]);

  function handleAct(ruleCode: string, action: "accept" | "dismiss") {
    setActed((prev) => ({
      ...prev,
      [ruleCode]: action === "accept" ? "accepted" : "dismissed",
    }));
  }

  return (
    <aside className={`${styles.card} ${styles.suggestionsPanel}`} aria-label="پیشنهادات بالینی">
      <h2 className={styles.suggestionsPanelTitle}>پیشنهادات بالینی</h2>

      {suggestionsLoading && (
        <div className={styles.suggestionsLoading} role="status" aria-live="polite">
          <span className={styles.spinner} aria-hidden="true" />
          در حال بارگذاری پیشنهادات…
        </div>
      )}

      {!suggestionsLoading && suggestionsError && (
        <p className={styles.ruleRec} role="alert" style={{ color: "var(--color-danger)" }}>
          {suggestionsError}
        </p>
      )}

      {!suggestionsLoading && !suggestionsError && suggestions && (
        <>
          {/* Framing banner — always visible, role="note" carries safety obligation */}
          <div className={styles.framingBanner} role="note" aria-label="این صفحه فقط پیشنهاد است">
            <span className={styles.framingIcon} aria-hidden="true">!</span>
            {suggestions.framing}
          </div>

          {suggestions.has_redflag && (
            <div className={styles.redflagStrip} role="alert">
              <span aria-hidden="true">!</span>
              پرچم قرمز: هشدار فوری وجود دارد
            </div>
          )}

          <DataGapsBanner gaps={suggestions.data_gaps} />

          <p className={styles.suggestionsCount}>
            {suggestions.count} پیشنهاد فعال
          </p>

          {suggestions.sections.length === 0 && (
            <p className={styles.emptyNote}>هیچ پیشنهادی یافت نشد.</p>
          )}

          {suggestions.sections.map((sec) => (
            <section key={sec.key} className={styles.suggestionSection} aria-label={sec.label}>
              <h3 className={styles.suggestionSectionLabel}>{sec.label}</h3>
              {sec.rules.map((rule) => (
                <RuleCard
                  key={rule.rule_code}
                  rule={rule}
                  uuid={uuid}
                  acted={acted[rule.rule_code]}
                  onAct={handleAct}
                />
              ))}
            </section>
          ))}
        </>
      )}

      {!suggestionsLoading && !suggestionsError && !suggestions && (
        <p className={styles.emptyNote}>داده‌ای موجود نیست.</p>
      )}
    </aside>
  );
}
