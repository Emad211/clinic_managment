"""Read-only decoding and presentation projections for Clinical Engine v2 audit."""
from __future__ import annotations

import json

from src.adapters.sqlite.core import get_db


_DECODED_RUN_FIELDS = (
    "fact_snapshot_json",
    "summary_json",
    "error_json",
    "legacy_compare_json",
)
_EVALUATION_JSON_FIELDS = (
    "trace_json",
    "data_issues_json",
    "recommendation_json",
    "suppression_json",
    "error_json",
)


def _decode_optional_json(row: dict, key: str) -> None:
    row[key.removesuffix("_json")] = (
        json.loads(row[key]) if row.get(key) else None
    )


class AuditProjectionRepositoryMixin:
    """Decode immutable audit rows without projecting retired v1 identifiers."""

    def get_run(self, run_id: str) -> dict | None:
        db = get_db()
        row = db.execute(
            "SELECT * FROM clinical_engine_runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["evaluations"] = [
            dict(item)
            for item in db.execute(
                "SELECT * FROM clinical_rule_evaluations "
                "WHERE run_id=? ORDER BY id",
                (run_id,),
            ).fetchall()
        ]
        result["recommendation_events"] = [
            dict(item)
            for item in db.execute(
                "SELECT * FROM clinical_recommendation_events "
                "WHERE run_id=? ORDER BY id",
                (run_id,),
            ).fetchall()
        ]
        return result

    def decoded_run(self, run_id: str | None) -> dict | None:
        """Return one exact run with decoded rule metadata for comparisons."""
        if not run_id:
            return None
        db = get_db()
        row = db.execute(
            "SELECT * FROM clinical_engine_runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if not row:
            return None
        run = dict(row)
        for key in _DECODED_RUN_FIELDS:
            _decode_optional_json(run, key)

        evaluations = []
        rows = db.execute(
            """SELECT evaluation.*, version.rule_code, version.action_type,
                      version.rule_json
               FROM clinical_rule_evaluations evaluation
               JOIN clinical_rule_versions version
                 ON version.id=evaluation.rule_version_id
               WHERE evaluation.run_id=?
               ORDER BY evaluation.id""",
            (run_id,),
        ).fetchall()
        for item in rows:
            value = dict(item)
            rule = json.loads(value.pop("rule_json"))
            value["rule_title"] = rule.get(
                "title", value["rule_code"]
            )
            value["severity"] = rule.get("severity")
            value["semantic_key"] = rule.get("semantic_key")
            for key in _EVALUATION_JSON_FIELDS:
                _decode_optional_json(value, key)
            evaluations.append(value)
        run["evaluations"] = evaluations
        return run

    def latest_presentable_run(
        self,
        patient_link_id: int,
    ) -> dict | None:
        """Return the latest terminal, non-failed run as decoded data."""
        db = get_db()
        row = db.execute(
            """SELECT * FROM clinical_engine_runs
               WHERE patient_link_id=?
                 AND run_status IN (
                     'COMPLETED', 'COMPLETED_WITH_ERRORS', 'SAFETY_FAILED'
                 )
               ORDER BY started_at DESC, rowid DESC LIMIT 1""",
            (patient_link_id,),
        ).fetchone()
        if not row:
            return None
        run = dict(row)
        for key in _DECODED_RUN_FIELDS:
            _decode_optional_json(run, key)

        evaluations = []
        rows = db.execute(
            """SELECT evaluation.*, version.rule_code, version.action_type,
                      version.rule_json
               FROM clinical_rule_evaluations evaluation
               JOIN clinical_rule_versions version
                 ON version.id=evaluation.rule_version_id
               WHERE evaluation.run_id=?
               ORDER BY evaluation.id""",
            (run["run_id"],),
        ).fetchall()
        for item in rows:
            evaluation = dict(item)
            rule = json.loads(evaluation.pop("rule_json"))
            evaluation.update(
                {
                    "rule_title": rule.get(
                        "title", evaluation["rule_code"]
                    ),
                    "severity": rule.get("severity"),
                    "priority": rule.get("priority"),
                    "semantic_key": rule.get("semantic_key"),
                }
            )
            for key in _EVALUATION_JSON_FIELDS:
                _decode_optional_json(evaluation, key)
            evaluations.append(evaluation)
        run["evaluations"] = evaluations

        created_events = [
            dict(item)
            for item in db.execute(
                """SELECT * FROM clinical_recommendation_events
                   WHERE run_id=? AND event_type='CREATED'
                   ORDER BY id""",
                (run["run_id"],),
            ).fetchall()
        ]
        event_by_evaluation: dict[int, dict] = {}
        for event in created_events:
            event["payload"] = json.loads(event["payload_json"])
            decision = db.execute(
                """SELECT * FROM clinical_decision_events
                   WHERE recommendation_event_id=?
                   ORDER BY occurred_at DESC, id DESC LIMIT 1""",
                (event["id"],),
            ).fetchone()
            event["current_decision"] = (
                dict(decision) if decision else None
            )
            if event["evaluation_id"] is not None:
                event_by_evaluation[int(event["evaluation_id"])] = event
        for evaluation in evaluations:
            evaluation["recommendation_event"] = event_by_evaluation.get(
                int(evaluation["id"])
            )
        return run
