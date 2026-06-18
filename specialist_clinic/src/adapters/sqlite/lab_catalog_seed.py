"""Idempotent seed of the common Iranian lab-test catalog + per-disease mappings.

Populates two tables (created in schema.sql by the data-model foundation phase):
  - lab_test_catalog(test_key PK, name_fa, unit, ref_low, ref_high, category,
                     display_order, is_active)
  - condition_lab_tests(condition_code, lab_test_key, display_order)

These are clinical DEFAULTS — manager-editable and **needing physician review**.
Reference ranges are typical adult Iranian-lab values for a starting set; they are
not exhaustive and the engine's live thresholds still come from
`clinical_indicators` (see CLAUDE.md threshold-sync rule). Seeded idempotently via
INSERT OR IGNORE (keyed by the PK / composite key) so a re-run inserts nothing new.

Condition codes mirror the `conditions` seed in schema.sql:
  diabetes, hypertension, hyperlipidemia, ckd, thyroid.
"""

# Each test: (test_key, name_fa, unit, ref_low, ref_high, category, display_order)
# ref_low / ref_high are typical adult reference bounds (None where not a simple range).
LAB_TESTS = [
    # ---------------- Glycemic ----------------
    ("fbs",         "قند خون ناشتا (FBS)",        "mg/dL", 70,   99,   "glycemic", 10),
    ("bs_2hpp",     "قند ۲ ساعت پس از غذا (2hpp)", "mg/dL", 70,   140,  "glycemic", 15),
    ("bs_random",   "قند خون تصادفی",              "mg/dL", 70,   199,  "glycemic", 18),
    ("hba1c",       "هموگلوبین A1c",               "%",     4.0,  5.6,  "glycemic", 20),
    ("ogtt_2h",     "تست تحمل گلوکز ۲ ساعته",      "mg/dL", 70,   139,  "glycemic", 25),
    ("insulin_fasting", "انسولین ناشتا",           "µIU/mL", 2.6, 24.9, "glycemic", 28),

    # ---------------- Lipid panel ----------------
    ("chol_total",  "کلسترول تام",                 "mg/dL", None, 200,  "lipid",    30),
    ("ldl",         "LDL کلسترول",                 "mg/dL", None, 100,  "lipid",    32),
    ("hdl",         "HDL کلسترول",                 "mg/dL", 40,   None, "lipid",    34),
    ("triglyceride","تری‌گلیسرید",                 "mg/dL", None, 150,  "lipid",    36),
    ("vldl",        "VLDL کلسترول",                "mg/dL", 5,    40,   "lipid",    38),

    # ---------------- Kidney / renal ----------------
    ("creatinine",  "کراتینین سرم",                "mg/dL", 0.6,  1.3,  "kidney",   40),
    ("urea",        "اوره (BUN)",                  "mg/dL", 15,   45,   "kidney",   42),
    ("bun",         "نیتروژن اورهٔ خون (BUN)",     "mg/dL", 7,    20,   "kidney",   43),
    ("egfr",        "eGFR (تخمین فیلتراسیون کلیه)","mL/min/1.73m²", 90, None, "kidney", 44),
    ("uacr",        "نسبت آلبومین به کراتینین ادرار (UACR)", "mg/g", None, 30, "kidney", 46),
    ("uric_acid",   "اسید اوریک",                  "mg/dL", 3.5,  7.2,  "kidney",   48),

    # ---------------- Electrolytes ----------------
    ("sodium",      "سدیم (Na)",                   "mEq/L", 135,  145,  "electrolyte", 50),
    ("potassium",   "پتاسیم (K)",                  "mEq/L", 3.5,  5.1,  "electrolyte", 52),
    ("chloride",    "کلر (Cl)",                    "mEq/L", 98,   107,  "electrolyte", 54),
    ("calcium",     "کلسیم تام",                   "mg/dL", 8.6,  10.2, "electrolyte", 56),
    ("phosphorus",  "فسفر",                        "mg/dL", 2.5,  4.5,  "electrolyte", 58),
    ("magnesium",   "منیزیم",                      "mg/dL", 1.7,  2.2,  "electrolyte", 59),

    # ---------------- Liver / hepatic ----------------
    ("ast",         "AST (SGOT)",                  "U/L",   None, 40,   "hepatic",  60),
    ("alt",         "ALT (SGPT)",                  "U/L",   None, 41,   "hepatic",  62),
    ("alp",         "آلکالن فسفاتاز (ALP)",        "U/L",   46,   116,  "hepatic",  64),
    ("ggt",         "GGT",                         "U/L",   None, 55,   "hepatic",  65),
    ("bil_total",   "بیلی‌روبین تام",              "mg/dL", 0.1,  1.2,  "hepatic",  66),
    ("albumin",     "آلبومین سرم",                 "g/dL",  3.5,  5.2,  "hepatic",  68),

    # ---------------- Thyroid ----------------
    ("tsh",         "TSH",                         "mIU/L", 0.4,  4.0,  "thyroid",  70),
    ("t4",          "تیروکسین تام (T4)",           "µg/dL", 4.5,  12.0, "thyroid",  72),
    ("ft4",         "T4 آزاد (Free T4)",           "ng/dL", 0.8,  1.8,  "thyroid",  73),
    ("t3",          "تری‌یدوتیرونین (T3)",         "ng/dL", 80,   200,  "thyroid",  74),
    ("anti_tpo",    "آنتی‌بادی ضد TPO",            "IU/mL", None, 34,   "thyroid",  76),

    # ---------------- CBC ----------------
    ("wbc",         "گلبول سفید (WBC)",            "10³/µL", 4.0,  10.0, "cbc",     80),
    ("rbc",         "گلبول قرمز (RBC)",            "10⁶/µL", 4.2,  5.9,  "cbc",     82),
    ("hgb",         "هموگلوبین (Hgb)",             "g/dL",  12.0, 17.0, "cbc",     84),
    ("hct",         "هماتوکریت (Hct)",             "%",     36,   50,   "cbc",     86),
    ("mcv",         "MCV",                         "fL",    80,   100,  "cbc",     88),
    ("plt",         "پلاکت (PLT)",                 "10³/µL", 150,  450,  "cbc",    90),

    # ---------------- Other / vitamins ----------------
    ("vit_d",       "ویتامین D (25-OH)",           "ng/mL", 30,   100,  "vitamin",  100),
    ("vit_b12",     "ویتامین B12",                 "pg/mL", 200,  900,  "vitamin",  102),
    ("ferritin",    "فریتین",                      "ng/mL", 20,   250,  "vitamin",  104),
    ("crp",         "CRP",                         "mg/L",  None, 5,    "inflammation", 110),
    ("esr",         "ESR (سرعت رسوب)",             "mm/hr", None, 20,   "inflammation", 112),
    ("hs_crp",      "hs-CRP",                      "mg/L",  None, 3,    "inflammation", 114),
]

