/**
 * Canonical vital-type catalog for the Halqe front-end.
 *
 * IMPORTANT — keep in sync with the back-end:
 *   - specialist_clinic/src/adapters/sqlite/schema.sql  →  clinical_indicators seed
 *   - specialist_clinic/src/adapters/sqlite/vitals_repo.py  →  VITAL_TYPES dict
 *
 * Keys here are the exact strings stored in vital_readings.type (and
 * clinical_indicators.key).  A future back-end endpoint (e.g. GET /api/v1/vitals/catalog)
 * can replace this static array — treat it as a TODO follow-up once the
 * clinical-indicators API is surfaced.
 *
 * Sources verified 2026-06-25 against:
 *   schema.sql:386-401 (clinical_indicators INSERT OR IGNORE block)
 *   vitals_repo.py:6-14 (VITAL_TYPES dict)
 */

export interface VitalCatalogItem {
  /** Canonical lowercase key — sent as VitalIn.type to the back-end. */
  key: string;
  /** Persian display label shown in the <select> option. */
  label: string;
  /** SI/clinical unit string; pre-filled and read-only on selection. */
  unit: string;
}

/**
 * Ordered list of known clinical indicators.
 * The "other" escape hatch is rendered separately by the form, not in this array.
 *
 * Display order mirrors clinical_indicators.display_order in schema.sql.
 */
export const VITAL_CATALOG: VitalCatalogItem[] = [
  // ── Glycemic ───────────────────────────────────────────────
  { key: "fbs",          label: "قند ناشتا (FBS)",    unit: "mg/dL"   },  // display_order 20
  { key: "hba1c",        label: "HbA1c",               unit: "%"       },  // display_order 10
  { key: "ppg",          label: "قند ۲ساعته پس‌غذا",   unit: "mg/dL"   },  // display_order 25
  // ── Blood pressure ─────────────────────────────────────────
  { key: "bp_systolic",  label: "فشار سیستول",         unit: "mmHg"    },  // display_order 30
  { key: "bp_diastolic", label: "فشار دیاستول",        unit: "mmHg"    },  // display_order 40
  { key: "pulse",        label: "ضربان قلب",           unit: "bpm"     },  // display_order 110
  // ── Lipid ──────────────────────────────────────────────────
  { key: "ldl",          label: "LDL کلسترول",         unit: "mg/dL"   },  // display_order 50
  { key: "hdl",          label: "HDL کلسترول",         unit: "mg/dL"   },  // display_order 60
  { key: "triglyceride", label: "تری‌گلیسرید",          unit: "mg/dL"   },  // display_order 70
  // ── Kidney ─────────────────────────────────────────────────
  { key: "egfr",         label: "eGFR (عملکرد کلیه)", unit: "mL/min"  },  // display_order 80
  { key: "uacr",         label: "UACR (آلبومین ادرار)",unit: "mg/g"    },  // display_order 90
  // ── Anthropometric ─────────────────────────────────────────
  { key: "weight",       label: "وزن",                 unit: "kg"      },  // display_order 100
  { key: "bmi",          label: "BMI",                 unit: ""        },  // display_order 105
  // ── Thyroid ────────────────────────────────────────────────
  { key: "tsh",          label: "TSH (تیروئید)",       unit: "mIU/L"   },  // display_order 115
];

/** Lookup map: key → VitalCatalogItem. O(1) access for auto-filling unit. */
export const VITAL_CATALOG_MAP: Readonly<Record<string, VitalCatalogItem>> =
  Object.fromEntries(VITAL_CATALOG.map((v) => [v.key, v]));
