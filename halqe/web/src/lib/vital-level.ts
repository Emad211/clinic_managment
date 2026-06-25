/**
 * Utility: map a vital's server-evaluated `level` to display properties.
 *
 * level values: 'ok' | 'warn' | 'danger' | null
 *   null  → no threshold defined for this vital type; render neutral.
 *
 * Returns:
 *   - className: CSS module class suffix to apply (e.g. vitalLevelDanger)
 *   - label:     Short Persian text for non-color accessibility indicator.
 *                Empty string when level is null (no indicator needed).
 *   - ariaLabel: Full ARIA label string; empty string when level is null.
 */

export type VitalLevel = "ok" | "warn" | "danger" | null | undefined;

export interface VitalLevelDisplay {
  /** Stable string key — use to look up CSS module classes. */
  key: "ok" | "warn" | "danger" | "none";
  /** Short Persian text badge label. Empty string when level is null/undefined. */
  label: string;
  /** Full ARIA label for assistive tech. Empty string when level is null/undefined. */
  ariaLabel: string;
}

const LEVEL_MAP: Record<"ok" | "warn" | "danger", VitalLevelDisplay> = {
  ok: {
    key: "ok",
    label: "عادی",
    ariaLabel: "وضعیت: عادی",
  },
  warn: {
    key: "warn",
    label: "احتیاط",
    ariaLabel: "وضعیت: احتیاط — نیاز به بررسی",
  },
  danger: {
    key: "danger",
    label: "خطر",
    ariaLabel: "وضعیت: خطر — بررسی فوری",
  },
};

const LEVEL_NONE: VitalLevelDisplay = {
  key: "none",
  label: "",
  ariaLabel: "",
};

/**
 * Map a VitalReadingDTO.level to display properties.
 * Pure function — no side effects; easy to unit test.
 */
export function vitalLevelDisplay(level: VitalLevel): VitalLevelDisplay {
  if (level === "ok" || level === "warn" || level === "danger") {
    return LEVEL_MAP[level];
  }
  return LEVEL_NONE;
}
