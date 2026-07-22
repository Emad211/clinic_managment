"""Run, evaluation and recommendation-event writes for Clinical Engine v2."""
from __future__ import annotations

import hashlib
import uuid
from typing import Any

from src.adapters.sqlite.core import get_db
from src.domain.clinical_engine import (
    PredicateState,
    RecommendationEventType,
    RuleOutcome,
    RunStatus,
)

from .clinical_engine_audit_common import json_text, now_text, optional_json


class RunAuditRepositoryMixin:
    """Append reproducible execution rows and finalize each run exactly once."""

    def start_run(
        self,
        *,
        patient_link_id: int,
        as_of_at: str,
        engine_version: str,
        fact_snapshot: Any,
        ruleset_id: int | None = None,
        encounter_key: str | None = None,
        created_by: str | None = None,
        run_id: str | None = None,
    ) -> str:
        if not as_of_at or not engine_version:
            raise ValueError("as_of_at and engine_version are required")
        snapshot_json = json_text(fact_snapshot)
        snapshot_hash = hashlib.sha256(
            snapshot_json.encode("utf-8")
        ).hexdigest()
        normalized_run_id = (run_id or str(uuid.uuid4())).strip()
        if not normalized_run_id:
            raise ValueError("run_id cannot be blank")
        with get_db() as db:
            db.execute(
                """INSERT INTO clinical_engine_runs
                   (run_id, patient_link_id, encounter_key, as_of_at, started_at,
                    run_status, engine_version, ruleset_id, fact_snapshot_json,
                    fact_snapshot_hash, created_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    normalized_run_id,
                    patient_link_id,
                    encounter_key,
                    as_of_at,
                    now_text(),
                    RunStatus.RUNNING.value,
                    engine_version,
                    ruleset_id,
                    snapshot_json,
                    snapshot_hash,
                    created_by,
                ),
            )
        return normalized_run_id

    def append_evaluation(
        self,
        *,
        run_id: str,
        rule_version_id: int,
        predicate_state: PredicateState,
        outcome: RuleOutcome,
        trace: Any,
        data_issues: Any | None = None,
        recommendation: Any | None = None,
        suppression: Any | None = None,
        error: Any | None = None,
        duration_ms: float | None = None,
    ) -> int:
        if duration_ms is not None and duration_ms < 0:
            raise ValueError("duration_ms cannot be negative")
        with get_db() as db:
            cursor = db.execute(
                """INSERT INTO clinical_rule_evaluations
                   (run_id, rule_version_id, predicate_state, outcome, trace_json,
                    data_issues_json, recommendation_json, suppression_json,
                    error_json, duration_ms, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    rule_version_id,
                    PredicateState(predicate_state).value,
                    RuleOutcome(outcome).value,
                    json_text(trace),
                    optional_json(data_issues),
                    optional_json(recommendation),
                    optional_json(suppression),
                    optional_json(error),
                    duration_ms,
                    now_text(),
                ),
            )
        return int(cursor.lastrowid)

    def append_recommendation_event(
        self,
        *,
        run_id: str,
        recommendation_key: str,
        action_type: str,
        event_type: RecommendationEventType,
        payload: Any,
        evaluation_id: int | None = None,
    ) -> int:
        if not recommendation_key or not action_type:
            raise ValueError(
                "recommendation_key and action_type are required"
            )
        with get_db() as db:
            cursor = db.execute(
                """INSERT INTO clinical_recommendation_events
                   (run_id, evaluation_id, recommendation_key, action_type,
                    event_type, payload_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    evaluation_id,
                    recommendation_key,
                    action_type,
                    RecommendationEventType(event_type).value,
                    json_text(payload),
                    now_text(),
                ),
            )
        return int(cursor.lastrowid)

    def complete_run(
        self,
        run_id: str,
        *,
        status: RunStatus,
        summary: Any | None = None,
        error: Any | None = None,
        legacy_compare: Any | None = None,
    ) -> None:
        terminal = RunStatus(status)
        if terminal is RunStatus.RUNNING:
            raise ValueError("completion status must be terminal")
        db = get_db()
        with db:
            cursor = db.execute(
                """UPDATE clinical_engine_runs
                   SET completed_at=?, run_status=?, summary_json=?, error_json=?,
                       legacy_compare_json=?
                   WHERE run_id=? AND run_status='RUNNING'""",
                (
                    now_text(),
                    terminal.value,
                    optional_json(summary),
                    optional_json(error),
                    optional_json(legacy_compare),
                    run_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("run not found or already terminal")
