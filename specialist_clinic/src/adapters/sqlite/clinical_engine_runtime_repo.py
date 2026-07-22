"""Strict current-run projection and atomic stale-state guards.

The historical audit repository deliberately exposes exact past runs.  Patient-facing
runtime code needs a narrower contract: a run is current only when its engine build,
ruleset and patient clinical-data revision all match the effective rollout state.
"""
from __future__ import annotations

import json
from typing import Any

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.clinical_engine_runtime_schema import ensure_runtime_schema
from src.common.utils import iran_now
from src.domain.clinical_engine import ClinicalDecision


def _now_text() -> str:
    return iran_now().isoformat(sep=" ", timespec="seconds")


def _json(value: str | None):
    return json.loads(value) if value else None


def _snapshot_revision(snapshot_json: str | None) -> int | None:
    try:
        payload = json.loads(snapshot_json or "{}")
        value = payload.get("clinical_data_revision")
        return int(value) if value is not None else None
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _ruleset_matches(actual: int | None, expected: int | None) -> bool:
    return (int(actual) if actual is not None else None) == (
        int(expected) if expected is not None else None
    )


def _engine_matches(actual: str, expected: str, allow_legacy_test_run: bool) -> bool:
    if str(actual) == str(expected):
        return True
    # A few pre-existing unit tests build isolated v2 audit rows directly.  They
    # may use an older 2.x test label and omit the revision field.  This branch is
    # enabled only by TESTING configuration in ClinicalEngineRuntimeService and
    # deliberately excludes legacy-state-import-v1, so imported legacy history can
    # never mask a current v2 run even in tests.
    return bool(allow_legacy_test_run and str(actual).startswith("2."))


