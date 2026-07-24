"""Strict worklist writes derived from exact current Clinical Engine output."""
from __future__ import annotations

import sqlite3

from src.adapters.sqlite.clinical_engine_activation_repo import (
    ClinicalEngineActivationRepository,
)
from src.adapters.sqlite.clinical_engine_current_contract import (
    assert_current_rollout_contract,
)
from src.adapters.sqlite.clinical_engine_runtime_schema import (
    ensure_runtime_schema,
)
from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.followups_repo import FollowupRepository


class ClinicalFollowupRepository(FollowupRepository):
    """Add clinical tasks only while their sealed source run remains current."""

    def __init__(self, *, activation=None):
        self.activation = activation or ClinicalEngineActivationRepository()

    def _assert_current_source(self, db, task: dict) -> None:
        context = db.execute(
            """SELECT r.engine_version, r.ruleset_id, r.fact_snapshot_json,
                      r.context_hash, r.run_status, p.clinical_data_revision,
                      EXISTS(
                          SELECT 1 FROM clinical_recommendation_events e
                          WHERE e.id=? AND e.run_id=r.run_id
                            AND e.event_type='CREATED'
                      ) AS recommendation_matches
               FROM clinical_engine_runs r
               JOIN patient_links p ON p.id=r.patient_link_id
               WHERE r.run_id=? AND r.patient_link_id=?""",
            (
                task["source_recommendation_event_id"],
                task["source_run_id"],
                task["patient_link_id"],
            ),
        ).fetchone()
        if (
            not context
            or not context["recommendation_matches"]
            or context["run_status"]
            not in {"COMPLETED", "COMPLETED_WITH_ERRORS"}
        ):
            raise RuntimeError("STALE_CLINICAL_TASK_SOURCE")
        assert_current_rollout_contract(
            db,
            context=context,
            patient_revision=int(
                context["clinical_data_revision"] or 0
            ),
            mode=str(task["source_mode"]),
            engine_version=str(task["source_engine_version"]),
            ruleset_id=task.get("source_ruleset_id"),
            clinical_data_revision=int(
                task["source_clinical_data_revision"]
            ),
            context_hash=str(task["clinical_context_hash"]),
            error_code="STALE_CLINICAL_TASK_SOURCE",
            activation=self.activation,
        )

    @staticmethod
    def _existing(db, task: dict):
        return db.execute(
            """SELECT id FROM followup_tasks
               WHERE clinical_task_key=?
                  OR (patient_link_id=? AND clinical_semantic_key=?
                      AND clinical_context_hash=?
                      AND source_engine='clinical_v2' AND status='open')
               ORDER BY id LIMIT 1""",
            (
                task["clinical_task_key"],
                task["patient_link_id"],
                task["clinical_semantic_key"],
                task["clinical_context_hash"],
            ),
        ).fetchone()

    def create_clinical_task_once(
        self, task: dict
    ) -> tuple[int, bool]:
        db = get_db()
        ensure_runtime_schema(db)
        db.execute("BEGIN IMMEDIATE")
        try:
            self._assert_current_source(db, task)
            existing = self._existing(db, task)
            if existing:
                db.commit()
                return int(existing["id"]), False
            cursor = db.execute(
                """INSERT INTO followup_tasks
                   (patient_link_id, reason, detail, due_date, fulfillment,
                    source_rule, source_event, source_engine, source_run_id,
                    source_recommendation_event_id, clinical_semantic_key,
                    clinical_context_hash, clinical_task_key)
                   VALUES (?, ?, ?, ?, 'in_person', ?, 'clinical_due',
                           'clinical_v2', ?, ?, ?, ?, ?)""",
                (
                    task["patient_link_id"],
                    task["reason"],
                    task["detail"],
                    task["due_date"],
                    task["source_rule"],
                    task["source_run_id"],
                    task["source_recommendation_event_id"],
                    task["clinical_semantic_key"],
                    task["clinical_context_hash"],
                    task["clinical_task_key"],
                ),
            )
            db.commit()
            return int(cursor.lastrowid), True
        except sqlite3.IntegrityError:
            db.rollback()
            existing = self._existing(db, task)
            if existing:
                return int(existing["id"]), False
            raise
        except Exception:
            db.rollback()
            raise
