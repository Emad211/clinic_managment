# Golden cases

این‌ها specification اجرایی‌اند، نه تأیید محتوای بالینی راهنما.

## GC-01 — بحران فشار

- **Facts:** DM؛ SBP=185، DBP=112، تازه/تأییدشده
- **Applicable rules:** T2-REDFLAG-BP + T2-BP-RX-01 + target
- **Expected predicate states:** redflag TRUE؛ routine TRUE
- **Expected rule outcomes:** redflag FIRED؛ routine SUPPRESSED
- **Expected suppression:** ACTIVE_REDFLAG
- **Expected UI:** هشدار فوری غالب
- **Expected audit events:** run/fired/presented/suppressed

## GC-02 — بارداری پرسیده نشده

- **Facts:** DM؛ SBP=146؛ pregnancy=NOT_ASKED
- **Applicable rules:** T2-BP-RX-01
- **Expected predicate states:** condition TRUE؛ required fact UNKNOWN
- **Expected rule outcomes:** NEEDS_DATA
- **Expected suppression:** none
- **Expected UI:** وضعیت بارداری را مشخص کنید
- **Expected audit events:** RULE_NEEDS_DATA

## GC-03 — آلرژی نامشخص

- **Facts:** DM+ASCVD؛ allergy=UNKNOWN
- **Applicable rules:** T2-ASA-01
- **Expected predicate states:** clinical TRUE؛ safety UNKNOWN
- **Expected rule outcomes:** NEEDS_DATA
- **Expected suppression:** no aspirin output
- **Expected UI:** آلرژی را مرور کنید
- **Expected audit events:** RULE_NEEDS_DATA

## GC-04 — متفورمین و eGFR 24

- **Facts:** metformin active؛ eGFR=24 fresh
- **Applicable rules:** T2-SAFE-MET-STOP
- **Expected predicate states:** TRUE
- **Expected rule outcomes:** safety FIRED؛ dependent routine suppressed
- **Expected suppression:** HARD_SAFETY
- **Expected UI:** هشدار ایمنی برجسته
- **Expected audit events:** SAFETY_FIRED/PRESENTED

## GC-05 — عدم تطابق واحد

- **Facts:** FBS=7.2 mmol/L؛ rule mg/dL؛ no conversion
- **Applicable rules:** T2-DX-01
- **Expected predicate states:** ERROR
- **Expected rule outcomes:** ERROR
- **Expected suppression:** no output
- **Expected UI:** واحد قابل تبدیل نیست
- **Expected audit events:** UNIT_MISMATCH

## GC-06 — آزمایش stale

- **Facts:** eGFR=42؛ 18 ماه قبل؛ max_age=90d
- **Applicable rules:** CKD med rules
- **Expected predicate states:** UNKNOWN
- **Expected rule outcomes:** NEEDS_DATA
- **Expected suppression:** no treatment
- **Expected UI:** عملکرد کلیه جدید لازم است
- **Expected audit events:** STALE

## GC-07 — مشاهدات متعارض

- **Facts:** SBP 118 device-unverified و 172 clinic-confirmed؛ unresolved
- **Applicable rules:** T2-BP-RX-01
- **Expected predicate states:** UNKNOWN
- **Expected rule outcomes:** NEEDS_DATA
- **Expected suppression:** no treatment
- **Expected UI:** فشارها متعارض‌اند
- **Expected audit events:** CONFLICTING

## GC-08 — JSON نامعتبر

- **Facts:** malformed trigger
- **Applicable rules:** candidate rule
- **Expected predicate states:** compile ERROR
- **Expected rule outcomes:** ruleset activation rejected
- **Expected suppression:** not active
- **Expected UI:** خطای validation مدیر
- **Expected audit events:** COMPILE_FAILED

## GC-09 — خرابی safety rule

- **Facts:** valid facts؛ evaluator throws in safety
- **Applicable rules:** T2-SAFE-MET-STOP
- **Expected predicate states:** ERROR
- **Expected rule outcomes:** SAFETY_FAILED؛ routine blocked
- **Expected suppression:** SAFETY_SUBSYSTEM_FAILED
- **Expected UI:** بررسی ایمنی کامل نشد
- **Expected audit events:** RUN_SAFETY_FAILED

## GC-10 — خرابی routine rule

- **Facts:** one lifestyle rule throws
- **Applicable rules:** routine
- **Expected predicate states:** ERROR for one
- **Expected rule outcomes:** one ERROR؛ others continue
- **Expected suppression:** failed rule only
- **Expected UI:** technical warning authorized
- **Expected audit events:** COMPLETED_WITH_ERRORS

## GC-11 — چند پیشنهاد دارویی

- **Facts:** DM+ASCVD+HF+CKD+obesity
- **Applicable rules:** ASCVD/HF/CKD/OBESITY rules
- **Expected predicate states:** all TRUE
- **Expected rule outcomes:** FIRED then composed option set
- **Expected suppression:** MERGED lower duplicates
- **Expected UI:** one combined card
- **Expected audit events:** evaluations+merge events

