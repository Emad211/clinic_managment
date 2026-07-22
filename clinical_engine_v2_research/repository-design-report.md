# Clinical Engine v2 — repository-specific design review

**Repository:** `Emad211/clinic_managment`
**Branch:** `main`
**Commit reviewed:** `cb611b918aa97cad9ad648d7003e097e57a18d22`
**Scope:** design only; no production code/database/repository change.

## 1. Verdict on previous report

The previous report was directionally correct about:
- missing-data semantics;
- safety-first ordering;
- executable contraindications;
- versioning and reproducibility;
- reason trace;
- clinical governance and test strategy.

It was too broad or premature in:
- immediate FHIR/CQL architecture;
- treating Postgres as a production prerequisite;
- proposing thirty ADRs;
- a large normalized fact/evidence platform before the next release;
- placing append-only clinical audit too late;
- requiring confirmation before every internal follow-up task.

Corrected strategy:
1. retain Flask, SQLite and JSON DSL;
2. add a compiled/versioned v2 beside v1;
3. run shadow on the ten demo patients;
4. make explicit semantics, safety, trace and event audit release gates;
5. defer interoperability/platform work.

## 2. Repository-specific gap analysis

### Direct P0 defects
1. `rule_engine.py` turns malformed trigger JSON into `None` and silently skips it.
2. Unexpected rule exceptions are swallowed with `continue`.
3. Missing values become false/ok; `not_has` on a missing collection can become true.
4. `clinical_rules_service.evaluate()` returns `ok` for missing/invalid input.
5. Contraindications are strings displayed by the template, not constraints.
6. Red flags are sorted first but do not suppress treatment/target/classification output.
7. Accepting a medication suggestion may prefill a class without an executable safety recheck.

### Fragmented semantics
The clinical engine is not one class. Logic is distributed across:
- `rule_engine.py`;
- `vitals_service.py` and `clinical_rules_service.py`;
- `analytics_service.py`;
- `followup_service.py`, `followup_engine.py`, `protocol_service.py`;
- patient-list, dashboard and control-room SQL;
- patient-card projection.

Several cohort/dashboard/follow-up paths read only `vital_readings` and ignore
catalog-keyed `lab_results`, despite the canonical union implemented in
`VitalsRepository.latest_by_type()`.

### Data-model gaps
- `patient_flags` is current-state text; blank deletes the row, so false/not-asked/unknown are indistinguishable.
- Latest observations lack verification, recorded time distinct from effective time, freshness/conflict policy and unit conversion.
- Allergies have no verification/status and can be hard-deleted.
- Several record objects are physically deleted.
- Age uses current year and an approximate Jalali-year conversion rather than full-date/as-of calculation.

### Audit/governance gaps
- `suggestion_log` is an UPSERT keyed by patient/rule and overwrites decisions.
- Manager edits active rule text, evidence, severity, priority and activation in place.
- No frozen fact snapshot, rule version, ruleset or engine version is retained.
- Activity logging is best-effort and can fail silently.
- Existing overwritten decision history cannot be recovered retrospectively.

### Layering gaps
- `patients.py`, `manager.py`, `dashboard.py` and `control_room.py` contain business logic/SQL.
- `followup_service.py` and `followup_engine.py` contain SQL.
- v2 work must not make this worse; every touched path should move SQL to repositories.

### Operational gaps
- `.github/workflows/ci.yml` targets the removed `halqe/` tree and does not run current Flask tests.
- Engagement preview enforces daily cap, but queue/approve do not.
- Control-room group SMS bypasses the approval/quiet/cap/cooldown ledger.
- Root docs say no tests and reference a missing `specialist_clinic/AGENTS.md`.
- The graph report was built from an older commit and is stale relative to the reviewed main commit.

## 3. Corrected priority list

### P0 — before any new general-practice treatment/referral rule
1. no silent compile/runtime failures;
2. four-state predicates and six explicit outcomes;
3. required-fact gate for safety data;
4. PREFLIGHT/SAFETY ordering and executable exclusions;
5. red-flag suppression of routine outputs;
6. current CI fixed;
7. v2 output withheld when audit persistence fails;
8. no autonomous medication/order/diagnosis/referral action.

### P1 — Engine v2 activation gate
1. immutable rule versions and rulesets;
2. append-only run/evaluation/recommendation/decision events;
3. deterministic snapshot and as-of age/time;
4. reason trace and data-issue UI;
5. minimal dedupe/conflict;
6. golden cases and ten-patient dual-run;
7. remove SQL from each touched service/route.

### P2
- historical versions of flags/allergy verification;
- advanced temporal trend/persistence/rate;
- governance UI;
- retention/archive tooling;
- canonical projections for all dashboards/cohorts/card;
- curated medication interaction knowledge.

### P3
- FHIR export/mapping;
- CQL pilot;
- CDS Hooks adapter;
- Postgres for scale/multi-tenancy;
- signatures/hash-chain/external immutable storage.

