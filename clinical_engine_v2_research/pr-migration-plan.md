# Pull-request migration plan

## PR-01 — Repair CI and freeze baseline
- **Goal:** run the current Flask suites on `main`; characterize v1 defects without changing behavior.
- **Files:** `.github/workflows/ci.yml`, workflow docs, `tests/test_rule_engine_v1_characterization.py`.
- **Schema:** none.
- **Tests:** malformed JSON skip, missing `not_has`, missing `!=`, redflag non-suppression; all existing specialist/webapp tests.
- **Feature flag:** none.
- **Compatibility:** total.
- **Rollback:** revert test/workflow commit.
- **Clinical risk:** none.
- **Acceptance:** no `halqe/` path in CI; both app suites run.

## PR-02 — Domain DTOs, schemas and compiler
- **Goal:** isolated v2 domain, three schemas, semantic compiler.
- **Files:** `src/domain/clinical_engine/*`, `src/services/clinical_engine/compiler.py`, docs schemas, tests.
- **Schema:** none.
- **Feature flag:** runtime off.
- **Compatibility:** total.
- **Rollback:** remove isolated package.
- **Clinical risk:** none.
- **Acceptance:** malformed JSON/operator/action/unit/type/safety metadata cannot compile.

## PR-03 — Additive version/ruleset/audit storage
- **Goal:** add tables and repositories only.
- **Files:** `schema.sql`, additive `core.py`, `clinical_engine_rules_repo.py`, `clinical_engine_audit_repo.py`.
- **Schema:** additive DDL; existing tables untouched.
- **Feature flag:** `clinical_engine_v2_mode=off`.
- **Compatibility:** legacy behavior unchanged.
- **Rollback:** stop using new tables; never drop data.
- **Clinical risk:** low migration risk.
- **Acceptance:** fresh and copied existing DB bootstrap idempotently; triggers/backup tested.

## PR-04 — FactProvider and snapshot shadow capture
- **Goal:** build canonical snapshots from current repositories; no v2 recommendation.
- **Files:** `fact_builder.py`, `legacy_adapter.py`, `clinical_engine_fact_repo.py`.
- **Schema:** PR-03 only.
- **Feature flag:** `off|shadow`.
- **Compatibility:** current UI unchanged.
- **Rollback:** flag off.
- **Clinical risk:** low.
- **Acceptance:** TEST0001–10 deterministic hashes; full-date age; canonical lab/vital union; missing sources explicit.

## PR-05 — Four-state evaluator and outcomes
- **Goal:** all/any/not/current operators, required facts and eligibility.
- **Files:** `evaluator.py`, domain results, compiler, focused tests.
- **Schema:** none.
- **Feature flag:** shadow only.
- **Compatibility:** current UI unchanged.
- **Rollback:** flag off.
- **Clinical risk:** none while shadow.
- **Acceptance:** complete truth tables; GC-02/05/06/07/08/10/14/15/16/22.

## PR-06 — SafetyKernel and action policy
- **Goal:** PREFLIGHT/SAFETY ordering, hard exclusions, redflag suppression, safety failure.
- **Files:** `safety.py`, `composer.py`, versioned draft rule artefacts.
- **Schema:** store draft versions/ruleset; legacy catalog unchanged.
- **Feature flag:** shadow.
- **Compatibility:** no clinician-facing v2 output.
- **Rollback:** retire draft/flag off.
- **Clinical risk:** medium content encoding risk, mitigated by shadow.
- **Acceptance:** GC-01/03/04/09; safety failure blocks routine.

## PR-07 — Trace, dedupe and read-only v2 UI
- **Goal:** grouped v2 cards with reason/data/suppression.
- **Files:** `conflicts.py`, `composer.py`, `facade.py`, thin `patients.py`, v2 template partial.
- **Schema:** none.
- **Feature flag:** `shadow|on_selected`.
- **Compatibility:** legacy partial retained.
- **Rollback:** flag off.
- **Clinical risk:** medium display risk; demo/selected users only.
- **Acceptance:** GC-11/12/17; redflag dominant; no “applied” until action exists.

## PR-08 — Append-only decisions
- **Goal:** presentation and clinician decisions as events; legacy log remains readable.
- **Files:** audit repo, decision service, thin routes, one-time legacy-state importer.
- **Schema:** PR-03 tables.
- **Feature flag:** v2 UI.
- **Compatibility:** old rows retained; current v2 state projected from events.
- **Rollback:** flag off; events retained.
- **Clinical risk:** low.
- **Acceptance:** GC-18/19/20/21; corrections append.

## PR-09 — Follow-up integration and fail-loud clinical paths
- **Goal:** clinical due events from v2; administrative refill/appointment remains distinct; move touched SQL to repos.
- **Files:** `followup_engine.py`, `followup_service.py`, repositories.
- **Schema:** optional additive semantic key on `followup_tasks`.
- **Feature flag:** v2 follow-ups for demo patients.
- **Compatibility:** legacy generator behind flag.
- **Rollback:** flag off.
- **Clinical risk:** medium task-generation risk.
- **Acceptance:** GC-13/23; no duplicate; errors visible.

## PR-10 — Ten-patient dual-run and controlled activation
- **Goal:** compare v1/v2 on TEST0001–10; freeze/approve ruleset; selected-user activation.
- **Files:** comparison tooling/report; no major schema/evaluator/UI rewrite.
- **Schema:** none.
- **Feature flag:** `shadow → on_selected → on`.
- **Compatibility:** instant legacy rollback.
- **Rollback:** flag off.
- **Clinical risk:** activation gate.
- **Acceptance:** zero unexplained safety differences; clinician signs cases; error/burden gates met.

No PR combines a large evaluator rewrite, schema migration, UI replacement and rule-content rewrite.