## GC-12 — duplicate recommendation

- **Facts:** DM+HLD؛ same statin semantic key
- **Applicable rules:** T2-LIPID-RX + HLD overlap
- **Expected predicate states:** TRUE
- **Expected rule outcomes:** one presented؛ duplicate SUPPRESSED
- **Expected suppression:** DEDUPLICATED
- **Expected UI:** one statin card
- **Expected audit events:** dedupe event

## GC-13 — follow-up recently completed

- **Facts:** A1c 30 days ago؛ interval 90d
- **Applicable rules:** T2-FU-A1C
- **Expected predicate states:** recently_completed TRUE
- **Expected rule outcomes:** NOT_FIRED/SUPPRESSED_RECENT
- **Expected suppression:** RECENTLY_COMPLETED
- **Expected UI:** فعلاً سررسید نیست
- **Expected audit events:** no task event

## GC-14 — سن unknown

- **Facts:** birthdate missing
- **Applicable rules:** age-based rules
- **Expected predicate states:** UNKNOWN
- **Expected rule outcomes:** NEEDS_DATA
- **Expected suppression:** no age output
- **Expected UI:** تاریخ تولد لازم است
- **Expected audit events:** AGE_UNKNOWN

## GC-15 — تولد جلالی

- **Facts:** 1367/05/10؛ fixed as-of
- **Applicable rules:** age rules
- **Expected predicate states:** deterministic full-date result
- **Expected rule outcomes:** expected
- **Expected suppression:** none
- **Expected UI:** normal
- **Expected audit events:** derived age provenance

## GC-16 — تولد میلادی

- **Facts:** 1988-08-01؛ same as-of
- **Applicable rules:** age rules
- **Expected predicate states:** same semantics
- **Expected rule outcomes:** expected
- **Expected suppression:** none
- **Expected UI:** normal
- **Expected audit events:** derived age provenance

## GC-17 — چند بیماری

- **Facts:** DM+HTN+CKD
- **Applicable rules:** three packs
- **Expected predicate states:** scope independently evaluated
- **Expected rule outcomes:** fired/not-fired؛ duplicates merged
- **Expected suppression:** semantic duplicate only
- **Expected UI:** grouped reasons
- **Expected audit events:** scope trace

## GC-18 — dismissed recommendation

- **Facts:** presented suggest_med
- **Applicable rules:** any
- **Expected predicate states:** FIRED
- **Expected rule outcomes:** DISMISSED event appended
- **Expected suppression:** future policy only
- **Expected UI:** رد‌شده با actor/time/reason
- **Expected audit events:** DECISION_DISMISSED

## GC-19 — accepted recommendation

- **Facts:** presented suggest_med
- **Applicable rules:** any
- **Expected predicate states:** FIRED
- **Expected rule outcomes:** ACCEPTED appended؛ no med mutation
- **Expected suppression:** none
- **Expected UI:** پذیرفته‌شده نه اعمال‌شده
- **Expected audit events:** DECISION_ACCEPTED + later action separate

## GC-20 — ruleset version change

- **Facts:** same snapshot؛ ruleset 2.0.0/2.0.1
- **Applicable rules:** changed version
- **Expected predicate states:** may differ
- **Expected rule outcomes:** both preserved
- **Expected suppression:** none
- **Expected UI:** current active result
- **Expected audit events:** two runs/hashes

## GC-21 — historical reproducibility

- **Facts:** stored snapshot/rules/engine
- **Applicable rules:** historical ruleset
- **Expected predicate states:** replay equals stored
- **Expected rule outcomes:** REPRODUCIBLE
- **Expected suppression:** none
- **Expected UI:** audit replay
- **Expected audit events:** REPLAY_VERIFIED

## GC-22 — not_has با منبع مفقود

- **Facts:** med list source unavailable, not explicit empty
- **Applicable rules:** rule using not_has
- **Expected predicate states:** UNKNOWN not TRUE
- **Expected rule outcomes:** NEEDS_DATA
- **Expected suppression:** no output
- **Expected UI:** فهرست دارو قابل تأیید نیست
- **Expected audit events:** SOURCE_UNAVAILABLE

## GC-23 — واکسن history unknown

- **Facts:** DM؛ vaccine history NOT_ASKED
- **Applicable rules:** vaccine rules
- **Expected predicate states:** due UNKNOWN
- **Expected rule outcomes:** NEEDS_DATA
- **Expected suppression:** no auto due task
- **Expected UI:** سابقه واکسن را تکمیل کنید
- **Expected audit events:** RULE_NEEDS_DATA

## GC-24 — dual-run demo

- **Facts:** TEST0001..10 frozen as-of
- **Applicable rules:** migrated legacy rules
- **Expected predicate states:** legacy/v2 compared
- **Expected rule outcomes:** diff classified
- **Expected suppression:** v2 shadow
- **Expected UI:** no clinician display
- **Expected audit events:** legacy_compare_json
