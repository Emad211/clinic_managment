# Owner/clinician decisions genuinely required

| Question | Options | Recommendation | Risk | Deadline |
|---|---|---|---|---|
| Which safety facts are critical for each medication class? | class-specific matrix / global checklist / no blocking | physician/pharmacist-approved class matrix | global overblocks; no blocking unsafe | before PR-06 rule migration |
| Should an active red flag create an urgent internal task, and who owns it? | none / urgent-only / all | approved urgent list with owner and SLA | none may be missed; all overloads | before PR-06 activation |
| Which patient messages may bypass physician approval? | none / administrative only / selected clinical | appointment/refill administrative only initially, under consent/guardrails | all-approval burden; broad auto-send safety/privacy | before engagement/control-room fix |
| When may a dismissed recommendation reappear? | next run / fixed window / material change | material change plus action-specific maximum window | next-run fatigue; indefinite suppression hides change | before PR-08 |
| What may `staff` clinically mutate? | current broad / physician-only / granular | granular; diagnosis/medication/prescription physician-only, data entry delegated | broad unauthorized action; physician-only bottleneck | before selected-user activation |
| What is the source hierarchy for Iranian adaptation and who approves it? | local-first / international-first / case-by-case | documented hierarchy with medical director/domain reviewer | inconsistent conflicting rules | before general-practice content |
| Retention period for snapshots/events? | indefinite / fixed years / archive | no deletion in v2; approve policy before archive | privacy/storage vs audit loss | before any purge job |
| Which outputs are interruptive? | severity only / approved allowlist / all safety | clinician-approved allowlist with SLA | fatigue vs missed urgency | before PR-07 |
| What shadow acceptance gates permit activation? | qualitative / predefined thresholds | predefined gates plus adjudication of every safety difference | vague unsafe activation; overstrict delay | before PR-10 |
