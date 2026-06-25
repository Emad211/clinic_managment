/**
 * RuleCard — single clinical suggestion card.
 *
 * Exported here so it can be tested directly on the real component
 * (not a mirror) and reused outside the patient detail page.
 *
 * Safety contract (اصل suggestion-only):
 *   - Every card carries data-suggestion-only="true" AND a visible chip «پیشنهاد»
 *     so a physician scrolling to a single card cannot miss that it is advisory.
 *   - Button labels frame the physician's decision ("پذیرفتم" / "رد کردم"),
 *     NOT a command ("تأیید" / "رد").
 *   - After acting, only a role="status" indicator remains — no "execute" button.
 */

"use client";

import { useState } from "react";
import { apiSuggestionAction, type SuggestionRuleDTO } from "@/lib/api";
import type { ActedState } from "@/lib/suggestion-utils";
import styles from "@/app/patients/[uuid]/record.module.css";

const SEVERITY_LABEL: Record<string, string> = {
  urgent: "هشدار",
  warn: "احتیاط",
  info: "توجه",
};

export interface RuleCardProps {
  rule: SuggestionRuleDTO;
  uuid: string;
  acted: ActedState | undefined;
  onAct: (ruleCode: string, action: "accept" | "dismiss") => void;
}

export function RuleCard({ rule, uuid, acted, onAct }: RuleCardProps) {
  const [busy, setBusy] = useState(false);

  async function handleAction(action: "accept" | "dismiss") {
    if (busy || acted) return;
    setBusy(true);
    try {
      await apiSuggestionAction(uuid, rule.rule_code, action);
      onAct(rule.rule_code, action);
    } catch {
      // silent fail — button re-enables so user can retry
    } finally {
      setBusy(false);
    }
  }

  return (
    <article
      className={styles.ruleCard}
      data-severity={rule.severity}
      data-suggestion-only="true"
      aria-label={rule.title}
    >
      {/* Per-card suggestion-only marker — ظریف ولی همیشه در DOM */}
      <span className={styles.suggestionOnlyChip} aria-label="این یک پیشنهاد است">
        پیشنهاد
      </span>

      <div className={styles.ruleHeader}>
        <h4 className={styles.ruleTitle}>{rule.title}</h4>
        <span
          className={styles.severityBadge}
          data-severity={rule.severity}
          aria-label={`شدت: ${SEVERITY_LABEL[rule.severity] ?? rule.severity}`}
        >
          {SEVERITY_LABEL[rule.severity] ?? rule.severity}
        </span>
      </div>

      {rule.recommendation && (
        <p className={styles.ruleRec}>{rule.recommendation}</p>
      )}

      <div className={styles.ruleActions} role="group" aria-label="اقدام روی پیشنهاد">
        {acted === "accepted" ? (
          <span className={`${styles.actedState} ${styles.actedAccepted}`} role="status">
            پذیرفته شد
          </span>
        ) : acted === "dismissed" ? (
          <span className={`${styles.actedState} ${styles.actedDismissed}`} role="status">
            رد شد
          </span>
        ) : (
          <>
            <button
              className={styles.acceptBtn}
              onClick={() => handleAction("accept")}
              disabled={busy}
              aria-label={`ثبت پذیرش پیشنهاد: ${rule.title}`}
            >
              {busy ? "…" : "پذیرفتم"}
            </button>
            <button
              className={styles.dismissBtn}
              onClick={() => handleAction("dismiss")}
              disabled={busy}
              aria-label={`ثبت رد پیشنهاد: ${rule.title}`}
            >
              {busy ? "…" : "رد کردم"}
            </button>
          </>
        )}
      </div>
    </article>
  );
}
