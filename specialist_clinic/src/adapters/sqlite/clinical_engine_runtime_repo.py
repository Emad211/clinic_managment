"""Exact read-side projection for current Clinical Engine v2 runs.

Historical audit access remains available through the audit repository. This boundary
returns only a terminal run whose engine identity, ruleset, patient clinical-data
revision and immutable evaluation-context hash exactly match the caller's contract.
"""
from __future__ import annotations

import json
from typing import Any

from src.adapters.sqlite.clinical_context_schema import (
    ensure_clinical_context_storage,
)
from src.adapters.sqlite.clinical_engine_current_contract import (
    same_optional_int,
    snapshot_context_hash,
    snapshot_revision,
)
from src.adapters.sqlite.clinical_engine_runtime_schema import ensure_runtime_schema
from src.adapters.sqlite.core import get_db


_TERMINAL_PRESENTABLE = (
    "COMPLETED",
    "COMPLETED_WITH_ERRORS",
    "SAFETY_FAILED",
)


def _json(value: str | None):
    return json.loads(value) if value else None


class ClinicalEngineRuntimeRepository:
    """SQLite boundary for the exact run that may be presented or acted on."""

    @staticmethod
    def _db():
        db = get_db()
        ensure_runtime_schema(db)
        ensure_clinical_context_storage(db)
        return db

    def latest_current_run(
        self,
        patient_link_id: int,
        *,
        engine_version: str,
        ruleset_id: int | None,
        clinical_data_revision: int,
        context_hash: str,
    ) -> dict | None:
        rows = self._db().execute(
            """SELECT * FROM clinical_engine_runs
               WHERE patient_link_id=? AND engine_version=? AND context_hash=?
                 AND run_status IN
                     ('COMPLETED','COMPLETED_WITH_ERRORS','SAFETY_FAILED')
               ORDER BY started_at DESC, rowid DESC""",
            (patient_link_id, engine_version, context_hash),
        ).fetchall()
        for row in rows:
            if not same_optional_int(row["ruleset_id"], ruleset_id):
                continue
            if snapshot_revision(row["fact_snapshot_json"]) != int(
                clinical_data_revision
            ):
                continue
            if snapshot_context_hash(row["fact_snapshot_json"]) != context_hash:
                continue
            return self.decoded_presentable_run(str(row["run_id"]))
        return None

    def decoded_presentable_run(self, run_id: str) -> dict | None:
        db = self._db()
        row = db.execute(
            """SELECT * FROM clinical_engine_runs
               WHERE run_id=?
                 AND run_status IN
                     ('COMPLETED','COMPLETED_WITH_ERRORS','SAFETY_FAILED')""",
            (run_id,),
        ).fetchone()
        if not row:
            return None
        run = dict(row)
        for key in (
            "fact_snapshot_json",
            "context_json",
            "summary_json",
            "error_json",
            "legacy_compare_json",
        ):
            run[key.removesuffix("_json")] = _json(run.get(key))
        run["clinical_data_revision"] = snapshot_revision(
            run.get("fact_snapshot_json")
        )

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
            evaluation.update(
                {
                    "rule_title": rule_document.get(
                        "title", evaluation["rule_code"]
                    ),
                    "severity": rule_document.get("severity"),
                    "priority": rule_document.get("priority"),
                    "semantic_key": rule_document.get("semantic_key"),
                }
            )
            for key in (
                "trace_json",
                "data_issues_json",
                "recommendation_json",
                "suppression_json",
                "error_json",
            ):
                evaluation[key.removesuffix("_json")] = _json(
                    evaluation.get(key)
                )
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
        self,
        recommendation_event_id: int,
        *,
        patient_link_id: int,
    ) -> dict | None:
        db = self._db()
        row = db.execute(
            """SELECT e.*, r.patient_link_id, r.run_status, r.engine_version,
                      r.ruleset_id, r.fact_snapshot_json, r.evaluation_mode,
                      r.context_key, r.context_json, r.context_hash,
                      r.encounter_key, r.encounter_event_id
               FROM clinical_recommendation_events e
               JOIN clinical_engine_runs r ON r.run_id=e.run_id
               WHERE e.id=? AND r.patient_link_id=? AND e.event_type='CREATED'
                 AND r.run_status IN
                     ('COMPLETED','COMPLETED_WITH_ERRORS','SAFETY_FAILED')""",
            (recommendation_event_id, patient_link_id),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["payload"] = json.loads(result["payload_json"])
        result["context"] = _json(result.get("context_json"))
        result["clinical_data_revision"] = snapshot_revision(
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
