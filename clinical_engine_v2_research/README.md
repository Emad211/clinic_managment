# Clinical Engine v2 research and expert-review package

This directory is the research and design input for the suggestion-only Clinical
Engine v2 in [`specialist_clinic/`](../specialist_clinic/). It is committed so a
clinical, safety, or software specialist can review the evidence, semantics,
governance, and implementation contract alongside the current code.

> Important: this package records the research baseline and proposed design. Some
> gaps described in the repository review and migration plan have since been
> implemented. Treat the current code, tests, and activation report as the source
> of implementation status; treat these documents as the source of design intent
> and review criteria. The sample rule remains `DRAFT` and is not approved for
> patient care.

## Recommended review order

1. [`repository-design-report.md`](repository-design-report.md) — repository-specific
   findings, risks, priorities, and Minimum Safe Engine v2.
2. [`formal-semantics.md`](formal-semantics.md) and
   [`action-type-policy.md`](action-type-policy.md) — fact states, predicate behavior,
   error containment, red flags, and action classes.
3. [`clinical-rule.schema.json`](clinical-rule.schema.json),
   [`clinical-fact.schema.json`](clinical-fact.schema.json), and
   [`evaluation-result.schema.json`](evaluation-result.schema.json) — machine-readable
   contracts (JSON Schema Draft 2020-12).
4. [`golden-cases.md`](golden-cases.md) and
   [`sample-reason-trace.json`](sample-reason-trace.json) — expected safety behavior
   and explainability examples.
5. [`citation-audit.md`](citation-audit.md) — evidence quality and limits of the
   source claims.
6. [`adrs.md`](adrs.md), [`package-class-boundaries.md`](package-class-boundaries.md),
   and [`diagrams.md`](diagrams.md) — architectural decisions and boundaries.
7. [`physician-approval-checklist.md`](physician-approval-checklist.md),
   [`owner-clinician-decisions.md`](owner-clinician-decisions.md), and
   [`production-definition-of-done.md`](production-definition-of-done.md) — items
   requiring human clinical sign-off and production acceptance.

## Implementation cross-check

- Engine code: [`../specialist_clinic/src/domain/clinical_engine/`](../specialist_clinic/src/domain/clinical_engine/),
  [`../specialist_clinic/src/services/clinical_engine/`](../specialist_clinic/src/services/clinical_engine/),
  and [`../specialist_clinic/src/adapters/sqlite/`](../specialist_clinic/src/adapters/sqlite/).
- Versioned rule package: [`../specialist_clinic/src/domain/clinical_engine/rule_artifacts/`](../specialist_clinic/src/domain/clinical_engine/rule_artifacts/).
- Automated tests: [`../specialist_clinic/tests/`](../specialist_clinic/tests/) — files
  named `test_clinical_engine_v2_*.py` cover compilation, storage, facts, evaluation,
  safety, conflicts, decisions, follow-up, UI, activation, and the longitudinal cohort.
- Runtime activation review: open **مدیریت ← موتور بالینی** in the Specialist Clinic.

Run the clinical-engine test set from `specialist_clinic/`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -k clinical_engine_v2 -q
```

## Package contents

- Design and migration: [`repository-design-report.md`](repository-design-report.md),
  [`pr-migration-plan.md`](pr-migration-plan.md), [`adrs.md`](adrs.md),
  [`package-class-boundaries.md`](package-class-boundaries.md), and
  [`sqlite-additive-ddl.sql`](sqlite-additive-ddl.sql).
- Safety and validation: [`formal-semantics.md`](formal-semantics.md),
  [`action-type-policy.md`](action-type-policy.md), [`golden-cases.md`](golden-cases.md),
  [`physician-approval-checklist.md`](physician-approval-checklist.md), and
  [`production-definition-of-done.md`](production-definition-of-done.md).
- Evidence and decisions: [`citation-audit.md`](citation-audit.md) and
  [`owner-clinician-decisions.md`](owner-clinician-decisions.md).
- Examples and verification: [`sample-rule.json`](sample-rule.json),
  [`sample-reason-trace.json`](sample-reason-trace.json),
  [`validation-report.json`](validation-report.json), and [`diagrams.md`](diagrams.md).
- Integrity inventory: [`MANIFEST.txt`](MANIFEST.txt).
