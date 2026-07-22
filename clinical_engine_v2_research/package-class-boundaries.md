# Package and class boundaries

```text
specialist_clinic/src/
├── domain/
│   └── clinical_engine/
│       ├── __init__.py
│       ├── enums.py
│       ├── facts.py
│       ├── rules.py
│       ├── results.py
│       └── ports.py
├── services/
│   └── clinical_engine/
│       ├── __init__.py
│       ├── compiler.py
│       ├── fact_builder.py
│       ├── evaluator.py
│       ├── safety.py
│       ├── conflicts.py
│       ├── composer.py
│       ├── facade.py
│       └── legacy_adapter.py
└── adapters/
    └── sqlite/
        ├── clinical_engine_rules_repo.py
        ├── clinical_engine_audit_repo.py
        └── clinical_engine_fact_repo.py
```

## Dependency rule

```text
api → services/clinical_engine → domain/clinical_engine
                              → repository ports
adapters/sqlite → domain/clinical_engine
```

- Domain never imports Flask, `get_db`, repositories, templates or wall-clock time.
- Services never import `request`, `g`, templates or execute SQL.
- SQLite adapters own all SQL and convert rows to domain DTOs.
- Routes validate/authenticate HTTP and call the facade.
- `as_of_at` is injected; evaluator code never calls `datetime.now()`.

| Component | Responsibility | Input | Output | Allowed | Forbidden |
|---|---|---|---|---|---|
| FactStatus | presence semantics | — | enum | stdlib | Flask/DB |
| Fact | immutable typed fact + quality axes | fields | Fact | domain enums | SQL |
| FactSnapshot | frozen ordered facts + canonical hash | facts, patient, as-of | snapshot | Fact/hash serializer | repository queries |
| RuleDefinition | validated rule DTO | JSON | definition | domain | Flask/DB |
| CompiledRule | typed executable plan | definition | plan | expression types | raw SQL |
| PredicateResult | state, reason, trace node | evaluation | T/F/U/E | enums | UI |
| EvaluationResult | explicit rule outcome | rule + snapshot | result | domain | persistence |
| FactProvider protocol | canonical fact interface | patient/as-of/context | facts/diagnostics | domain | Flask globals |
| LegacyFactBundleAdapter | map current patient/vitals/lab/flags/med tables to v2 facts | repository ports | facts | repositories | rule evaluation |
| RuleCompiler | JSON Schema + semantic/type/unit/dependency validation | rule JSON | compiled rule/diagnostics | validator/domain | patient data |
| RuleEvaluator | deterministic expression evaluation | compiled rule + snapshot | predicate/evaluation | domain | SQL/Flask |
| SafetyKernel | PREFLIGHT/SAFETY ordering and blocking context | safety rules + snapshot | safety context | evaluator | template logic |
| ConflictResolver | semantic dedupe and explicit conflicts | fired results | kept/suppressed results | domain | DB |
| RecommendationComposer | action policy and suggestion-only DTO | resolved results | recommendations | policy table | persistence |
| RulesRepository | immutable versions/rulesets/lifecycle | IDs/status | domain objects | SQLite | HTTP |
| AuditRepository | atomic run/evaluation/event/decision persistence | domain results | IDs | SQLite | clinical interpretation |
| ClinicalEngineFacade | orchestrates build→safety→evaluate→resolve→audit | patient/as-of/mode | UI DTO + legacy-compatible groups | service components | route logic |

## Transitional facade

Keep `src/services/rule_engine.py` as the public compatibility facade. Mechanically
move the existing implementation to `services/clinical_engine/legacy_adapter.py`
without changing behavior. Add setting `clinical_engine_v2_mode=off|shadow|on`.

```python
class RuleEngine:
    def evaluate(self, pid):
        mode = self.settings.mode()
        legacy = self.legacy.evaluate(pid)
        if mode == "off":
            return legacy
        v2 = self.v2.evaluate(pid, as_of_at=iran_now())
        if mode == "shadow":
            self.audit.store_comparison(legacy, v2)
            return legacy
        return self.legacy_output_adapter.to_fired_list(v2)
```

`grouped(pid)` remains compatible until the patient template is migrated.
