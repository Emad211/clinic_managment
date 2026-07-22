# Clinical Engine v2 research and expert-review package

This directory preserves the research and design input for the suggestion-only
Clinical Engine v2 implemented in [`specialist_clinic/`](../specialist_clinic/).
It is retained for clinical, safety and architecture review—not as an executable
migration package.

> **Implementation source of truth:** current application code, tests, immutable rule
> packages and activation reports. Several documents here describe the original
> dual-run plan and therefore contain historical analysis of components that have since
> been retired. The research directory must never be used to bootstrap or migrate a
> database.

## Recommended review order

1. [`repository-design-report.md`](repository-design-report.md) — the original
   repository-specific risks and Minimum Safe Engine v2 rationale.
2. [`formal-semantics.md`](formal-semantics.md) and
   [`action-type-policy.md`](action-type-policy.md) — fact states, predicate behavior,
   error containment, red flags and action classes.
3. [`clinical-rule.schema.json`](clinical-rule.schema.json),
   [`clinical-fact.schema.json`](clinical-fact.schema.json) and
   [`evaluation-result.schema.json`](evaluation-result.schema.json) — review copies of
   the machine-readable contracts. Runtime copies live under
   `specialist_clinic/src/domain/clinical_engine/schemas/` and are tested for parity.
4. [`golden-cases.md`](golden-cases.md) and
   [`sample-reason-trace.json`](sample-reason-trace.json) — expected safety behavior
   and explainability examples.
5. [`citation-audit.md`](citation-audit.md) — evidence quality and limits of the source
   claims.
6. [`adrs.md`](adrs.md), [`package-class-boundaries.md`](package-class-boundaries.md)
   and [`diagrams.md`](diagrams.md) — architectural decisions and boundaries.
7. [`physician-approval-checklist.md`](physician-approval-checklist.md),
   [`owner-clinician-decisions.md`](owner-clinician-decisions.md) and
   [`production-definition-of-done.md`](production-definition-of-done.md) — human
   clinical sign-off and production acceptance criteria.

## Current implementation cross-check

- Engine domain: [`../specialist_clinic/src/domain/clinical_engine/`](../specialist_clinic/src/domain/clinical_engine/)
- Engine services: [`../specialist_clinic/src/services/clinical_engine/`](../specialist_clinic/src/services/clinical_engine/)
- SQLite boundaries: [`../specialist_clinic/src/adapters/sqlite/`](../specialist_clinic/src/adapters/sqlite/)
- Versioned rule packages: [`../specialist_clinic/src/domain/clinical_engine/rule_artifacts/`](../specialist_clinic/src/domain/clinical_engine/rule_artifacts/)
- Automated tests: [`../specialist_clinic/tests/`](../specialist_clinic/tests/)
- Runtime governance UI: **مدیریت ← موتور بالینی**

Run the complete Specialist Clinic suite from `specialist_clinic/`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

## Non-executable historical artefacts

[`sqlite-additive-ddl.sql`](sqlite-additive-ddl.sql) is intentionally a comment-only
tombstone. Its former dual-run SQL referenced retired v1 tables and must not be run.
The old sample rule and static hash manifest were removed because they no longer matched
the current contract.
