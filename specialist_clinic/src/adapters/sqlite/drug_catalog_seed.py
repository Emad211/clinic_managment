"""Idempotent seed of the common drug catalog (per disease), keyed to drug classes.

Populates drug_catalog(id PK, generic_fa, drug_class_key, standard_doses, is_active)
— created in schema.sql by the data-model foundation phase. Each `drug_class_key`
references an existing `drug_classes.class_key` (seeded in schema.sql):
  metformin, sglt2i, glp1_ra, dual_gip_glp1, dpp4i, tzd, su, meglitinide,
  insulin_basal, insulin_bolus, acei, arb, ccb, thiazide, statin, ezetimibe,
  finerenone, aspirin, beta_blocker, loop_diuretic, fibrate, mra,
  thyroid_agent, antithyroid, other.

These are clinical DEFAULTS — manager-editable and **needing physician review**.
`standard_doses` is stored as a JSON-array STRING, e.g. '["500mg", "1000mg"]'.

Idempotency: AUTOINCREMENT ids would let a naive re-run duplicate rows, so we
GUARD the whole seed behind a `SELECT COUNT(*) FROM drug_catalog` emptiness check
AND additionally skip any drug whose `generic_fa` is already present — keyed on
the drug name ALONE (not the generic_fa/class pair), so a re-class of an existing
drug updates cleanly instead of inserting a duplicate, and a re-run inserts nothing.
"""
import json

