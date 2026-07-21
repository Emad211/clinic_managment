"""Stable enum vocabulary for Clinical Engine v2.

These values are persisted in rule artefacts and audit records. Renaming one is
a versioned DSL change, not an internal refactor.
"""

from enum import StrEnum


class PredicateState(StrEnum):
    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"
    ERROR = "ERROR"


class RuleOutcome(StrEnum):
    FIRED = "FIRED"
    NOT_FIRED = "NOT_FIRED"
    NEEDS_DATA = "NEEDS_DATA"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    SUPPRESSED = "SUPPRESSED"
    ERROR = "ERROR"


class ClinicalPhase(StrEnum):
    PREFLIGHT = "PREFLIGHT"
    SAFETY = "SAFETY"
    ROUTINE = "ROUTINE"


class ActionType(StrEnum):
    REDFLAG = "redflag"
    SAFETY_ALERT = "safety_alert"
    SUGGEST_MED = "suggest_med"
    FLAG_RISK = "flag_risk"
    SET_TARGET = "set_target"
    CLASSIFY = "classify"
    CREATE_FOLLOWUP = "create_followup"
    SCHEDULE_SCREENING = "schedule_screening"
    VACCINE = "vaccine"
    EDUCATE = "educate"


class RuleSeverity(StrEnum):
    INFO = "INFO"
    WARN = "WARN"
    URGENT = "URGENT"
    CRITICAL = "CRITICAL"


class DiagnosticSeverity(StrEnum):
    ERROR = "ERROR"
    WARNING = "WARNING"


class FactKind(StrEnum):
    DEMOGRAPHIC = "demographic"
    CONDITION = "condition"
    OBSERVATION = "observation"
    FLAG = "flag"
    MEDICATION = "medication"
    ALLERGY = "allergy"
    PROCEDURE = "procedure"
    ENCOUNTER = "encounter"


class FactStatus(StrEnum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    UNKNOWN = "UNKNOWN"
    NOT_ASKED = "NOT_ASKED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    ENTERED_IN_ERROR = "ENTERED_IN_ERROR"


class VerificationStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    PROVISIONAL = "PROVISIONAL"
    UNVERIFIED = "UNVERIFIED"
    REFUTED = "REFUTED"


class FreshnessStatus(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class ConflictStatus(StrEnum):
    NONE = "NONE"
    PRESENT = "PRESENT"
    UNKNOWN = "UNKNOWN"


class RunStatus(StrEnum):
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"
    SAFETY_FAILED = "SAFETY_FAILED"
    FACT_BUILD_FAILED = "FACT_BUILD_FAILED"
    AUDIT_FAILED = "AUDIT_FAILED"
