"""Atomic presentation and decision writes for exact current Clinical Engine output."""
from __future__ import annotations

import json

from src.adapters.sqlite.clinical_engine_activation_repo import (
    ClinicalEngineActivationRepository,
)
from src.adapters.sqlite.clinical_engine_current_contract import (
    assert_current_rollout_contract,
)
from src.adapters.sqlite.clinical_engine_runtime_repo import (
    ClinicalEngineRuntimeRepository,
)
from src.common.utils import iran_now
from src.domain.clinical_engine import ClinicalDecision


def _now_text() -> str:
    return iran_now().isoformat(sep=" ", timespec="seconds")


class ClinicalEngineActionRepository:
    """Append action events only while the sealed context-specific run is current."""

    def __init__(self, *, runtime_repo=None, activation=None):
        self.runtime_repo = runtime_repo or ClinicalEngineRuntimeRepository()
        self.activation = activation or ClinicalEngineActivationRepository()

    def _db(self):
        return self.runtime_repo._db()

    @staticmethod
    def _context(db, recommendation_event_id: int, patient_link_id: int):
        context = db.execute(
            """SELECT e.*, r.patient_link_id, r.run_status, r.engine_version,
                      r.ruleset_id, r.fact_snapshot_json, r.context_hash,
                      r.context_json, r.evaluation_mode, r.context_key,
                      r.encounter_key, r.encounter_event_id
               FROM clinical_recommendation_events e
               JOIN clinical_engine_runs r ON r.run_id=e.run_id
               WHERE e.id=? AND e.event_type='CREATED'
                 AND r.patient_link_id=?
                 AND r.run_status IN
                     ('COMPLETED','COMPLETED_WITH_ERRORS','SAFETY_FAILED')""",
            (recommendation_event_id, patient_link_id),
        ).fetchone()
        patient = db.execute(
            "SELECT clinical_data_revision FROM patient_links WHERE id=?",
            (patient_link_id,),
        ).fetchone()
        if not context or not patient:
            raise ValueError(
                "recommendation event is unavailable for this patient"
            )
        return context, int(patient["clinical_data_revision"] or 0)

    def _assert_current(
        self,
        db,
        *,
        context,
        patient_revision: int,
        mode: str,
        engine_version: str,
        ruleset_id: int | None,
        clinical_data_revision: int,
        context_hash: str,
    ) -> None:
        assert_current_rollout_contract(
            db,
            context=context,
            patient_revision=patient_revision,
            mode=mode,
            engine_version=engine_version,
            ruleset_id=ruleset_id,
            clinical_data_revision=clinical_data_revision,
            context_hash=context_hash,
            error_code="STALE_RECOMMENDATION",
            activation=self.activation,
        )

    def append_presentation_once(
        self,
        recommendation_event_id: int,
        *,
        patient_link_id: int,
        mode: str,
        engine_version: str,
        ruleset_id: int | None,
        clinical_data_revision: int,
        context_hash: str,
    ) -> int:
        db = self._db()
        db.execute("BEGIN IMMEDIATE")
        try:
            context, patient_revision = self._context(
                db, recommendation_event_id, patient_link_id
            )
            self._assert_current(
                db,
                context=context,
                patient_revision=patient_revision,
                mode=mode,
                engine_version=engine_version,
                ruleset_id=ruleset_id,
                clinical_data_revision=clinical_data_revision,
                context_hash=context_hash,
            )
            payload = json.dumps(
                {
                    "source_event_id": recommendation_event_id,
                    "context_hash": context_hash,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            cursor = db.execute(
                """INSERT INTO clinical_recommendation_events
                   (run_id, evaluation_id, recommendation_key, action_type,
                    event_type, payload_json, created_at)
                   SELECT source.run_id, source.evaluation_id,
                          source.recommendation_key, source.action_type,
                          'PRESENTED', ?, ?
                   FROM clinical_recommendation_events source
                   WHERE source.id=? AND source.event_type='CREATED'
                     AND NOT EXISTS (
                         SELECT 1 FROM clinical_recommendation_events prior
                         WHERE prior.run_id=source.run_id
                           AND prior.evaluation_id=source.evaluation_id
                           AND prior.recommendation_key=source.recommendation_key
                           AND prior.event_type='PRESENTED'
                     )""",
                (payload, _now_text(), recommendation_event_id),
            )
            if cursor.rowcount == 1:
                event_id = int(cursor.lastrowid)
            else:
                existing = db.execute(
                    """SELECT presented.id
                       FROM clinical_recommendation_events source
                       JOIN clinical_recommendation_events presented
                         ON presented.run_id=source.run_id
                        AND presented.evaluation_id=source.evaluation_id
                        AND presented.recommendation_key=source.recommendation_key
                        AND presented.event_type='PRESENTED'
                       WHERE source.id=? AND source.event_type='CREATED'""",
                    (recommendation_event_id,),
                ).fetchone()
                if not existing:
                    raise ValueError(
                        "recommendation presentation could not be recorded"
                    )
                event_id = int(existing["id"])
            db.commit()
            return event_id
        except Exception:
            db.rollback()
            raise

    def append_current_decision(
        self,
        *,
        recommendation_event_id: int,
        patient_link_id: int,
        decision: ClinicalDecision,
        actor_username: str,
        actor_user_id: int | None,
        expected_current_event_id: int | None,
        mode: str,
        engine_version: str,
        ruleset_id: int | None,
        clinical_data_revision: int,
        context_hash: str,
        reason_code: str | None = None,
        reason_text: str | None = None,
    ) -> dict:
        db = self._db()
        db.execute("BEGIN IMMEDIATE")
        try:
            context, patient_revision = self._context(
                db, recommendation_event_id, patient_link_id
            )
            self._assert_current(
                db,
                context=context,
                patient_revision=patient_revision,
                mode=mode,
                engine_version=engine_version,
                ruleset_id=ruleset_id,
                clinical_data_revision=clinical_data_revision,
                context_hash=context_hash,
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
                    _now_text(),
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
