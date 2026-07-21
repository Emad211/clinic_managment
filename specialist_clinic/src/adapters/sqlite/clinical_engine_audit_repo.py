"""Append-only audit persistence for Clinical Engine v2."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from src.adapters.sqlite.core import get_db
from src.common.utils import iran_now
from src.domain.clinical_engine import (
    ClinicalDecision,
    PredicateState,
    RecommendationEventType,
    RuleOutcome,
    RunStatus,
)


def _now_text() -> str:
    return iran_now().isoformat(sep=" ", timespec="seconds")


def _json_text(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _optional_json(value: Any | None) -> str | None:
    return None if value is None else _json_text(value)


class ClinicalEngineAuditRepository:
    """Writes reproducible runs and append-only evaluation/decision events."""

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
        snapshot_json = _json_text(fact_snapshot)
        snapshot_hash = hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()
        run_id = (run_id or str(uuid.uuid4())).strip()
        if not run_id:
            raise ValueError("run_id cannot be blank")
        with get_db() as db:
            db.execute(
                """INSERT INTO clinical_engine_runs
                   (run_id, patient_link_id, encounter_key, as_of_at, started_at,
                    run_status, engine_version, ruleset_id, fact_snapshot_json,
                    fact_snapshot_hash, created_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    patient_link_id,
                    encounter_key,
                    as_of_at,
                    _now_text(),
                    RunStatus.RUNNING.value,
                    engine_version,
                    ruleset_id,
                    snapshot_json,
                    snapshot_hash,
                    created_by,
                ),
            )
        return run_id

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
            cur = db.execute(
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
                    _json_text(trace),
                    _optional_json(data_issues),
                    _optional_json(recommendation),
                    _optional_json(suppression),
                    _optional_json(error),
                    duration_ms,
                    _now_text(),
                ),
            )
        return int(cur.lastrowid)

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
            raise ValueError("recommendation_key and action_type are required")
        with get_db() as db:
            cur = db.execute(
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
                    _json_text(payload),
                    _now_text(),
                ),
            )
        return int(cur.lastrowid)

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
            cur = db.execute(
                """UPDATE clinical_engine_runs
                   SET completed_at=?, run_status=?, summary_json=?, error_json=?,
                       legacy_compare_json=?
                   WHERE run_id=? AND run_status='RUNNING'""",
                (
                    _now_text(),
                    terminal.value,
                    _optional_json(summary),
                    _optional_json(error),
                    _optional_json(legacy_compare),
                    run_id,
                ),
            )
            if cur.rowcount != 1:
                raise ValueError("run not found or already terminal")

    def append_decision(
        self,
        *,
        recommendation_event_id: int,
        patient_link_id: int,
        decision: ClinicalDecision,
        actor_username: str,
        actor_user_id: int | None = None,
        reason_code: str | None = None,
        reason_text: str | None = None,
        supersedes_event_id: int | None = None,
        legacy_source_suggestion_log_id: int | None = None,
    ) -> int:
        actor = (actor_username or "").strip()
        if not actor:
            raise ValueError("actor_username is required")
        db = get_db()
        recommendation = db.execute(
            """SELECT r.run_id, e.patient_link_id
               FROM clinical_recommendation_events r
               JOIN clinical_engine_runs e ON e.run_id=r.run_id
               WHERE r.id=?""",
            (recommendation_event_id,),
        ).fetchone()
        if not recommendation or int(recommendation["patient_link_id"]) != int(patient_link_id):
            raise ValueError("recommendation event does not belong to this patient")
        if supersedes_event_id is not None:
            prior = db.execute(
                """SELECT recommendation_event_id, patient_link_id
                   FROM clinical_decision_events WHERE id=?""",
                (supersedes_event_id,),
            ).fetchone()
            if (
                not prior
                or int(prior["recommendation_event_id"]) != int(recommendation_event_id)
                or int(prior["patient_link_id"]) != int(patient_link_id)
            ):
                raise ValueError("superseded decision must belong to the same recommendation")
        with db:
            cur = db.execute(
                """INSERT INTO clinical_decision_events
                   (recommendation_event_id, patient_link_id, decision, reason_code,
                    reason_text, actor_user_id, actor_username, occurred_at,
                    supersedes_event_id, legacy_source_suggestion_log_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    recommendation_event_id,
                    patient_link_id,
                    ClinicalDecision(decision).value,
                    reason_code,
                    reason_text,
                    actor_user_id,
                    actor,
                    _now_text(),
                    supersedes_event_id,
                    legacy_source_suggestion_log_id,
                ),
            )
        return int(cur.lastrowid)

    def recommendation_context(
        self, recommendation_event_id: int, *, patient_link_id: int
    ) -> dict | None:
        """Return one CREATED recommendation and its latest decision."""
        db = get_db()
        row = db.execute(
            """SELECT e.*, r.patient_link_id, r.run_status
               FROM clinical_recommendation_events e
               JOIN clinical_engine_runs r ON r.run_id=e.run_id
               WHERE e.id=? AND r.patient_link_id=? AND e.event_type='CREATED'""",
            (recommendation_event_id, patient_link_id),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["payload"] = json.loads(result["payload_json"])
        decision = db.execute(
            """SELECT * FROM clinical_decision_events
               WHERE recommendation_event_id=?
               ORDER BY occurred_at DESC, id DESC LIMIT 1""",
            (recommendation_event_id,),
        ).fetchone()
        result["current_decision"] = dict(decision) if decision else None
        return result

    def append_presentation_once(
        self, recommendation_event_id: int, *, patient_link_id: int
    ) -> int:
        """Append one PRESENTED event per run/evaluation recommendation."""
        db = get_db()
        now = _now_text()
        payload = _json_text({"source_event_id": recommendation_event_id})
        with db:
            cur = db.execute(
                """INSERT INTO clinical_recommendation_events
                   (run_id, evaluation_id, recommendation_key, action_type,
                    event_type, payload_json, created_at)
                   SELECT source.run_id, source.evaluation_id,
                          source.recommendation_key, source.action_type,
                          'PRESENTED', ?, ?
                   FROM clinical_recommendation_events source
                   JOIN clinical_engine_runs run ON run.run_id=source.run_id
                   WHERE source.id=? AND source.event_type='CREATED'
                     AND run.patient_link_id=? AND run.run_status<>'RUNNING'
                     AND NOT EXISTS (
                         SELECT 1 FROM clinical_recommendation_events prior
                         WHERE prior.run_id=source.run_id
                           AND prior.evaluation_id=source.evaluation_id
                           AND prior.recommendation_key=source.recommendation_key
                           AND prior.event_type='PRESENTED'
                     )""",
                (payload, now, recommendation_event_id, patient_link_id),
            )
            if cur.rowcount == 1:
                return int(cur.lastrowid)
            existing = db.execute(
                """SELECT presented.id
                   FROM clinical_recommendation_events source
                   JOIN clinical_engine_runs run ON run.run_id=source.run_id
                   JOIN clinical_recommendation_events presented
                     ON presented.run_id=source.run_id
                    AND presented.evaluation_id=source.evaluation_id
                    AND presented.recommendation_key=source.recommendation_key
                    AND presented.event_type='PRESENTED'
                   WHERE source.id=? AND source.event_type='CREATED'
                     AND run.patient_link_id=?""",
                (recommendation_event_id, patient_link_id),
            ).fetchone()
            if not existing:
                raise ValueError("recommendation is not presentable for this patient")
            return int(existing["id"])

    def append_current_decision(
        self,
        *,
        recommendation_event_id: int,
        patient_link_id: int,
        decision: ClinicalDecision,
        actor_username: str,
        actor_user_id: int | None,
        expected_current_event_id: int | None,
        reason_code: str | None = None,
        reason_text: str | None = None,
        legacy_source_suggestion_log_id: int | None = None,
    ) -> dict:
        """Atomically append a decision if the caller's projected state is current."""
        db = get_db()
        db.execute("BEGIN IMMEDIATE")
        try:
            context = db.execute(
                """SELECT e.id
                   FROM clinical_recommendation_events e
                   JOIN clinical_engine_runs r ON r.run_id=e.run_id
                   WHERE e.id=? AND e.event_type='CREATED'
                     AND r.patient_link_id=? AND r.run_status<>'RUNNING'""",
                (recommendation_event_id, patient_link_id),
            ).fetchone()
            if not context:
                raise ValueError("recommendation event does not belong to this patient")
            current = db.execute(
                """SELECT id FROM clinical_decision_events
                   WHERE recommendation_event_id=?
                   ORDER BY occurred_at DESC, id DESC LIMIT 1""",
                (recommendation_event_id,),
            ).fetchone()
            current_id = int(current["id"]) if current else None
            if current_id != expected_current_event_id:
                raise RuntimeError("STALE_DECISION_STATE")
            cur = db.execute(
                """INSERT INTO clinical_decision_events
                   (recommendation_event_id, patient_link_id, decision,
                    reason_code, reason_text, actor_user_id, actor_username,
                    occurred_at, supersedes_event_id,
                    legacy_source_suggestion_log_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    recommendation_event_id,
                    patient_link_id,
                    ClinicalDecision(decision).value,
                    reason_code,
                    reason_text,
                    actor_user_id,
                    actor_username,
                    _now_text(),
                    current_id,
                    legacy_source_suggestion_log_id,
                ),
            )
            row = db.execute(
                "SELECT * FROM clinical_decision_events WHERE id=?",
                (cur.lastrowid,),
            ).fetchone()
            db.commit()
            return dict(row)
        except Exception:
            db.rollback()
            raise

    def unimported_legacy_decisions(self) -> list[dict]:
        return [
            dict(row)
            for row in get_db().execute(
                """SELECT s.* FROM suggestion_log s
                   WHERE s.status IN ('accepted', 'dismissed')
                     AND NOT EXISTS (
                         SELECT 1 FROM clinical_decision_events d
                         WHERE d.legacy_source_suggestion_log_id=s.id
                     )
                   ORDER BY s.id"""
            ).fetchall()
        ]

    def recommendation_by_key(self, recommendation_key: str) -> dict | None:
        row = get_db().execute(
            """SELECT e.*, r.patient_link_id, r.run_status
               FROM clinical_recommendation_events e
               JOIN clinical_engine_runs r ON r.run_id=e.run_id
               WHERE e.recommendation_key=? AND e.event_type='CREATED'
               ORDER BY e.id DESC LIMIT 1""",
            (recommendation_key,),
        ).fetchone()
        return dict(row) if row else None

    def get_run(self, run_id: str) -> dict | None:
        db = get_db()
        row = db.execute(
            "SELECT * FROM clinical_engine_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["evaluations"] = [
            dict(item)
            for item in db.execute(
                "SELECT * FROM clinical_rule_evaluations WHERE run_id=? ORDER BY id",
                (run_id,),
            ).fetchall()
        ]
        result["recommendation_events"] = [
            dict(item)
            for item in db.execute(
                "SELECT * FROM clinical_recommendation_events WHERE run_id=? ORDER BY id",
                (run_id,),
            ).fetchall()
        ]
        return result

    def latest_presentable_run(self, patient_link_id: int) -> dict | None:
        """Return the latest terminal, non-failed run as decoded read-only data."""
        db = get_db()
        row = db.execute(
            """SELECT * FROM clinical_engine_runs
               WHERE patient_link_id=?
                 AND run_status IN ('COMPLETED', 'COMPLETED_WITH_ERRORS',
                                    'SAFETY_FAILED')
               ORDER BY started_at DESC, rowid DESC LIMIT 1""",
            (patient_link_id,),
        ).fetchone()
        if not row:
            return None
        run = dict(row)
        for key in (
            "fact_snapshot_json", "summary_json", "error_json",
            "legacy_compare_json",
        ):
            run[key.removesuffix("_json")] = (
                json.loads(run[key]) if run.get(key) else None
            )
        evaluations = []
        rows = db.execute(
            """SELECT e.*, r.rule_code, r.action_type, r.rule_json
               FROM clinical_rule_evaluations e
               JOIN clinical_rule_versions r ON r.id=e.rule_version_id
               WHERE e.run_id=? ORDER BY e.id""",
            (run["run_id"],),
        ).fetchall()
        for item in rows:
            evaluation = dict(item)
            rule_document = json.loads(evaluation.pop("rule_json"))
            evaluation.update({
                "rule_title": rule_document.get("title", evaluation["rule_code"]),
                "severity": rule_document.get("severity"),
                "priority": rule_document.get("priority"),
                "semantic_key": rule_document.get("semantic_key"),
            })
            for key in (
                "trace_json", "data_issues_json", "recommendation_json",
                "suppression_json", "error_json",
            ):
                evaluation[key.removesuffix("_json")] = (
                    json.loads(evaluation[key]) if evaluation.get(key) else None
                )
            evaluations.append(evaluation)
        run["evaluations"] = evaluations
        created_events = [
            dict(item)
            for item in db.execute(
                """SELECT * FROM clinical_recommendation_events
                   WHERE run_id=? AND event_type='CREATED' ORDER BY id""",
                (run["run_id"],),
            ).fetchall()
        ]
        event_by_evaluation = {}
        for event in created_events:
            event["payload"] = json.loads(event["payload_json"])
            decision = db.execute(
                """SELECT * FROM clinical_decision_events
                   WHERE recommendation_event_id=?
                   ORDER BY occurred_at DESC, id DESC LIMIT 1""",
                (event["id"],),
            ).fetchone()
            event["current_decision"] = dict(decision) if decision else None
            if event["evaluation_id"] is not None:
                event_by_evaluation[int(event["evaluation_id"])] = event
        for evaluation in evaluations:
            evaluation["recommendation_event"] = event_by_evaluation.get(
                int(evaluation["id"])
            )
        return run
