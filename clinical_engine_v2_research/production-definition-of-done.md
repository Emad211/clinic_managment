# Production Definition of Done — Minimum Safe Engine v2

## Compile/activation
- [ ] Active rules have schema/DSL versions, immutable version and hash.
- [ ] JSON Schema and semantic compilation pass.
- [ ] Invalid rules cannot enter ACTIVE rulesets.
- [ ] Prior ACTIVE ruleset is available for rollback.
- [ ] Activation has clinical and technical approval.

## Facts/semantics
- [ ] Missing, absence, unknown, not asked and not applicable are distinct.
- [ ] Stale, unverified, conflict, unit mismatch and invalid type are tested.
- [ ] Current operators implement published truth tables.
- [ ] Age uses full normalized birth date and fixed as-of time.
- [ ] Same snapshot/ruleset/engine returns the same canonical result.

## Safety
- [ ] PREFLIGHT and SAFETY execute before ROUTINE.
- [ ] Safety failure blocks dependent routine output and is visible.
- [ ] Red flags suppress configured routine actions without erasing audit results.
- [ ] Required medication contraindications are executable.
- [ ] No recommendation automatically prescribes, diagnoses, refers or orders.

## Explainability/audit
- [ ] Every run stores snapshot JSON/hash, ruleset, engine version and status.
- [ ] Every candidate rule has explicit outcome and node trace.
- [ ] Presented/suppressed/deduplicated/conflict outputs are evented.
- [ ] Clinician decisions append; they never overwrite.
- [ ] Audit failure prevents v2 recommendation presentation.

## Follow-up/UI
- [ ] Clinical tasks come only from FIRED approved due rules and are idempotent.
- [ ] Orders/appointments/patient messages are separate confirmed actions.
- [ ] UI distinguishes FIRED, NEEDS_DATA, SUPPRESSED and ERROR.
- [ ] Accepted is not labelled applied until a separate action exists.
- [ ] Routine cards are suppressed/collapsed under red flags.

## Testing/release
- [ ] CI runs both current Flask suites.
- [ ] Compiler/operator/truth-table/safety/golden tests pass.
- [ ] All supplied golden cases pass.
- [ ] V1/V2 dual-run on TEST0001–TEST0010 has no unexplained safety difference.
- [ ] Clinical owner signs approval checklist.
- [ ] Feature-flag rollback is tested.
- [ ] Additive SQLite migration is tested on a copy and backup restore is verified.