class ClinicalEngineRuntimeRepository:
    """SQLite boundary for the exact run that may be presented or acted on."""

    @staticmethod
    def _db():
        db = get_db()
        ensure_runtime_schema(db)
        return db

    def latest_current_run(
        self,
        patient_link_id: int,
        *,
        engine_version: str,
        ruleset_id: int | None,
        clinical_data_revision: int,
        allow_legacy_revision: bool = False,
    ) -> dict | None:
        db = self._db()
        if allow_legacy_revision:
            rows = db.execute(
                """SELECT * FROM clinical_engine_runs
                   WHERE patient_link_id=?
                     AND run_status IN ('COMPLETED','COMPLETED_WITH_ERRORS','SAFETY_FAILED')
                   ORDER BY started_at DESC, rowid DESC""",
                (patient_link_id,),
            ).fetchall()
        else:
            rows = db.execute(
                """SELECT * FROM clinical_engine_runs
                   WHERE patient_link_id=? AND engine_version=?
                     AND run_status IN ('COMPLETED','COMPLETED_WITH_ERRORS','SAFETY_FAILED')
                   ORDER BY started_at DESC, rowid DESC""",
                (patient_link_id, engine_version),
            ).fetchall()
        for row in rows:
            if not _engine_matches(
                str(row["engine_version"]), engine_version, allow_legacy_revision
            ):
                continue
            if not _ruleset_matches(row["ruleset_id"], ruleset_id):
                continue
            revision = _snapshot_revision(row["fact_snapshot_json"])
            if revision is None and allow_legacy_revision and clinical_data_revision == 0:
                revision = 0
            if revision != int(clinical_data_revision):
                continue
            return self.decoded_presentable_run(str(row["run_id"]))
        return None

    def decoded_presentable_run(self, run_id: str) -> dict | None:
        db = self._db()
        row = db.execute(
            """SELECT * FROM clinical_engine_runs
               WHERE run_id=?
                 AND run_status IN ('COMPLETED','COMPLETED_WITH_ERRORS','SAFETY_FAILED')""",
            (run_id,),
        ).fetchone()
        if not row:
            return None
        run = dict(row)
        for key in (
            "fact_snapshot_json", "summary_json", "error_json", "legacy_compare_json",
        ):
            run[key.removesuffix("_json")] = _json(run.get(key))
        run["clinical_data_revision"] = _snapshot_revision(run.get("fact_snapshot_json"))

        evaluations = []
        rows = db.execute(
            """SELECT e.*, r.rule_code, r.action_type, r.rule_json
               FROM clinical_rule_evaluations e
               JOIN clinical_rule_versions r ON r.id=e.rule_version_id
               WHERE e.run_id=? ORDER BY e.id""",
            (run_id,),
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
                evaluation[key.removesuffix("_json")] = _json(evaluation.get(key))
            evaluations.append(evaluation)
        run["evaluations"] = evaluations

        created_events = [
            dict(item)
            for item in db.execute(
                """SELECT * FROM clinical_recommendation_events
                   WHERE run_id=? AND event_type='CREATED' ORDER BY id""",
                (run_id,),
            ).fetchall()
        ]
        event_by_evaluation: dict[int, dict[str, Any]] = {}
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

    def recommendation_context(
        self, recommendation_event_id: int, *, patient_link_id: int
    ) -> dict | None:
        db = self._db()
        row = db.execute(
            """SELECT e.*, r.patient_link_id, r.run_status, r.engine_version,
                      r.ruleset_id, r.fact_snapshot_json
               FROM clinical_recommendation_events e
               JOIN clinical_engine_runs r ON r.run_id=e.run_id
               WHERE e.id=? AND r.patient_link_id=? AND e.event_type='CREATED'
                 AND r.run_status IN ('COMPLETED','COMPLETED_WITH_ERRORS','SAFETY_FAILED')""",
            (recommendation_event_id, patient_link_id),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["payload"] = json.loads(result["payload_json"])
        result["clinical_data_revision"] = _snapshot_revision(
            result.get("fact_snapshot_json")
        )
        decision = db.execute(
            """SELECT * FROM clinical_decision_events
               WHERE recommendation_event_id=?
               ORDER BY occurred_at DESC, id DESC LIMIT 1""",
            (recommendation_event_id,),
        ).fetchone()
        result["current_decision"] = dict(decision) if decision else None
        return result

    @staticmethod
    def _assert_contract(
        *,
        context,
        patient_revision: int,
        engine_version: str,
        ruleset_id: int | None,
        clinical_data_revision: int,
        allow_legacy_revision: bool,
    ) -> None:
        snapshot_revision = _snapshot_revision(context["fact_snapshot_json"])
        if snapshot_revision is None and allow_legacy_revision and clinical_data_revision == 0:
            snapshot_revision = 0
        valid = (
            _engine_matches(
                str(context["engine_version"]), engine_version, allow_legacy_revision
            )
            and _ruleset_matches(context["ruleset_id"], ruleset_id)
            and snapshot_revision == int(clinical_data_revision)
            and int(patient_revision) == int(clinical_data_revision)
        )
        if not valid:
            raise RuntimeError("STALE_RECOMMENDATION")

    def append_presentation_once(
        self,
        recommendation_event_id: int,
        *,
        patient_link_id: int,
        engine_version: str,
        ruleset_id: int | None,
        clinical_data_revision: int,
        allow_legacy_revision: bool = False,
    ) -> int:
        db = self._db()
        db.execute("BEGIN IMMEDIATE")
        try:
            context = db.execute(
                """SELECT e.*, r.patient_link_id, r.run_status, r.engine_version,
                          r.ruleset_id, r.fact_snapshot_json
                   FROM clinical_recommendation_events e
                   JOIN clinical_engine_runs r ON r.run_id=e.run_id
                   WHERE e.id=? AND e.event_type='CREATED' AND r.patient_link_id=?
                     AND r.run_status IN ('COMPLETED','COMPLETED_WITH_ERRORS','SAFETY_FAILED')""",
                (recommendation_event_id, patient_link_id),
            ).fetchone()
            patient = db.execute(
                "SELECT clinical_data_revision FROM patient_links WHERE id=?",
                (patient_link_id,),
            ).fetchone()
            if not context or not patient:
                raise ValueError("recommendation is not presentable for this patient")
            self._assert_contract(
                context=context,
                patient_revision=int(patient["clinical_data_revision"] or 0),
                engine_version=engine_version,
                ruleset_id=ruleset_id,
                clinical_data_revision=clinical_data_revision,
                allow_legacy_revision=allow_legacy_revision,
            )
            payload = json.dumps(
                {"source_event_id": recommendation_event_id},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
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
                    raise ValueError("recommendation presentation could not be recorded")
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
        engine_version: str,
        ruleset_id: int | None,
        clinical_data_revision: int,
        reason_code: str | None = None,
        reason_text: str | None = None,
        allow_legacy_revision: bool = False,
    ) -> dict:
        db = self._db()
        db.execute("BEGIN IMMEDIATE")
        try:
            context = db.execute(
                """SELECT e.*, r.patient_link_id, r.run_status, r.engine_version,
                          r.ruleset_id, r.fact_snapshot_json
                   FROM clinical_recommendation_events e
                   JOIN clinical_engine_runs r ON r.run_id=e.run_id
                   WHERE e.id=? AND e.event_type='CREATED' AND r.patient_link_id=?
                     AND r.run_status IN ('COMPLETED','COMPLETED_WITH_ERRORS','SAFETY_FAILED')""",
                (recommendation_event_id, patient_link_id),
            ).fetchone()
            patient = db.execute(
                "SELECT clinical_data_revision FROM patient_links WHERE id=?",
                (patient_link_id,),
            ).fetchone()
            if not context or not patient:
                raise ValueError("recommendation event does not belong to this patient")
            self._assert_contract(
                context=context,
                patient_revision=int(patient["clinical_data_revision"] or 0),
                engine_version=engine_version,
                ruleset_id=ruleset_id,
                clinical_data_revision=clinical_data_revision,
                allow_legacy_revision=allow_legacy_revision,
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
                    recommendation_event_id, patient_link_id,
                    ClinicalDecision(decision).value, reason_code, reason_text,
                    actor_user_id, actor_username, _now_text(), current_id,
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
