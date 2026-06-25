# Threshold-currency audit — `clinical_indicators` vs current guidelines

**Step 40 (cluster I), loop-4. Owner-gated.** Audit date: 2026-06-25.
Reviewer: clinical-research-advisor (evidence currency across ADA / KDIGO / ESC / ACC-AHA).

> **Nothing in this document changes a live threshold.** The seed values in
> `specialist_clinic/docs/migration_tools/schema_pg_slice2_clinical.sql`
> (`clinical_indicators`) remain unchanged. The ⚠️ items below are **proposals
> pending physician sign-off**, not edits. The code↔seed *consistency* guard
> (`tests/test_threshold_sync.py`) is the only firm deliverable of this step.

## Summary

- **28 of 30 audited threshold fields are ✓ consistent** with current guidelines
  (ADA 2026 §6/§10/§11, KDIGO 2024, ACC/AHA 2025/2026, ATA 2014).
- **No urgent or patient-endangering discrepancy** was found.
- **3 ⚠️ proposals** (below) — all low-risk, all better expressed as per-patient
  or per-rule logic than as a base-threshold change, all **pending physician approval**.

## ✓ Confirmed-current (no action)

`hba1c` (7.0/8.0/target 7.0), `fbs` (130/180, goal 80–130), `ppg` (180/250),
`bp_systolic` (130/140/target 130 — ADA/ACC diabetes target; ESH 2023 uses 140/90
but the ADA-aligned 130 is the defensible conservative choice for this population),
`bp_diastolic` (80/90), `ldl` (warn 70 / danger 100 / target 70),
`hdl` danger (35), `triglyceride` (150/500), `egfr` (60/30), `uacr` (30/300),
`bmi` (25/30 — general population; Iranian cohort is predominantly non-Asian),
`tsh` (4.5/10/target 2.5, goal 0.4–4.0 — ATA-derived; ADA has no explicit TSH cut).

## ⚠️ Proposals — pending physician approval (do NOT apply silently)

| # | indicator/field | current seed | guideline | proposed handling | source |
|---|---|---|---|---|---|
| **P1** | `ldl` target for established-ASCVD subgroup | 70 | **<55 mg/dL** for diabetes + established ASCVD (very-high-risk) | NOT a base-threshold change. Express as a `clinical_rules` rule gated on the `ascvd` flag (verify whether such a rule already exists; if so this is already covered). `target=70` stays correct for the general high-risk diabetic. | ACC/AHA Dyslipidemia 2026; ADA 2026 §10 |
| **P2** | `hdl` warn single value | 40 | women **<50**, men <40 | Single value (40) is correct for men, slightly insensitive for women. Best handled by the per-patient threshold mechanism (step 39, gated) **if patient sex is available** — not a base change. No urgent risk. | ADA 2026 §10 |
| **P3** | `bmi` overweight/obesity cut | 25 / 30 | Asian ancestry **23 / 27.5** | Not applicable by default to the (predominantly non-Asian) Iranian population. Apply per-patient only if an ancestry field is added. No base change. | ADA 2026 §2.12a (Level B) |

## Domain notes flagged for specialist confirmation (if pursued)

- **TSH** (`target=2.5`, `danger=10`): ADA has no explicit non-pregnant-diabetic TSH
  cut; values are ATA-2014/lab-range derived → confirm with **endocrinology** before any change.
- **UACR ↔ SGLT2i**: the indicator classification cut (`uacr danger=300`,
  macroalbuminuria) is distinct from the KDIGO-2024 SGLT2i *drug* trigger (UACR≥200).
  These must NOT be merged — the 200 trigger belongs in the rule's `trigger_json`,
  not the indicator threshold. Confirm with **nephrology** if a rule uses 300 where it
  should use 200.

## Threshold-sync status (firm)

`rule_engine._FALLBACK_THRESHOLDS` (last-resort fallback for hba1c / fbs /
bp_systolic / bp_diastolic) was verified **consistent** with the
`clinical_indicators` seed and is now locked by `tests/test_threshold_sync.py`,
which fails on any future drift between the fallback and the seed.
