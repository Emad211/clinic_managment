"""Recommendation presentation and clinician-decision audit writes."""
from __future__ import annotations

import json

from src.adapters.sqlite.core import get_db
from src.domain.clinical_engine import ClinicalDecision

from .clinical_engine_audit_common import json_text, now_text


class DecisionAuditRepositoryMixin:
    """Append v2 presentation and decision events without v1 lineage."""

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
    ) -> int:
        actor = (actor_username or "").strip()
        if not actor:
            raise ValueError("actor_username is required")
        db = get_db()
        recommendation = db.execute(
            """SELECT event.run_id, run.patient_link_id
               FROM clinical_recommendation_events event
               JOIN clinical_engine_runs run ON run.run_id=event.run_id
               WHERE event.id=?""",
            (recommendation_event_id,),
        ).fetchone()
        if (
            not recommendation
            or int(recommendation["patient_link_id"])
            != int(patient_link_id)
        ):
            raise ValueError(
                "recommendation event does not belong to this patient"
            )
        if supersedes_event_id is not None:
            prior = db.execute(
                """SELECT recommendation_event_id, patient_link_id
                   FROM clinical_decision_events WHERE id=?""",
                (supersedes_event_id,),
            ).fetchone()
            if (
                not prior
                or int(prior["recommendation_event_id"])
                != int(recommendation_event_id)
                or int(prior["patient_link_id"]) != int(patient_link_id)
            ):
                raise ValueError(
                    "superseded decision must belong to the same recommendation"
                )
        with db:
            cursor = db.execute(
                """INSERT INTO clinical_decision_events
                   (recommendation_event_id, patient_link_id, decision,
                    reason_code, reason_text, actor_user_id, actor_username,
                    occurred_at, supersedes_event_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    recommendation_event_id,
                    patient_link_id,
                    ClinicalDecision(decision).value,
                    reason_code,
                    reason_text,
                    actor_user_id,
                    actor,
                    now_text(),
                    supersedes_event_id,
                ),
            )
        return int(cursor.lastrowid)

    def recommendation_context(
        self,
        recommendation_event_id: int,
        *,
        patient_link_id: int,
    ) -> dict | None:
        """Return one CREATED recommendation and its latest decision."""
        db = get_db()
        row = db.execute(
            """SELECT event.*, run.patient_link_id, run.run_status
               FROM clinical_recommendation_events event
               JOIN clinical_engine_runs run ON run.run_id=event.run_id
               WHERE event.id=? AND run.patient_link_id=?
                 AND event.event_type='CREATED'""",
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
        self,
        recommendation_event_id: int,
        *,
        patient_link_id: int,
    ) -> int:
        """Append one PRESENTED event per run/evaluation recommendation."""
        db = get_db()
        payload = json_text({"source_event_id": recommendation_event_id})
        with db:
            cursor = db.execute(
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
                (
                    payload,
                    now_text(),
                    recommendation_event_id,
                    patient_link_id,
                ),
            )
            if cursor.rowcount == 1:
                return int(cursor.lastrowid)
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
                raise ValueError(
                    "recommendation is not presentable for this patient"
                )
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
    ) -> dict:
        """Append a decision only if the projected latest event is unchanged."""
        db = get_db()
        db.execute("BEGIN IMMEDIATE")
        try:
            context = db.execute(
                """SELECT event.id
                   FROM clinical_recommendation_events event
                   JOIN clinical_engine_runs run ON run.run_id=event.run_id
                   WHERE event.id=? AND event.event_type='CREATED'
                     AND run.patient_link_id=? AND run.run_status<>'RUNNING'""",
                (recommendation_event_id, patient_link_id),
            ).fetchone()
            if not context:
                raise ValueError(
                    "recommendation event does not belong to this patient"
                )
            current = db.execute(
                """SELECT id FROM clinical_decision_events
                   WHERE recommendation_event_id=?
                   ORDER BY occurred_at DESC, id DESC LIMIT 1""",
                (recommendation_event_id,),
            ).fetchone()
            current_id = int(current["id"]) if current else None
            if current_id != expected_current_event_id:
                raise RuntimeError("STALE_DECISION_STATE")
            cursor = db.execute(
                """INSERT INTO clinical_decision_events
                   (recommendation_event_id, patient_link_id, decision,
                    reason_code, reason_text, actor_user_id, actor_username,
                    occurred_at, supersedes_event_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    recommendation_event_id,
                    patient_link_id,
                    ClinicalDecision(decision).value,
                    reason_code,
                    reason_text,
                    actor_user_id,
                    actor_username,
                    now_text(),
                    current_id,
                ),
            )
            row = db.execute(
                "SELECT * FROM clinical_decision_events WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
            db.commit()
            return dict(row)
        except Exception:
            db.rollback()
            raise

    def recommendation_by_key(
        self,
        recommendation_key: str,
    ) -> dict | None:
        row = get_db().execute(
            """SELECT event.*, run.patient_link_id, run.run_status
               FROM clinical_recommendation_events event
               JOIN clinical_engine_runs run ON run.run_id=event.run_id
               WHERE event.recommendation_key=?
                 AND event.event_type='CREATED'
               ORDER BY event.id DESC LIMIT 1""",
            (recommendation_key,),
        ).fetchone()
        return dict(row) if row else None
