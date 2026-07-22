# Eight consolidated ADRs

## ADR-01 — Clinical safety boundary and abstention
**Context:** v1 suggestion-only output can still imply safety when data/evaluation is missing.
**Decision:** no autonomous diagnosis, prescription, order, referral or vaccine administration. Safety uncertainty yields abstention/NEEDS_DATA. Red flags display automatically.
**Alternatives:** boolean best-effort engine; autonomous workflow.
**Consequences:** more data-needed states, less false reassurance.
**Deferred:** class-specific critical-fact matrix.
**Review trigger:** patient-facing decisions, autonomous actions or legal classification change.

## ADR-02 — Multi-state facts and predicate semantics
**Context:** v1 collapses missing/unknown to false/ok and can make `not_has` true.
**Decision:** explicit fact status, four-state predicates, published truth tables and injected as-of time.
**Alternatives:** SQL NULL/boolean; three states without ERROR.
**Consequences:** explicit UI/trace; legacy adapter required.
**Deferred:** fully normalized historical fact store.
**Review trigger:** external device/EHR/probabilistic sources.

## ADR-03 — Versioned JSON DSL and compilation
**Context:** JSON fits the Flask app but malformed rules are skipped.
**Decision:** retain JSON for v2, version it, validate with Draft 2020-12 plus semantic compiler, store immutable versions.
**Alternatives:** immediate CQL; hard-coded Python; raw DB JSON.
**Consequences:** evolutionary migration; local compiler maintenance.
**Deferred:** CQL runtime/authoring.
**Review trigger:** external computable-guideline exchange or complex shared temporal libraries.

## ADR-04 — Safety ordering, exclusions and conflict resolution
**Context:** red flags are priority-only and contraindications are text.
**Decision:** PREFLIGHT→SAFETY→ROUTINE, executable exclusions, safety failure blocks routine, minimal semantic dedupe and explicit unresolved conflict.
**Alternatives:** priority sorting; UI-only warnings.
**Consequences:** routine output may be suppressed; local clinical policy required.
**Deferred:** generic pathway/state-machine engine.
**Review trigger:** multi-step pathways or multi-guideline conflict at scale.

## ADR-05 — Explainability and immutable audit
**Context:** `suggestion_log` overwrites state; no reason trace.
**Decision:** freeze fact snapshot, rule/ruleset/engine versions, node trace, recommendation events and append-only clinician decisions. No numeric confidence.
**Alternatives:** activity log only; mutable latest state; immediate cryptographic ledger.
**Consequences:** more SQLite storage; reproducibility; retention decision required.
**Deferred:** signatures/hash chain/external WORM.
**Review trigger:** regulation, multi-site dispute or tampering threat.

## ADR-06 — Rule governance and activation lifecycle
**Context:** manager edits active rows in place.
**Decision:** immutable versions; DRAFT/VALIDATED/APPROVED/SILENT/ACTIVE/SUSPENDED/RETIRED; compiler/safety errors block activation; clinical+technical approval.
**Alternatives:** direct manager edit; source-control-only rules.
**Consequences:** slower but reversible changes; manager UI becomes drafting surface.
**Deferred:** e-signatures and external knowledge-management system.
**Review trigger:** multiple sites/authors or formal quality-system requirement.

## ADR-07 — Temporal and terminology semantics
**Context:** latest is timestamp-only; units/codes free text; age approximate.
**Decision:** deterministic as-of, full-date age, canonical keys, registered unit aliases/conversions, minimal temporal operators: latest, within_days, count_within_days, recently_completed.
**Alternatives:** current SQL latest; full CQL temporal algebra.
**Consequences:** enough safety for next release without platform rewrite.
**Deferred:** trends/rates/persistence, terminology server, multiple timezones.
**Review trigger:** rules demand complex intervals, multiple sites/timezones or external code systems.

## ADR-08 — FHIR/CQL/CDS Hooks interoperability
**Context:** standards improve portability but current deployment is standalone desktop.
**Decision:** no FHIR/CQL runtime dependency in v2; use mappable canonical IDs/metadata and adapter seams; CDS Hooks only with future EHR integration.
**Alternatives:** immediate FHIR server/CQL engine; ignore standards.
**Consequences:** low near-term cost, migration path preserved.
**Deferred:** R4/R5 target, CQL engine and CDS Hooks deployment.
**Review trigger:** signed EHR integration, external content exchange or procurement requirement.
