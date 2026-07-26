"""Append-only specialist appointment linkage and financial read projections."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import sqlite3
import uuid
from typing import Any

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.specialist_financial_funnel_schema import (
    ensure_specialist_financial_funnel_storage,
)
from src.common.utils import iran_now


class SpecialistFinancialFunnelConflict(RuntimeError):
    pass


def _text_time(value: datetime | str | None = None) -> str:
    current = value or iran_now()
    if isinstance(current, str):
        parsed = datetime.fromisoformat(current.replace("Z", "+00:00"))
    else:
        parsed = current
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    return parsed.isoformat(sep=" ", timespec="seconds")


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


class SpecialistFinancialFunnelRepository:
    def __init__(self, db: sqlite3.Connection | None = None):
        self._connection = db

    def _db(self) -> sqlite3.Connection:
        if self._connection is not None:
            return self._connection
        db = get_db()
        ensure_specialist_financial_funnel_storage(db)
        return db

    @staticmethod
    def _row(row) -> dict | None:
        return dict(row) if row else None

    def appointment_link_for_encounter(self, encounter_id: str) -> dict | None:
        row = self._db().execute(
            """SELECT link.*, event.id AS current_event_id,
                      event.status AS current_status,
                      event.recorded_at AS current_recorded_at
               FROM encounter_appointment_links link
               JOIN encounter_appointment_link_events event
                 ON event.link_id=link.link_id
               WHERE link.encounter_id=?
                 AND event.id=(
                     SELECT head.id FROM encounter_appointment_link_events head
                     WHERE head.link_id=link.link_id
                     ORDER BY head.recorded_at DESC, head.id DESC LIMIT 1
                 )""",
            (str(encounter_id),),
        ).fetchone()
        return self._row(row)

    def link_appointment_once(
        self,
        *,
        appointment_id: int,
        encounter_id: str,
        patient_link_id: int,
        journey_id: str,
        actor_username: str,
        effective_at: datetime | str | None = None,
        reason_code: str = "DOCTOR_QUEUE_EXPLICIT_SELECTION",
        commit: bool = True,
    ) -> dict:
        db = self._db()
        existing = self.appointment_link_for_encounter(encounter_id)
        if existing:
            if int(existing["appointment_id"]) == int(appointment_id):
                return existing
            raise SpecialistFinancialFunnelConflict(
                "ENCOUNTER_ALREADY_LINKED_TO_ANOTHER_APPOINTMENT"
            )
        appointment_existing = db.execute(
            "SELECT encounter_id FROM encounter_appointment_links WHERE appointment_id=?",
            (int(appointment_id),),
        ).fetchone()
        if appointment_existing:
            raise SpecialistFinancialFunnelConflict(
                "APPOINTMENT_ALREADY_LINKED_TO_ANOTHER_ENCOUNTER"
            )
        when = _text_time(effective_at)
        link_id = "apptlink_" + uuid.uuid4().hex
        root = {
            "link_id": link_id,
            "appointment_id": int(appointment_id),
            "encounter_id": str(encounter_id),
            "journey_id": str(journey_id),
            "patient_link_id": int(patient_link_id),
            "created_at": when,
            "created_by": str(actor_username),
        }
        db.execute(
            """INSERT INTO encounter_appointment_links
               (link_id, appointment_id, encounter_id, journey_id,
                patient_link_id, created_at, created_by, content_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                root["link_id"], root["appointment_id"], root["encounter_id"],
                root["journey_id"], root["patient_link_id"], root["created_at"],
                root["created_by"], _hash(root),
            ),
        )
        event = {
            "link_id": link_id,
            "event_type": "LINKED",
            "status": "LINKED",
            "reason_code": str(reason_code),
            "effective_at": when,
            "recorded_at": when,
            "actor_username": str(actor_username),
            "note": None,
            "supersedes_event_id": None,
        }
        db.execute(
            """INSERT INTO encounter_appointment_link_events
               (link_id, event_type, status, reason_code, effective_at,
                recorded_at, actor_username, note, supersedes_event_id,
                content_hash)
               VALUES (?, 'LINKED', 'LINKED', ?, ?, ?, ?, ?, ?, ?)""",
            (
                link_id, event["reason_code"], when, when,
                event["actor_username"], None, None, _hash(event),
            ),
        )
        if commit:
            db.commit()
        return self.appointment_link_for_encounter(encounter_id)

    def eligible_invoice_contexts(self) -> list[dict]:
        rows = self._db().execute(
            """SELECT attribution.accounting_invoice_id,
                      attribution.accounting_patient_id,
                      attribution.patient_link_id,
                      attribution.journey_id,
                      attribution.encounter_id,
                      completion.id AS encounter_completion_event_id,
                      link.appointment_id
               FROM accounting_invoice_attribution_events attribution
               JOIN care_encounters encounter
                 ON encounter.encounter_id=attribution.encounter_id
               JOIN care_encounter_events completion
                 ON completion.encounter_id=encounter.encounter_id
               LEFT JOIN encounter_appointment_links link
                 ON link.encounter_id=encounter.encounter_id
               LEFT JOIN encounter_appointment_link_events link_event
                 ON link_event.link_id=link.link_id
                AND link_event.id=(
                    SELECT link_head.id
                    FROM encounter_appointment_link_events link_head
                    WHERE link_head.link_id=link.link_id
                    ORDER BY link_head.recorded_at DESC, link_head.id DESC LIMIT 1
                )
               WHERE attribution.id=(
                   SELECT head.id FROM accounting_invoice_attribution_events head
                   WHERE head.accounting_invoice_id=attribution.accounting_invoice_id
                   ORDER BY head.recorded_at DESC, head.id DESC LIMIT 1
               )
                 AND attribution.event_type='ATTRIBUTED'
                 AND completion.id=(
                     SELECT current.id FROM care_encounter_events current
                     WHERE current.encounter_id=encounter.encounter_id
                     ORDER BY current.recorded_at DESC, current.id DESC LIMIT 1
                 )
                 AND completion.event_type='COMPLETED'
                 AND (link.link_id IS NULL OR link_event.status='LINKED')
               ORDER BY attribution.accounting_invoice_id"""
        ).fetchall()
        return [dict(row) for row in rows]

    def record_observation_once(
        self,
        *,
        context: dict,
        snapshot: dict,
        observed_at: datetime | str | None = None,
        created_by: str = "system:specialist-finance-reconciliation",
        commit: bool = True,
    ) -> tuple[dict, bool]:
        db = self._db()
        if int(snapshot["accounting_invoice_id"]) != int(
            context["accounting_invoice_id"]
        ):
            raise SpecialistFinancialFunnelConflict("FINANCIAL_INVOICE_SCOPE_MISMATCH")
        if int(snapshot["accounting_patient_id"]) != int(
            context["accounting_patient_id"]
        ):
            raise SpecialistFinancialFunnelConflict("FINANCIAL_PATIENT_SCOPE_MISMATCH")
        existing = db.execute(
            """SELECT * FROM specialist_financial_observations
               WHERE accounting_invoice_id=? AND source_fingerprint=?""",
            (
                int(context["accounting_invoice_id"]),
                str(snapshot["source_fingerprint"]),
            ),
        ).fetchone()
        if existing:
            return dict(existing), False
        when = _text_time(observed_at)
        payload = {
            "accounting_invoice_id": int(context["accounting_invoice_id"]),
            "accounting_patient_id": int(context["accounting_patient_id"]),
            "patient_link_id": int(context["patient_link_id"]),
            "journey_id": str(context["journey_id"]),
            "encounter_id": str(context["encounter_id"]),
            "encounter_completion_event_id": int(
                context["encounter_completion_event_id"]
            ),
            "appointment_id": (
                int(context["appointment_id"])
                if context.get("appointment_id") is not None
                else None
            ),
            "invoice_status": str(snapshot["invoice_status"]),
            "work_date": snapshot.get("work_date"),
            "closed_at": snapshot.get("closed_at"),
            "source_total_amount": snapshot.get("source_total_amount"),
            "visits_billed": int(snapshot["visits_billed"]),
            "injections_billed": int(snapshot["injections_billed"]),
            "procedures_billed": int(snapshot["procedures_billed"]),
            "billed_amount": int(snapshot["billed_amount"]),
            "visits_collected": int(snapshot["visits_collected"]),
            "injections_collected": int(snapshot["injections_collected"]),
            "procedures_collected": int(snapshot["procedures_collected"]),
            "collected_amount": int(snapshot["collected_amount"]),
            "billable_item_count": int(snapshot["billable_item_count"]),
            "paid_item_count": int(snapshot["paid_item_count"]),
            "collection_state": str(snapshot["collection_state"]),
            "payment_evidence": "ITEM_PAID_FLAGS",
            "source_fingerprint": str(snapshot["source_fingerprint"]),
            "observed_at": when,
            "created_by": str(created_by),
        }
        columns = ", ".join(payload.keys()) + ", content_hash"
        marks = ", ".join("?" for _ in payload) + ", ?"
        cursor = db.execute(
            f"INSERT INTO specialist_financial_observations ({columns}) VALUES ({marks})",
            (*payload.values(), _hash(payload)),
        )
        if commit:
            db.commit()
        row = db.execute(
            "SELECT * FROM specialist_financial_observations WHERE id=?",
            (cursor.lastrowid,),
        ).fetchone()
        return dict(row), True

    def latest_observations(self) -> list[dict]:
        rows = self._db().execute(
            """SELECT observation.*
               FROM specialist_financial_observations observation
               WHERE observation.id=(
                   SELECT latest.id FROM specialist_financial_observations latest
                   WHERE latest.accounting_invoice_id=observation.accounting_invoice_id
                   ORDER BY latest.observed_at DESC, latest.id DESC LIMIT 1
               )
               ORDER BY observation.accounting_invoice_id"""
        ).fetchall()
        return [dict(row) for row in rows]

    def reconciliation_scope(self) -> dict:
        eligible = self.eligible_invoice_contexts()
        observations = self.latest_observations()
        observed_ids = {int(row["accounting_invoice_id"]) for row in observations}
        eligible_ids = {int(row["accounting_invoice_id"]) for row in eligible}
        latest_at = max(
            (str(row["observed_at"]) for row in observations),
            default=None,
        )
        return {
            "eligible_invoices": len(eligible_ids),
            "observed_invoices": len(observed_ids & eligible_ids),
            "missing_observations": len(eligible_ids - observed_ids),
            "latest_observed_at": latest_at,
        }

    def finance_totals(
        self, *, floor: str | None = None, until: str | None = None
    ) -> dict:
        clauses = ["observation.invoice_status='closed'"]
        params: list[Any] = []
        if floor:
            clauses.append("observation.work_date>=?")
            params.append(str(floor))
        if until:
            clauses.append("observation.work_date<=?")
            params.append(str(until))
        where = " AND ".join(clauses)
        row = self._db().execute(
            f"""SELECT COALESCE(SUM(observation.visits_billed),0) AS visits,
                       COALESCE(SUM(observation.injections_billed),0) AS injections,
                       COALESCE(SUM(observation.procedures_billed),0) AS procedures,
                       COALESCE(SUM(observation.billed_amount),0) AS total,
                       COALESCE(SUM(observation.collected_amount),0) AS collected,
                       COUNT(*) AS invoices
                FROM specialist_financial_observations observation
                WHERE observation.id=(
                    SELECT latest.id FROM specialist_financial_observations latest
                    WHERE latest.accounting_invoice_id=observation.accounting_invoice_id
                    ORDER BY latest.observed_at DESC, latest.id DESC LIMIT 1
                ) AND {where}""",
            params,
        ).fetchone()
        return {key: int(row[key] or 0) for key in row.keys()}

    def daily_totals(self, date_from: str, date_to: str) -> dict[str, dict[str, int]]:
        rows = self._db().execute(
            """SELECT observation.work_date AS day,
                      COALESCE(SUM(observation.billed_amount),0) AS billed,
                      COALESCE(SUM(observation.collected_amount),0) AS collected
               FROM specialist_financial_observations observation
               WHERE observation.id=(
                   SELECT latest.id FROM specialist_financial_observations latest
                   WHERE latest.accounting_invoice_id=observation.accounting_invoice_id
                   ORDER BY latest.observed_at DESC, latest.id DESC LIMIT 1
               )
                 AND observation.invoice_status='closed'
                 AND observation.work_date BETWEEN ? AND ?
               GROUP BY observation.work_date""",
            (str(date_from), str(date_to)),
        ).fetchall()
        return {
            str(row["day"]): {
                "billed": int(row["billed"] or 0),
                "collected": int(row["collected"] or 0),
            }
            for row in rows
            if row["day"]
        }

    def funnel_summary(self) -> dict:
        db = self._db()
        booked = db.execute(
            """SELECT COUNT(*) AS count
               FROM encounter_appointment_links link
               JOIN encounter_appointment_link_events event
                 ON event.link_id=link.link_id
               WHERE event.id=(
                   SELECT head.id FROM encounter_appointment_link_events head
                   WHERE head.link_id=link.link_id
                   ORDER BY head.recorded_at DESC, head.id DESC LIMIT 1
               ) AND event.status='LINKED'"""
        ).fetchone()["count"]
        attended = db.execute(
            """SELECT COUNT(DISTINCT encounter.encounter_id) AS count
               FROM care_encounters encounter
               WHERE EXISTS (
                   SELECT 1 FROM care_encounter_events event
                   WHERE event.encounter_id=encounter.encounter_id
                     AND event.event_type='STARTED'
               )"""
        ).fetchone()["count"]
        completed = db.execute(
            """SELECT COUNT(*) AS count
               FROM care_encounters encounter
               JOIN care_encounter_events event
                 ON event.encounter_id=encounter.encounter_id
               WHERE event.id=(
                   SELECT head.id FROM care_encounter_events head
                   WHERE head.encounter_id=encounter.encounter_id
                   ORDER BY head.recorded_at DESC, head.id DESC LIMIT 1
               ) AND event.event_type='COMPLETED'"""
        ).fetchone()["count"]
        states = {
            row["collection_state"]: int(row["count"])
            for row in db.execute(
                """SELECT observation.collection_state, COUNT(*) AS count
                   FROM specialist_financial_observations observation
                   WHERE observation.id=(
                       SELECT latest.id FROM specialist_financial_observations latest
                       WHERE latest.accounting_invoice_id=observation.accounting_invoice_id
                       ORDER BY latest.observed_at DESC, latest.id DESC LIMIT 1
                   ) GROUP BY observation.collection_state"""
            ).fetchall()
        }
        invoiced = sum(
            value
            for key, value in states.items()
            if key != "WAITING_FOR_INVOICE_CLOSURE"
        )
        return {
            "booked": int(booked or 0),
            "attended": int(attended or 0),
            "service_completed": int(completed or 0),
            "invoice_closed": int(invoiced),
            "unpaid": states.get("UNPAID", 0),
            "partially_collected": states.get("PARTIALLY_COLLECTED", 0),
            "collected": states.get("COLLECTED", 0),
            "closed_no_billable_items": states.get(
                "CLOSED_NO_BILLABLE_ITEMS", 0
            ),
            "waiting_for_invoice_closure": states.get(
                "WAITING_FOR_INVOICE_CLOSURE", 0
            ),
        }
