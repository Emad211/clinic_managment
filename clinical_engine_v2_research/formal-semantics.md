# Formal semantics — Clinical Engine v2

## Predicate states
`TRUE` means established from usable facts. `FALSE` means disproved from usable facts.
`UNKNOWN` means insufficient/unknown/not-asked/stale/unverified/conflicting data.
`ERROR` means malformed rule/fact, invalid type, unmapped unit, or unexpected evaluation failure.
`UNKNOWN` is never coerced to `FALSE`; `ERROR` is never reported as NOT_FIRED.

## Boolean truth tables

All children are evaluated for a complete trace.

### all
| Inputs | Result |
|---|---|
| any ERROR | ERROR |
| otherwise any FALSE | FALSE |
| otherwise any UNKNOWN | UNKNOWN |
| all TRUE | TRUE |

### any
| Inputs | Result |
|---|---|
| any ERROR | ERROR |
| otherwise any TRUE | TRUE |
| otherwise any UNKNOWN | UNKNOWN |
| all FALSE | FALSE |

### not
| Input | Result |
|---|---|
| TRUE | FALSE |
| FALSE | TRUE |
| UNKNOWN | UNKNOWN |
| ERROR | ERROR |

## Fact usability
| Fact state/quality | Predicate input |
|---|---|
| PRESENT + acceptable verification + fresh + non-conflicting + compatible unit/type | evaluate |
| explicit verified ABSENT | known absence |
| no row, NULL, UNKNOWN, NOT_ASKED | UNKNOWN |
| NOT_APPLICABLE | UNKNOWN at predicate level; eligibility may map rule to NOT_APPLICABLE |
| stale/unverified/conflicting and selector disallows it | UNKNOWN + data issue |
| source unavailable | UNKNOWN + SOURCE_UNAVAILABLE; fact build may fail if critical |
| unit mismatch without registered conversion | ERROR |
| invalid runtime type | ERROR |
| REFUTED/ENTERED_IN_ERROR | excluded; UNKNOWN if nothing usable remains |

## Current operator semantics
| Operator | PRESENT usable | Explicit verified ABSENT | Missing/unknown/not asked | Invalid type/unit |
|---|---|---|---|---|
| exists | TRUE | FALSE | UNKNOWN | ERROR if malformed |
| truthy | typed boolean | FALSE | UNKNOWN | ERROR |
| has | membership | FALSE | UNKNOWN | ERROR |
| not_has | negated membership | TRUE | UNKNOWN | ERROR |
| in | scalar membership | UNKNOWN unless absence is explicitly modeled as a candidate | UNKNOWN | ERROR |
| == | typed equality | UNKNOWN unless comparing an explicit absence token | UNKNOWN | ERROR |
| != | typed inequality | UNKNOWN unless comparing an explicit absence token | UNKNOWN | ERROR |
| between | inclusive bounds | UNKNOWN | UNKNOWN | ERROR |
| >= <= > < | unit-normalized numeric compare | UNKNOWN | UNKNOWN | ERROR |

The v1 outcomes `None != value → TRUE` and missing collection `not_has → TRUE` are forbidden.

## Rule outcomes
| Situation | Outcome |
|---|---|
| eligibility FALSE | NOT_APPLICABLE |
| eligibility UNKNOWN | NEEDS_DATA unless scope alone proves non-applicability |
| eligibility ERROR | ERROR |
| critical/required fact unusable with NEEDS_DATA policy | NEEDS_DATA |
| condition TRUE and safety clear | FIRED |
| condition FALSE | NOT_FIRED |
| condition UNKNOWN | NEEDS_DATA |
| condition ERROR | ERROR |
| condition TRUE but blocked by red flag, hard exclusion, conflict or dedupe | SUPPRESSED |
| unexpected runtime failure | ERROR |

## Error containment
- Compile-time: no invalid rule may enter an ACTIVE ruleset. Any invalid PREFLIGHT/SAFETY rule rejects the candidate ruleset. Routine compile errors also block activation; the previous approved ruleset stays active.
- Runtime safety error: run status `SAFETY_FAILED`; all dependent routine treatment/target/classification outputs are blocked; UI says «بررسی ایمنی کامل نشد».
- Runtime routine error: only that rule is ERROR; independent rules continue; run is `COMPLETED_WITH_ERRORS`.
- Fact snapshot integrity failure: `FACT_BUILD_FAILED`; no v2 recommendation is presented.
- Audit commit failure: no v2 recommendation is presented.

## Red-flag policy
Active red flags are FIRED and dominant. Routine evaluations remain in audit but are SUPPRESSED.
Default suppression covers suggest_med, set_target, classify, routine risk, screening, vaccination,
follow-up and routine education. Emergency-specific education may remain.
