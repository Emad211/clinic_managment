# Action-type policy matrix

| action_type | Clinician confirmation | Critical data missing | Active red flag | Automatic task | Presentation | Failure | Audit | Suppression |
|---|---|---|---|---|---|---|---|---|
| redflag | not to display; acknowledgement recommended | show safety not cleared if check cannot complete | dominant | optional urgent internal worklist only; no auto referral/order/SMS | INTERRUPTIVE | fail-closed | evaluated/fired/error, presented, acknowledged/override, optional task | never by routine; merge duplicates |
| safety_alert | not to display; acknowledgement/override for blocker | dependent action NEEDS_DATA/blocked | retain if directly relevant | optional safety-review task | PROMINENT; interruptive only for approved urgent list | fail-closed | evaluated/presented/acknowledged/override reason | merge equivalent alerts; no silent permanent dismissal |
| suggest_med | yes before medication/order change | NEEDS_DATA | SUPPRESSED | no | NON_INTERRUPTIVE | fail-closed | evaluated, presented/suppressed, decision, later med action separately | red flag, hard exclusion, conflict, duplicate |
| flag_risk | no to display; yes before official diagnosis/classification | show UNKNOWN/PARTIAL; never infer low | routine card collapsed/suppressed | no unless separate rule | NON_INTERRUPTIVE | fail-closed for named classification | evaluated/presented/data quality | merge same risk |
| set_target | yes before patient target mutation | NEEDS_DATA | SUPPRESSED | no | NON_INTERRUPTIVE | fail-closed | evaluated/presented/decision/target event | red flag/conflict/duplicate |
| classify | yes before problem-list/diagnosis mutation | NEEDS_DATA | SUPPRESSED unless emergency-specific | no | NON_INTERRUPTIVE | fail-closed | evaluated/presented/decision/separate condition event | red flag, insufficient confirmation, conflicting tests |
| create_followup | no for approved internal worklist; yes for order/message | no task | routine suppressed; emergency task may remain | yes, idempotently | NON_INTERRUPTIVE | fail-closed for clinical due-state | evaluated/task composed-created-deduped/resolved | semantic period and recently-completed |
| schedule_screening | internal due task automatic; appointment/order confirmed | no task | routine suppressed | due task only | NON_INTERRUPTIVE | fail-closed | evaluated/task/later appointment or order | recently-completed/open-task dedupe |
| vaccine | internal due task automatic; order/administration/message confirmed | NEEDS_DATA when history unknown | routine suppressed | due task only | NON_INTERRUPTIVE | fail-closed | evaluated/due task/decision/administration separately | series/period/history dedupe |
| educate | clinician-facing generic no; personalized patient delivery yes | generic may continue; safety-personalized abstains | routine collapsed; emergency instructions retained | no | NON_INTERRUPTIVE | fail-open only generic low-risk content | evaluated/presented; delivery event if sent | semantic dedupe |

## Distinct workflow classes
- Administrative appointment/refill reminders are not clinical recommendations. They may auto-run only under explicit consent/opt-out/quiet-hours/cap policy.
- Internal clinical monitoring tasks may be automatically created by an approved, sufficiently informed due rule.
- Referral, order, prescription, vaccine administration and diagnosis changes require a separate clinician-confirmed action.
- Emergency escalation displays automatically, but external action remains controlled by clinic workflow.
