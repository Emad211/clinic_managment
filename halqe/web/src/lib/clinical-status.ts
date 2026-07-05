/**
 * clinical-status.ts — display metadata for the safety-cockpit status tokens.
 *
 * Single source of truth for how the control / risk / indicator-level tokens map
 * to a Persian label, a NON-COLOUR shape indicator (icon), and a CSS-module class
 * suffix. Every consumer (PatientHeader, ClinicalSummaryStrip, PerDiseaseIndicators,
 * ActiveConditions) reads from here so the vocabulary and the "colour is not the
 * only signal" rule stay consistent across the cockpit.
 *
 * The `className` values are CSS-module class KEYS (looked up as styles[className]);
 * the same class names are defined in record.module.css.
 *
 * Fallback labels: the backend already sends Persian labels for control/risk. These
 * maps provide the icon + class + a fallback label so a component can render even if
 * it only has the status token (e.g. per-disease control, which carries its own
 * label but shares the same vocabulary).
 */

import type {
  ControlStatus,
  RiskLevel,
} from "@/lib/api";

/** Non-colour shape/icon + class + fallback label for one status token. */
export interface StatusMeta {
  label: string;
  icon: string;
  className: string;
}

/** Control status → display meta (icons are text glyphs, no image assets). */
export const CONTROL_META: Record<ControlStatus, StatusMeta> = {
  controlled: { label: "کنترل‌شده", icon: "●", className: "levelOk" },
  borderline: { label: "مرزی", icon: "◆", className: "levelWarn" },
  uncontrolled: { label: "کنترل‌نشده", icon: "▲", className: "levelDanger" },
  no_data: { label: "بدون داده", icon: "—", className: "levelNeutral" },
};

/** Risk level → display meta. */
export const RISK_META: Record<RiskLevel, StatusMeta> = {
  high: { label: "پرخطر", icon: "▲", className: "levelDanger" },
  medium: { label: "متوسط", icon: "◆", className: "levelWarn" },
  low: { label: "کم", icon: "●", className: "levelOk" },
  stable: { label: "پایدار", icon: "●", className: "levelOk" },
};

/** Indicator threshold level → display meta (ok/warn/danger + null neutral). */
export type IndicatorLevel = "ok" | "warn" | "danger" | null | undefined;

export interface IndicatorLevelMeta {
  label: string;
  icon: string;
  className: string;
}

const INDICATOR_LEVEL_MAP: Record<"ok" | "warn" | "danger", IndicatorLevelMeta> = {
  ok: { label: "عادی", icon: "●", className: "levelOk" },
  warn: { label: "احتیاط", icon: "◆", className: "levelWarn" },
  danger: { label: "خطر", icon: "▲", className: "levelDanger" },
};

const INDICATOR_LEVEL_NEUTRAL: IndicatorLevelMeta = {
  label: "",
  icon: "",
  className: "levelNeutral",
};

/**
 * Map an indicator level (ok|warn|danger|null) to display meta. Returns a neutral
 * (no-label) meta for null/undefined so callers can decide whether to show a badge.
 */
export function indicatorLevelMeta(level: IndicatorLevel): IndicatorLevelMeta {
  if (level === "ok" || level === "warn" || level === "danger") {
    return INDICATOR_LEVEL_MAP[level];
  }
  return INDICATOR_LEVEL_NEUTRAL;
}
