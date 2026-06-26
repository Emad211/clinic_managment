/**
 * Suggestions domain — mirrors SuggestionsResponseDTO + suggestion-action.
 */
import { apiFetch } from "./_core";

export interface SuggestionRuleDTO {
  rule_code: string;
  title: string;
  category: string;
  condition_code: string;
  recommendation: string | null;
  dosage_titration: string | null;
  monitoring: string | null;
  contraindications: string | null;
  evidence_level: string | null;
  action_type: string;
  severity: "info" | "warn" | "urgent";
  priority: number;
  source_ref: string | null;
  section: string;
  suggestion_only: boolean;
  /**
   * Prior physician action for this rule on this patient.
   * Populated by GET /patients/{uuid}/suggestions.
   * Any value other than 'accepted' or 'dismissed' is treated as null (no prior action).
   */
  prior_action: "accepted" | "dismissed" | null;
}

export interface SuggestionSectionDTO {
  key: string;
  label: string;
  rules: SuggestionRuleDTO[];
}

/**
 * A single missing clinical datum that prevented some rules from being evaluated.
 * Returned by GET /patients/{uuid}/suggestions when the engine detected gaps.
 */
export interface DataGapDTO {
  /** Machine-readable datum key, e.g. "age", "egfr", "hba1c". */
  datum: string;
  /** Human-readable Persian label shown in the transparency banner. */
  label: string;
  /** Number of clinical rules that could not be evaluated due to this missing datum. */
  affected_rules: number;
}

/**
 * One drug-drug interaction (DDI) flagged by the clinical engine.
 * Returned in `ddi[]` on GET /patients/{uuid}/suggestions.
 *
 * Severity levels (clinical pharmacist contract):
 *   - contraindicated : absolute two-blocker risk (e.g. dual RAAS) — role="alert"
 *   - major           : serious interaction requiring physician review — role="note"
 *   - moderate        : monitor + consider alternatives — role="note"
 *
 * `suggestion_only` is always true — no automatic action is taken.
 */
export interface DdiDTO {
  /** Pharmacologic class of the first drug (e.g. "acei"). */
  class_a: string;
  /** Pharmacologic class of the second drug (e.g. "arb"). */
  class_b: string;
  severity: "contraindicated" | "major" | "moderate";
  /** Human-readable Persian explanation of the interaction. */
  message_fa: string;
  /** Evidence citation, e.g. "ONTARGET 2008؛ ADA 2025 §CKD". Optional. */
  evidence?: string;
  /** Always true — the system suggests, the physician decides. */
  suggestion_only?: boolean;
}

export interface SuggestionsResponseDTO {
  patient_link_id: number;
  count: number;
  has_redflag: boolean;
  framing: string;
  sections: SuggestionSectionDTO[];
  /**
   * Missing data items that prevented some rules from being evaluated.
   * Empty array (or absent) when the engine had everything it needed.
   * Displayed as a non-alarming informational transparency banner.
   */
  data_gaps?: DataGapDTO[];
  /**
   * Drug-drug interactions detected for this patient's active medications.
   * Empty array (or absent) = no interactions found.
   * Rendered above the regular suggestion list, sorted by severity descending.
   */
  ddi?: DdiDTO[];
}

export async function apiGetSuggestions(
  uuid: string,
): Promise<SuggestionsResponseDTO> {
  return apiFetch<SuggestionsResponseDTO>(`/patients/${uuid}/suggestions`);
}

// ────────────────────────────────────────────────────────────
// Suggestion action  — mirrors SuggestionLogDTO
// ────────────────────────────────────────────────────────────

export interface SuggestionLogDTO {
  id: number;
  patient_link_id: number;
  tenant_id: number;
  rule_code: string;
  status: string;
  acted_by: string | null;
  acted_at: string | null;
  note: string | null;
  created_at: string;
}

export async function apiSuggestionAction(
  uuid: string,
  ruleCode: string,
  action: "accept" | "dismiss",
  note?: string,
): Promise<SuggestionLogDTO> {
  return apiFetch<SuggestionLogDTO>(
    `/patients/${uuid}/suggestions/${encodeURIComponent(ruleCode)}/action`,
    {
      method: "POST",
      body: JSON.stringify({ action, note: note ?? null }),
    },
  );
}