# Per-disease frequent tests → condition_lab_tests(condition_code, lab_test_key, display_order)
CONDITION_TESTS = {
    "diabetes": [
        "hba1c", "fbs", "bs_2hpp", "ldl", "hdl", "triglyceride", "chol_total",
        "creatinine", "egfr", "uacr", "ast", "alt", "potassium",
    ],
    "hypertension": [
        "creatinine", "egfr", "potassium", "sodium", "uacr",
        "ldl", "hdl", "triglyceride", "chol_total", "uric_acid",
    ],
    "hyperlipidemia": [
        "chol_total", "ldl", "hdl", "triglyceride", "vldl", "ast", "alt", "fbs", "hba1c",
    ],
    "ckd": [
        "creatinine", "egfr", "uacr", "urea", "potassium", "sodium",
        "calcium", "phosphorus", "hgb", "hct", "albumin",
    ],
    "thyroid": [
        "tsh", "t4", "ft4", "t3", "anti_tpo",
    ],
}


def seed_lab_catalog(db):
    """Idempotently seed the lab-test catalog and per-disease mappings.

    Uses INSERT OR IGNORE keyed by the primary / composite key, so a second run
    inserts nothing new (manager edits to existing rows are preserved).
    """
    for test_key, name_fa, unit, ref_low, ref_high, category, order in LAB_TESTS:
        db.execute(
            """INSERT OR IGNORE INTO lab_test_catalog
               (test_key, name_fa, unit, ref_low, ref_high, category, display_order, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
            (test_key, name_fa, unit, ref_low, ref_high, category, order),
        )

    for condition_code, test_keys in CONDITION_TESTS.items():
        for order, lab_test_key in enumerate(test_keys, start=1):
            db.execute(
                """INSERT OR IGNORE INTO condition_lab_tests
                   (condition_code, lab_test_key, display_order)
                   VALUES (?, ?, ?)""",
                (condition_code, lab_test_key, order * 10),
            )

    db.commit()