## 4. Corrected decisions from the previous report

### Follow-up confirmation
Do not require confirmation for every task. A due, approved clinical rule may
create an internal idempotent worklist task. A prescription, order, referral,
appointment booking, vaccine administration or patient-facing clinical message
is a separate confirmed action.

### Append-only audit
Execution and clinician-decision audit moves to P1/release gate. Cryptographic
tamper evidence remains later.

### Postgres
Not required for this single-centre release. SQLite remains acceptable if
migrations, locking/concurrency, backups, restore and audit integrity are tested.

### ADR count
Eight ADRs are sufficient.

### Confidence
No numeric probability. Use categorical data sufficiency, data quality,
applicability, evidence certainty and recommendation strength, accompanied by a
warning that these are not probabilities of correctness.

### FHIR/CQL value in three years
Practical only if EHR integration, computable guideline exchange, complex shared
temporal libraries or a contractual requirement emerges. Preserve mapping seams;
do not add runtime dependencies in v2.

## 5. Minimum Safe Engine v2

| Capability | Why | Risk without it | Current files | Proposed component | DB | Compatibility | Done |
|---|---|---|---|---|---|---|---|
| DSL/schema version | deterministic meaning | mixed old/new semantics | clinical_rules/seed | RuleDefinition/Compiler | rule_versions | legacy stays | unsupported version rejected |
| JSON Schema + semantic compile | invalid rules cannot activate | silent loss/wrong type | rule_engine/manager | compiler.py | diagnostics/version row | shadow | GC-08 |
| no silent failures | visible defects | false reassurance | rule_engine/core/followup | typed diagnostics | run/eval errors | shadow | errors counted/rendered |
| four-state predicates | false vs unknown vs error | unsafe negation | rule_engine | evaluator.py | trace JSON | adapter | truth-table suite |
| explicit outcomes | audit/UI clarity | all non-fired conflated | patient UI/followup | EvaluationResult | evaluations | output adapter | six states |
| required facts + eligibility | scope/data safety | unsafe application | seed/rules | compiler/evaluator | rule JSON | draft migration | GC-02/03/14 |
| safety preflight/exclusions | executable contraindications | unsafe medication output | seed/template | safety.py | rule JSON | shadow | GC-01/04/09 |
| minimal trace | clinician review/debug | opaque output | engine/template | result/composer | trace_json | legacy UI retained | why/data/source visible |
| version/hash | replay/rollback | historical ambiguity | clinical_rules | rules repo | rule/ruleset tables | legacy retained | GC-20/21 |
| append-only audit | preserve history | overwritten decisions | suggestion/activity | audit repo | event tables | synthetic legacy import | GC-18/19 |
| minimal temporal | freshness/due correctness | stale/repeated tasks | vitals/followup | selectors | JSON | legacy behind flag | GC-06/13 |
| simple dedupe/conflict | alert burden | duplicate/contradictory cards | grouped/followup | conflicts.py | event JSON | no content rewrite | GC-11/12/17 |

Deferred from v2: FHIR/CQL runtime, terminology server, advanced trends/rates,
generic state machines, Postgres, cryptographic audit, comprehensive drug
interaction database and automatic clinical messaging.

## 6. SQLite data model

Use the seven additive tables in `sqlite-additive-ddl.sql`.

For v2, retain the complete canonical fact snapshot as JSON in
`clinical_engine_runs` rather than introducing a normalized fact-snapshot table.
Advantages:
- one run is self-contained;
- historical replay is straightforward;
- no destructive rewrite of current clinical tables;
- fewer joins and tables.

Disadvantages:
- duplicated data;
- growth over time;
- harder SQL analytics per individual fact.

This is an acceptable single-clinic v2 tradeoff. A normalized fact/event store
can be added later without changing the engine contract.

### Migration
- Keep `clinical_rules` unchanged during dual-run.
- Idempotent Python migration creates one draft legacy-import version per current row.
- Do not activate imported versions before compile, tests and clinical review.
- Keep `suggestion_log`. Import each current row once as a synthetic
  `legacy_state_only` decision. State explicitly that overwritten history is unrecoverable.
- Do not drop old tables in the v2 migration.
- No automatic retention purge in v2.

## 7. Repository mapping

- Current `RuleEngine` becomes compatibility facade.
- Existing evaluator moves mechanically to a legacy adapter before behavior changes.
- `patients.py` calls only `ClinicalEngineFacade`.
- New SQL belongs only in three clinical-engine SQLite repositories.
- `followup_service.py` consumes typed v2 outcomes; it does not query clinical tables.
- Patient detail uses a dedicated v2 partial and retains the legacy partial for rollback.
- Settings expose `clinical_engine_v2_mode=off|shadow|on_selected|on`.

## 8. Interoperability decision
Use FHIR-aligned identifiers and provenance fields only. Do not deploy a FHIR
server, CQL engine or CDS Hooks service in v2.
