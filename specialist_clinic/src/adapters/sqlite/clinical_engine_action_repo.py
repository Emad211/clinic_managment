"""Atomic presentation and decision writes for current Clinical Engine v2 output.

Read-side current-run selection is handled by ``clinical_engine_runtime_repo``.
This repository owns the narrower write contract: while holding SQLite's write
lock it revalidates patient revision, engine build, exact ruleset, raw mode and
the activation seal. A concurrent rollback or approval revocation therefore
linearizes either before the write (the write is rejected) or after it (the
write completed while the rollout was still valid).
"""
from __future__ import annotations

import json

from src.adapters.sqlite.clinical_engine_activation_repo import (
    ClinicalEngineActivationRepository,
)
from src.adapters.sqlite.clinical_engine_runtime_repo import (
    ClinicalEngineRuntimeRepository,
)
from src.common.utils import iran_now
from src.domain.clinical_engine import ClinicalDecision


def _now_text() -> str:
    return iran_now().isoformat(sep=" ", timespec="seconds")


def _snapshot_revision(snapshot_json: str | None) -> int | None:
    try:
        payload = json.loads(snapshot_json or "{}")
        value = payload.get("clinical_data_revision")
        return int(value) if value is not None else None
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _same_optional_int(left, right) -> bool:
    return (int(left) if left is not None else None) == (
        int(right) if right is not None else None
    )


def _engine_matches(actual: str, expected: str, allow_legacy_test_run: bool) -> bool:
    return str(actual) == str(expected) or bool(
        allow_legacy_test_run and str(actual).startswith("2.")
    )


class ClinicalEngineActionRepository:
    """Append presentation/decision events only for the effective current run."""

    def __init__(self, *, runtime_repo=None, activation=None):
        self.runtime_repo = runtime_repo or ClinicalEngineRuntimeRepository()
        self.activation = activation or ClinicalEngineActivationRepository()

    def _db(self):
        return self.runtime_repo._db()  # one verified connection boundary

    def _assert_contract(
        self,
        db,
        *,
        context,
        patient_revision: int,
        mode: str,
        engine_version: str,
        ruleset_id: int | None,
        clinical_data_revision: int,
        allow_legacy_test_run: bool,
    ) -> None:
        snapshot_revision = _snapshot_revision(context["fact_snapshot_json"])
        if (
            snapshot_revision is None
            and allow_legacy_test_run
            and clinical_data_revision == 0
        ):
            snapshot_revision = 0

        raw = db.execute(
            "SELECT value FROM settings WHERE key='clinical_engine_v2_mode'"
        ).fetchone()
        raw_mode = str(raw["value"] if raw else "off").strip().lower()
        valid = (
            raw_mode == mode
            and _engine_matches(
                str(context["engine_version"]),
                engine_version,
                allow_legacy_test_run,
            )
            and _same_optional_int(context["ruleset_id"], ruleset_id)
            and snapshot_revision == int(clinical_data_revision)
            and int(patient_revision) == int(clinical_data_revision)
        )
        if not valid:
            raise RuntimeError("STALE_RECOMMENDATION")

        # Test fixtures may build isolated 2.x audit rows without a production
        # seal. Production actions must still be tied to the exact valid seal.
        if not allow_legacy_test_run and not self.activation.valid_seal(mode):
            raise RuntimeError("STALE_RECOMMENDATION")

    def append_presentation_once(
        self,
        recommendation_event_id: int,
        *,
        patient_link_id: int,
        mode: str,
        engine_version: str,
        ruleset_id: int | None,
        clinical_data_revision: int,
        allow_legacy_test_run: bool = False,
    ) -> int:
        db = self._db()
        db.execute("BEGIN IMMEDIATE")
        try:
            context = db.execute(
                """SELECT e.*, r.patient_link_id, r.run_status, r.engine_version,
                          r.ruleset_id, r.fact_snapshot_json
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
                    "recommendation is not presentable for this patient"
                )
            self._assert_contract(
                db,
                context=context,
                patient_revision=int(patient["clinical_data_revision"] or 0),
                mode=mode,
                engine_version=engine_version,
                ruleset_id=ruleset_id,
                clinical_data_revision=clinical_data_revision,
                allow_legacy_test_run=allow_legacy_test_run,
            )

            payload = json.dumps(
                {"source_event_id": recommendation_event_id},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            cur = db.execute(
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
            if cur.rowcount == 1:
                event_id = int(cur.lastrowid)
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
        reason_code: str | None = None,
        reason_text: str | None = None,
        allow_legacy_test_run: bool = False,
    ) -> dict:
        db = self._db()
        db.execute("BEGIN IMMEDIATE")
        try:
            context = db.execute(
                """SELECT e.*, r.patient_link_id, r.run_status, r.engine_version,
                          r.ruleset_id, r.fact_snapshot_json
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
                    "recommendation event does not belong to this patient"
                )
            self._assert_contract(
                db,
                context=context,
                patient_revision=int(patient["clinical_data_revision"] or 0),
                mode=mode,
                engine_version=engine_version,
                ruleset_id=ruleset_id,
                clinical_data_revision=clinical_data_revision,
                allow_legacy_test_run=allow_legacy_test_run,
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

            cur = db.execute(
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
                (cur.lastrowid,),
            ).fetchone()
            db.commit()
            return dict(row)
        except Exception:
            db.rollback()
            raise
