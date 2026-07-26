"""Repository for signed encounter plan commitments and Worklist projections."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import sqlite3
from typing import Any

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.encounter_plan_commitment_schema import (
    COMMITMENT_TYPES,
    ensure_encounter_plan_commitment_storage,
)
from src.common.utils import iran_now


class EncounterPlanCommitmentConflict(RuntimeError):
    pass


class EncounterPlanCommitmentValidationError(ValueError):
    pass


_OPEN_STATUSES = {"OPEN", "IN_PROGRESS", "SCHEDULED"}
_TERMINAL_STATUSES = {"COMPLETED", "CANCELLED", "ENTERED_IN_ERROR"}


def _hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _time(value: datetime | str | None = None) -> str:
    current = value or iran_now()
    if isinstance(current, str):
        parsed = datetime.fromisoformat(current.replace("Z", "+00:00"))
    else:
        parsed = current
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    return parsed.isoformat(sep=" ", timespec="seconds")


def _commitment_id(document_event_id: int, client_key: str) -> str:
    digest = hashlib.sha256(
        f"encounter-plan:{int(document_event_id)}:{client_key}".encode("utf-8")
    ).hexdigest()
    return "plan_commitment_" + digest[:32]


class EncounterPlanCommitmentRepository:
    def __init__(self, db: sqlite3.Connection | None = None):
        self._connection = db

    def _db(self) -> sqlite3.Connection:
        db = self._connection or get_db()
        installed = db.execute(
            """SELECT 1 FROM sqlite_master
               WHERE type='table' AND name='care_plan_commitments'"""
        ).fetchone()
        if not installed:
            if db.in_transaction:
                raise RuntimeError(
                    "plan commitment storage is missing inside caller transaction"
                )
            ensure_encounter_plan_commitment_storage(db)
        return db

    @staticmethod
    def _row(row) -> dict | None:
        return dict(row) if row else None

    def commitment(self, commitment_id: str) -> dict | None:
        return self._row(
            self._db().execute(
                "SELECT * FROM care_plan_commitments WHERE commitment_id=?",
                (str(commitment_id),),
            ).fetchone()
        )

    def commitment_for_task(self, task_id: int) -> dict | None:
        return self._row(
            self._db().execute(
                """SELECT commitment.*,link.task_id
                   FROM care_plan_commitment_task_links link
                   JOIN care_plan_commitments commitment
                     ON commitment.commitment_id=link.commitment_id
                   WHERE link.task_id=?""",
                (int(task_id),),
            ).fetchone()
        )

    def current_event(self, commitment_id: str) -> dict | None:
        return self._row(
            self._db().execute(
                """SELECT * FROM care_plan_commitment_events
                   WHERE commitment_id=?
                   ORDER BY recorded_at DESC,id DESC LIMIT 1""",
                (str(commitment_id),),
            ).fetchone()
        )

    def current_for_task(self, task_id: int) -> dict | None:
        row = self._db().execute(
            """SELECT commitment.*,link.task_id,
                      event.id AS current_event_id,
                      event.event_type AS current_event_type,
                      event.status AS current_status,
                      event.due_at AS current_due_at,
                      event.assigned_to AS current_assigned_to,
                      event.appointment_id AS current_appointment_id,
                      event.evidence_type AS current_evidence_type,
                      event.evidence_ref AS current_evidence_ref,
                      event.outcome_code AS current_outcome_code,
                      event.note AS current_note,
                      event.recorded_at AS current_recorded_at
               FROM care_plan_commitment_task_links link
               JOIN care_plan_commitments commitment
                 ON commitment.commitment_id=link.commitment_id
               JOIN care_plan_commitment_events event
                 ON event.commitment_id=commitment.commitment_id
                AND event.id=(
                    SELECT head.id FROM care_plan_commitment_events head
                    WHERE head.commitment_id=commitment.commitment_id
                    ORDER BY head.recorded_at DESC,head.id DESC LIMIT 1
                )
               WHERE link.task_id=?""",
            (int(task_id),),
        ).fetchone()
        return self._row(row)

    def history(self, commitment_id: str) -> list[dict]:
        return [
            dict(row)
            for row in self._db().execute(
                """SELECT * FROM care_plan_commitment_events
                   WHERE commitment_id=? ORDER BY recorded_at,id""",
                (str(commitment_id),),
            ).fetchall()
        ]

    @staticmethod
    def _validate_definition(item: dict) -> dict:
        client_key = str(item.get("client_key") or "").strip()
        commitment_type = str(item.get("commitment_type") or "").strip().upper()
        instruction = str(item.get("instruction") or "").strip()
        fulfillment = str(item.get("fulfillment") or "").strip().lower()
        due_at = _time(item.get("due_at"))
        assigned_to = str(item.get("assigned_to") or "").strip() or None
        if len(client_key) < 12:
            raise EncounterPlanCommitmentValidationError(
                "commitment client key is required"
            )
        if commitment_type not in COMMITMENT_TYPES:
            raise EncounterPlanCommitmentValidationError(
                "invalid commitment type"
            )
        if not instruction:
            raise EncounterPlanCommitmentValidationError(
                "commitment instruction is required"
            )
        if fulfillment not in {"remote", "in_person", "hybrid"}:
            raise EncounterPlanCommitmentValidationError(
                "invalid commitment fulfillment"
            )
        return {
            "client_key": client_key,
            "commitment_type": commitment_type,
            "instruction": instruction,
            "fulfillment": fulfillment,
            "due_at": due_at,
            "assigned_to": assigned_to,
        }

    def materialize_signed_document(
        self,
        *,
        document_event: dict,
        commitments: list[dict],
        actor_username: str,
        actor_user_id: int | None,
        commit: bool = True,
    ) -> list[dict]:
        if document_event.get("document_status") != "SIGNED":
            raise EncounterPlanCommitmentValidationError(
                "plan commitments require signed document"
            )
        db = self._db()
        normalized = [self._validate_definition(item) for item in commitments]
        if len({item["client_key"] for item in normalized}) != len(normalized):
            raise EncounterPlanCommitmentValidationError(
                "duplicate commitment client key"
            )
        if commit:
            db.execute("BEGIN IMMEDIATE")
        try:
            output: list[dict] = []
            for item in normalized:
                commitment_id = _commitment_id(
                    int(document_event["id"]), item["client_key"]
                )
                existing = self.commitment(commitment_id)
                if existing:
                    output.append(self.current_for_task(
                        int(db.execute(
                            """SELECT task_id FROM care_plan_commitment_task_links
                               WHERE commitment_id=?""",
                            (commitment_id,),
                        ).fetchone()["task_id"])
                    ))
                    continue
                created_at = _time()
                root = {
                    "commitment_id": commitment_id,
                    "document_event_id": int(document_event["id"]),
                    "encounter_id": str(document_event["encounter_id"]),
                    "journey_id": str(document_event["journey_id"]),
                    "patient_link_id": int(document_event["patient_link_id"]),
                    "client_key": item["client_key"],
                    "commitment_type": item["commitment_type"],
                    "instruction": item["instruction"],
                    "fulfillment": item["fulfillment"],
                    "original_due_at": item["due_at"],
                    "original_assigned_to": item["assigned_to"],
                    "created_at": created_at,
                    "created_by": str(actor_username),
                }
                db.execute(
                    """INSERT INTO care_plan_commitments
                       (commitment_id,document_event_id,encounter_id,journey_id,
                        patient_link_id,client_key,commitment_type,instruction,
                        fulfillment,original_due_at,original_assigned_to,
                        created_at,created_by,content_hash)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (*root.values(), _hash(root)),
                )
                task_cursor = db.execute(
                    """INSERT INTO followup_tasks
                       (patient_link_id,due_date,reason,detail,status,assigned_to,
                        source_rule,source_event,fulfillment,source_engine,created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        root["patient_link_id"],
                        item["due_at"][:10],
                        "encounter_plan",
                        item["instruction"],
                        "open",
                        item["assigned_to"],
                        commitment_id,
                        "encounter_plan_commitment",
                        item["fulfillment"],
                        "encounter_plan",
                        created_at,
                    ),
                )
                task_id = int(task_cursor.lastrowid)
                link = {
                    "commitment_id": commitment_id,
                    "task_id": task_id,
                    "linked_at": created_at,
                    "linked_by": str(actor_username),
                }
                db.execute(
                    """INSERT INTO care_plan_commitment_task_links
                       (commitment_id,task_id,linked_at,linked_by,content_hash)
                       VALUES (?,?,?,?,?)""",
                    (*link.values(), _hash(link)),
                )
                event = {
                    "commitment_id": commitment_id,
                    "event_type": "CREATED",
                    "status": "OPEN",
                    "due_at": item["due_at"],
                    "assigned_to": item["assigned_to"],
                    "appointment_id": None,
                    "evidence_type": None,
                    "evidence_ref": None,
                    "outcome_code": None,
                    "note": "تعهد صریح از سند امضاشده Encounter",
                    "recorded_at": created_at,
                    "actor_user_id": int(actor_user_id) if actor_user_id else None,
                    "actor_username": str(actor_username),
                    "idempotency_key": f"plan-commitment:create:{commitment_id}",
                    "supersedes_event_id": None,
                }
                db.execute(
                    """INSERT INTO care_plan_commitment_events
                       (commitment_id,event_type,status,due_at,assigned_to,
                        appointment_id,evidence_type,evidence_ref,outcome_code,
                        note,recorded_at,actor_user_id,actor_username,
                        idempotency_key,supersedes_event_id,content_hash)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (*event.values(), _hash(event)),
                )
                output.append(self.current_for_task(task_id))
            if commit:
                db.commit()
            return output
        except Exception:
            if commit:
                db.rollback()
            raise

    def append_event(
        self,
        *,
        task_id: int,
        event_type: str,
        actor_username: str,
        actor_user_id: int | None,
        idempotency_key: str,
        expected_current_event_id: int,
        due_at: datetime | str | None = None,
        assigned_to: str | None = None,
        appointment_id: int | None = None,
        evidence_type: str | None = None,
        evidence_ref: str | None = None,
        outcome_code: str | None = None,
        note: str | None = None,
        commit: bool = True,
    ) -> dict:
        db = self._db()
        current = self.current_for_task(task_id)
        if not current:
            raise LookupError("plan commitment task not found")
        if int(current["current_event_id"]) != int(expected_current_event_id):
            raise EncounterPlanCommitmentConflict("STALE_PLAN_COMMITMENT")
        event = str(event_type or "").strip().upper()
        if event not in {
            "STARTED", "ASSIGNED", "RESCHEDULED", "SCHEDULED",
            "COMPLETED", "CANCELLED", "ENTERED_IN_ERROR",
        }:
            raise EncounterPlanCommitmentValidationError(
                "invalid plan commitment event"
            )
        status_by_event = {
            "STARTED": "IN_PROGRESS",
            "ASSIGNED": str(current["current_status"]),
            "RESCHEDULED": str(current["current_status"]),
            "SCHEDULED": "SCHEDULED",
            "COMPLETED": "COMPLETED",
            "CANCELLED": "CANCELLED",
            "ENTERED_IN_ERROR": "ENTERED_IN_ERROR",
        }
        current_status = str(current["current_status"])
        if current_status in _TERMINAL_STATUSES:
            raise EncounterPlanCommitmentConflict(
                "plan commitment is terminal"
            )
        next_due = _time(due_at or current["current_due_at"])
        next_assigned = (
            str(assigned_to).strip()
            if assigned_to is not None and str(assigned_to).strip()
            else current.get("current_assigned_to")
        )
        next_appointment = (
            int(appointment_id)
            if appointment_id is not None
            else current.get("current_appointment_id")
        )
        payload = {
            "commitment_id": str(current["commitment_id"]),
            "event_type": event,
            "status": status_by_event[event],
            "due_at": next_due,
            "assigned_to": next_assigned,
            "appointment_id": next_appointment,
            "evidence_type": (
                str(evidence_type).strip().upper() if evidence_type else None
            ),
            "evidence_ref": str(evidence_ref).strip() if evidence_ref else None,
            "outcome_code": (
                str(outcome_code).strip().upper() if outcome_code else None
            ),
            "note": str(note).strip() if note else None,
            "recorded_at": _time(),
            "actor_user_id": int(actor_user_id) if actor_user_id else None,
            "actor_username": str(actor_username),
            "idempotency_key": str(idempotency_key),
            "supersedes_event_id": int(current["current_event_id"]),
        }
        prior = db.execute(
            "SELECT * FROM care_plan_commitment_events WHERE idempotency_key=?",
            (payload["idempotency_key"],),
        ).fetchone()
        if prior:
            if prior["commitment_id"] != payload["commitment_id"]:
                raise EncounterPlanCommitmentConflict(
                    "commitment idempotency scope mismatch"
                )
            return dict(prior)
        if commit:
            db.execute("BEGIN IMMEDIATE")
        try:
            cursor = db.execute(
                """INSERT INTO care_plan_commitment_events
                   (commitment_id,event_type,status,due_at,assigned_to,
                    appointment_id,evidence_type,evidence_ref,outcome_code,
                    note,recorded_at,actor_user_id,actor_username,
                    idempotency_key,supersedes_event_id,content_hash)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (*payload.values(), _hash(payload)),
            )
            if event == "ASSIGNED":
                db.execute(
                    "UPDATE followup_tasks SET assigned_to=? WHERE id=?",
                    (next_assigned, int(task_id)),
                )
            elif event == "RESCHEDULED":
                db.execute(
                    "UPDATE followup_tasks SET due_date=? WHERE id=?",
                    (next_due[:10], int(task_id)),
                )
            elif event == "SCHEDULED":
                db.execute(
                    """UPDATE followup_tasks
                       SET appointment_id=?,due_date=? WHERE id=?""",
                    (next_appointment, next_due[:10], int(task_id)),
                )
            elif event == "COMPLETED":
                db.execute(
                    """UPDATE followup_tasks SET status='done',resolved_at=?
                       WHERE id=?""",
                    (payload["recorded_at"], int(task_id)),
                )
            elif event in {"CANCELLED", "ENTERED_IN_ERROR"}:
                db.execute(
                    """UPDATE followup_tasks SET status='dismissed',resolved_at=?
                       WHERE id=?""",
                    (payload["recorded_at"], int(task_id)),
                )
            if commit:
                db.commit()
            row = db.execute(
                "SELECT * FROM care_plan_commitment_events WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
            return dict(row)
        except Exception:
            if commit:
                db.rollback()
            raise

    def list_current(
        self,
        *,
        patient_link_id: int | None = None,
        reason: str | None = None,
        query: str | None = None,
        include_terminal: bool = False,
    ) -> list[dict]:
        clauses = []
        params: list[Any] = []
        if patient_link_id is not None:
            clauses.append("commitment.patient_link_id=?")
            params.append(int(patient_link_id))
        if reason and reason != "encounter_plan":
            return []
        if query:
            like = f"%{str(query).strip()}%"
            clauses.append(
                "(patient.national_id LIKE ? OR patient.full_name LIKE ? "
                "OR patient.phone_number LIKE ?)"
            )
            params.extend((like, like, like))
        if not include_terminal:
            clauses.append("event.status IN ('OPEN','IN_PROGRESS','SCHEDULED')")
        where = " AND ".join(clauses) or "1=1"
        rows = self._db().execute(
            f"""SELECT link.task_id AS id,commitment.patient_link_id,
                       'encounter_plan' AS reason,commitment.instruction AS detail,
                       task.status,task.assigned_to,task.appointment_id,
                       task.fulfillment,task.source_engine,task.source_event,
                       task.source_rule,task.created_at,task.resolved_at,
                       patient.full_name AS patient_name,patient.phone_number,
                       patient.national_id,
                       commitment.commitment_id,commitment.document_event_id,
                       commitment.encounter_id,commitment.journey_id,
                       commitment.commitment_type,
                       event.id AS current_event_id,
                       event.event_type AS current_event_type,
                       event.status AS current_status,
                       event.due_at AS current_due_at,
                       event.assigned_to AS current_assigned_to,
                       event.appointment_id AS current_appointment_id,
                       event.evidence_type AS current_evidence_type,
                       event.evidence_ref AS current_evidence_ref,
                       event.outcome_code AS current_outcome_code,
                       event.note AS current_note,
                       event.recorded_at AS current_recorded_at,
                       event.id AS latest_outcome_event_id
                FROM care_plan_commitments commitment
                JOIN care_plan_commitment_task_links link
                  ON link.commitment_id=commitment.commitment_id
                JOIN followup_tasks task ON task.id=link.task_id
                JOIN patient_links patient ON patient.id=commitment.patient_link_id
                JOIN care_plan_commitment_events event
                  ON event.commitment_id=commitment.commitment_id
                 AND event.id=(
                    SELECT head.id FROM care_plan_commitment_events head
                    WHERE head.commitment_id=commitment.commitment_id
                    ORDER BY head.recorded_at DESC,head.id DESC LIMIT 1
                 )
                WHERE {where}
                ORDER BY event.due_at,link.task_id""",
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def counts_by_type(self, *, include_terminal: bool = False) -> dict[str, int]:
        result: dict[str, int] = {}
        for row in self.list_current(include_terminal=include_terminal):
            key = str(row["commitment_type"])
            result[key] = result.get(key, 0) + 1
        return result


__all__ = [
    "EncounterPlanCommitmentConflict",
    "EncounterPlanCommitmentRepository",
    "EncounterPlanCommitmentValidationError",
]
