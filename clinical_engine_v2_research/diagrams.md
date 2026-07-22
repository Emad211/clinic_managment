# Diagrams

## Rule lifecycle
```mermaid
stateDiagram-v2
    [*] --> Draft
    Draft --> Validated: schema/compiler/tests pass
    Validated --> Approved: clinical + technical approval
    Approved --> Silent: release manager
    Silent --> Active: shadow acceptance criteria met
    Active --> Suspended: safety officer / medical director
    Suspended --> Active: fix + revalidation + reapproval
    Active --> Retired: superseded/end-of-life
    Suspended --> Retired
    Retired --> [*]
    Validated --> Draft: review correction
    Silent --> Draft: discrepancy/safety defect
```

## Runtime sequence
```mermaid
sequenceDiagram
    actor Clinician
    participant Route as Flask Route
    participant Facade as ClinicalEngineFacade
    participant Facts as FactProvider
    participant Rules as RulesRepository
    participant Safety as SafetyKernel
    participant Eval as RuleEvaluator
    participant Conflict as ConflictResolver
    participant Compose as RecommendationComposer
    participant Audit as AuditRepository
    participant UI as Patient Detail UI

    Clinician->>Route: open patient detail
    Route->>Facade: evaluate(patient_id, as_of, context)
    Facade->>Facts: build_snapshot
    Facts-->>Facade: FactSnapshot + diagnostics
    Facade->>Rules: load frozen ruleset
    Rules-->>Facade: compiled rule versions
    Facade->>Safety: evaluate PREFLIGHT/SAFETY
    Safety-->>Facade: safety context
    Facade->>Eval: evaluate ROUTINE
    Eval-->>Facade: explicit results
    Facade->>Conflict: dedupe/conflict/suppression
    Conflict-->>Compose: resolved results
    Compose-->>Facade: suggestion-only recommendations
    Facade->>Audit: atomic run + traces + events
    Audit-->>Facade: persisted IDs
    Facade-->>Route: UI DTO
    Route-->>UI: render
    Clinician->>Route: accept/dismiss/acknowledge
    Route->>Facade: record_decision
    Facade->>Audit: append decision event
```

## Dual-run
```text
request
  ├─ legacy engine ─────────────────► current UI
  └─ engine v2 shadow
       ├─ fact snapshot
       ├─ safety/evaluation
       ├─ trace/audit
       └─ difference classifier ────► no clinician display
```