# (generic_fa, drug_class_key, [standard doses])  — grouped by disease for clarity.
DRUGS = [
    # ===================== DIABETES =====================
    ("متفورمین",            "metformin",      ["500mg", "750mg", "1000mg"]),
    ("امپاگلیفلوزین",       "sglt2i",         ["10mg", "25mg"]),
    ("داپاگلیفلوزین",       "sglt2i",         ["5mg", "10mg"]),
    ("کاناگلیفلوزین",       "sglt2i",         ["100mg", "300mg"]),
    ("لیراگلوتاید",         "glp1_ra",        ["0.6mg", "1.2mg", "1.8mg"]),
    ("سماگلوتاید",          "glp1_ra",        ["0.25mg", "0.5mg", "1mg"]),
    ("دولاگلوتاید",         "glp1_ra",        ["0.75mg", "1.5mg"]),
    ("تیرزپاتاید",          "dual_gip_glp1",  ["2.5mg", "5mg", "7.5mg", "10mg"]),
    ("سیتاگلیپتین",         "dpp4i",          ["50mg", "100mg"]),
    ("لیناگلیپتین",         "dpp4i",          ["5mg"]),
    ("ویلداگلیپتین",        "dpp4i",          ["50mg"]),
    ("پیوگلیتازون",         "tzd",            ["15mg", "30mg", "45mg"]),
    ("گلی‌بنکلامید (گلی‌بوراید)", "su",        ["2.5mg", "5mg"]),
    ("گلی‌کلازید",          "su",             ["30mg", "60mg", "80mg"]),
    ("گلی‌مپراید",          "su",             ["1mg", "2mg", "3mg", "4mg"]),
    ("رپاگلیناید",          "meglitinide",    ["0.5mg", "1mg", "2mg"]),
    ("انسولین گلارژین",     "insulin_basal",  ["10U", "20U", "30U"]),
    ("انسولین دتمیر",       "insulin_basal",  ["10U", "20U"]),
    ("انسولین NPH",         "insulin_basal",  ["10U", "20U"]),
    ("انسولین آسپارت",      "insulin_bolus",  ["4U", "6U", "8U"]),
    ("انسولین لیسپرو",      "insulin_bolus",  ["4U", "6U", "8U"]),
    ("انسولین رگولار",      "insulin_bolus",  ["4U", "6U", "8U"]),

    # ===================== HYPERTENSION =====================
    ("لوزارتان",            "arb",            ["25mg", "50mg", "100mg"]),
    ("والزارتان",           "arb",            ["80mg", "160mg", "320mg"]),
    ("تلمیزارتان",          "arb",            ["40mg", "80mg"]),
    ("کاپتوپریل",           "acei",           ["25mg", "50mg"]),
    ("انالاپریل",           "acei",           ["5mg", "10mg", "20mg"]),
    ("لیزینوپریل",          "acei",           ["5mg", "10mg", "20mg"]),
    ("پریندوپریل",          "acei",           ["4mg", "8mg"]),
    ("آملودیپین",           "ccb",            ["5mg", "10mg"]),
    ("نیفدیپین",            "ccb",            ["20mg", "40mg"]),
    ("دیلتیازم",            "ccb",            ["60mg", "90mg", "120mg"]),
    ("هیدروکلروتیازید",     "thiazide",       ["12.5mg", "25mg"]),
    ("اینداپامید",          "thiazide",       ["1.5mg", "2.5mg"]),
    ("آتنولول",             "beta_blocker",   ["25mg", "50mg", "100mg"]),
    ("متوپرولول",           "beta_blocker",   ["25mg", "50mg", "100mg"]),
    ("کارودیلول",           "beta_blocker",   ["6.25mg", "12.5mg", "25mg"]),
    ("بیزوپرولول",          "beta_blocker",   ["2.5mg", "5mg", "10mg"]),
    ("اسپیرونولاکتون",      "mra",            ["25mg", "50mg", "100mg"]),
    ("فوروزماید",           "loop_diuretic",  ["20mg", "40mg"]),
    ("فینرنون",             "finerenone",     ["10mg", "20mg"]),

    # ===================== HYPERLIPIDEMIA =====================
    ("آتورواستاتین",        "statin",         ["10mg", "20mg", "40mg", "80mg"]),
    ("روزوواستاتین",        "statin",         ["5mg", "10mg", "20mg", "40mg"]),
    ("سیمواستاتین",         "statin",         ["10mg", "20mg", "40mg"]),
    ("لوواستاتین",          "statin",         ["20mg", "40mg"]),
    ("ازتیمایب",            "ezetimibe",      ["10mg"]),
    ("جم‌فیبروزیل",         "fibrate",        ["600mg"]),
    ("فنوفیبرات",           "fibrate",        ["145mg", "160mg", "200mg"]),

    # ===================== ANTIPLATELET / CARDIO-PROTECTIVE =====================
    ("آسپرین",              "aspirin",        ["80mg", "100mg"]),

    # ===================== THYROID =====================
    ("لووتیروکسین",         "thyroid_agent",  ["25µg", "50µg", "75µg", "100µg", "150µg"]),
    ("متی‌مازول",           "antithyroid",    ["5mg", "10mg"]),
    ("پروپیل‌تیواوراسیل (PTU)", "antithyroid",  ["50mg", "100mg"]),
]


def seed_drug_catalog(db):
    """Idempotently seed the per-disease drug catalog.

    AUTOINCREMENT means re-inserting would duplicate, so we guard:
      1. skip entirely if the table already has rows (the common fast path), and
      2. even then, skip any drug whose `generic_fa` is already present (keyed on
         the name alone) — so a partially-seeded table is repaired without
         duplicates and a future class change updates cleanly.
    """
    existing = db.execute("SELECT COUNT(*) AS c FROM drug_catalog").fetchone()
    table_empty = not existing or existing["c"] == 0

    for generic_fa, drug_class_key, doses in DRUGS:
        if not table_empty:
            present = db.execute(
                "SELECT 1 FROM drug_catalog WHERE generic_fa=? LIMIT 1",
                (generic_fa,),
            ).fetchone()
            if present:
                continue
        db.execute(
            """INSERT INTO drug_catalog (generic_fa, drug_class_key, standard_doses, is_active)
               VALUES (?, ?, ?, 1)""",
            (generic_fa, drug_class_key, json.dumps(doses, ensure_ascii=False)),
        )

    db.commit()
