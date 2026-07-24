"""Append-only persistence and optimistic resolution of clinical source conflicts."""
from __future__ import annotations

from datetime import datetime
import json
import sqlite3
from typing import Any

from src.adapters.sqlite.clinical_data_conflict_schema import (
    ensure_clinical_data_conflict_storage,
)
from src.adapters.sqlite.core import get_db
from src.common.utils import iran_now, parse_datetime
from src.domain.clinical_engine.data_conflicts import (
    ClinicalDataConflictError,
    ConflictEventStatus,
    ConflictEventType,
    ConflictResolutionMethod,
    detect_conflict_groups,
    digest,
    merge_candidate_items,
    project_conflict_overlay,
)


class ClinicalDataConflictStale(RuntimeError):
    """Candidate sources or the conflict head changed after the UI was loaded."""


_SOURCE_SQL = {
    "conditions": """SELECT pc.*, c.code AS condition_code,
                                c.name AS condition_name
                       FROM patient_conditions pc
                       JOIN conditions c ON c.id=pc.condition_id
                       WHERE pc.patient_link_id=? ORDER BY pc.id""",
    "medications": """SELECT * FROM patient_medications
                       WHERE patient_link_id=? ORDER BY id""",
    "allergies": """SELECT allergy.*, catalog.concept_key AS allergy_concept_key,
                             catalog.display_name AS allergy_concept_name
                      FROM allergies allergy
                      LEFT JOIN allergy_catalog catalog
                        ON catalog.id=allergy.allergy_concept_id
                      WHERE allergy.patient_link_id=? ORDER BY allergy.id""",
}


def _local_naive(value: datetime | str | None) -> datetime:
    parsed = parse_datetime(value) if value is not None else None
    if parsed is None:
        parsed = iran_now()
    return parsed.replace(tzinfo=None) if parsed.tzinfo is not None else parsed


def _text_time(value: datetime) -> str:
    return value.isoformat(sep=" ", timespec="seconds")


class ClinicalDataConflictRepository:
    def __init__(self, db: sqlite3.Connection | None = None, *, clock=None):
        self._connection = db
        self.clock = clock or iran_now

    def _db(self) -> sqlite3.Connection:
        db = self._connection or get_db()
        ensure_clinical_data_conflict_storage(db)
        return db

    @staticmethod
    def _rows(
        db: sqlite3.Connection,
        patient_link_id: int,
        collection_key: str,
    ) -> list[dict[str, Any]]:
        try:
            sql = _SOURCE_SQL[collection_key]
        except KeyError as exc:
            raise ClinicalDataConflictError("unsupported conflict collection") from exc
        return [
            dict(row)
            for row in db.execute(sql, (patient_link_id,)).fetchall()
        ]

    @staticmethod
    def _medication_events(
        db: sqlite3.Connection,
        patient_link_id: int,
    ) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in db.execute(
                """SELECT * FROM medication_events
                   WHERE patient_link_id=? ORDER BY event_date, created_at, id""",
                (patient_link_id,),
            ).fetchall()
        ]

    @staticmethod
    def _events(
        db: sqlite3.Connection,
        patient_link_id: int,
        collection_key: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM clinical_data_conflict_events WHERE patient_link_id=?"
        params: list[Any] = [patient_link_id]
        if collection_key is not None:
            sql += " AND collection_key=?"
            params.append(collection_key)
        sql += " ORDER BY recorded_at, id"
        return [dict(row) for row in db.execute(sql, params).fetchall()]

    @staticmethod
    def _groups_db(
        db: sqlite3.Connection,
        patient_link_id: int,
        collection_key: str,
        *,
        as_of_at: datetime,
    ):
        rows = ClinicalDataConflictRepository._rows(
            db, patient_link_id, collection_key
        )
        medication_events = (
            ClinicalDataConflictRepository._medication_events(db, patient_link_id)
            if collection_key == "medications"
            else ()
        )
        return detect_conflict_groups(
            collection_key,
            rows,
            as_of_at=as_of_at,
            medication_events=medication_events,
        )

    def projection(
        self,
        patient_link_id: int,
        collection_key: str,
        *,
        as_of_at: datetime | str | None = None,
    ):
        db = self._db()
        as_of = _local_naive(as_of_at)
        groups = self._groups_db(
            db, patient_link_id, collection_key, as_of_at=as_of
        )
        return project_conflict_overlay(
            collection_key,
            groups,
            self._events(db, patient_link_id, collection_key),
            as_of_at=as_of,
        )

    def patient_events(self, patient_link_id: int) -> list[dict[str, Any]]:
        return self._events(self._db(), patient_link_id)

    @staticmethod
    def _head(
        db: sqlite3.Connection,
        patient_link_id: int,
        collection_key: str,
        group_key: str,
    ) -> dict[str, Any] | None:
        row = db.execute(
            """SELECT event.* FROM clinical_data_conflict_events event
               WHERE event.patient_link_id=? AND event.collection_key=?
                 AND event.conflict_group_key=?
                 AND NOT EXISTS (
                     SELECT 1 FROM clinical_data_conflict_events child
                     WHERE child.supersedes_event_id=event.id
                 )
               ORDER BY event.recorded_at DESC, event.id DESC LIMIT 1""",
            (patient_link_id, collection_key, group_key),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _event_hash(payload: dict[str, Any]) -> str:
        return digest(payload)

    @classmethod
    def _append_event(
        cls,
        db: sqlite3.Connection,
        *,
        patient_link_id: int,
        collection_key: str,
        group,
        event_type: ConflictEventType,
        status: ConflictEventStatus,
        actor_username: str,
        actor_user_id: int | None,
        source: str,
        effective_at: datetime,
        recorded_at: datetime,
        supersedes_event_id: int | None,
        resolution_method: ConflictResolutionMethod | None = None,
        selected_candidate_keys: tuple[str, ...] = (),
        resolved_value: dict[str, Any] | None = None,
        note: str | None = None,
    ) -> int:
        candidates = [candidate.payload() for candidate in group.candidates]
        payload = {
            "schema_version": "1.0",
            "patient_link_id": int(patient_link_id),
            "collection_key": collection_key,
            "conflict_group_key": group.group_key,
            "concept_key": group.concept_key,
            "event_type": event_type.value,
            "status": status.value,
            "candidate_set_hash": group.candidate_set_hash,
            "candidates": candidates,
            "resolution_method": resolution_method.value if resolution_method else None,
            "selected_candidate_keys": list(selected_candidate_keys),
            "resolved_value": resolved_value,
            "verification": "CONFIRMED",
            "effective_at": _text_time(effective_at),
            "recorded_at": _text_time(recorded_at),
            "source": source,
            "actor_username": actor_username,
            "supersedes_event_id": supersedes_event_id,
            "note": note,
        }
        cursor = db.execute(
            """INSERT INTO clinical_data_conflict_events
               (patient_link_id, collection_key, conflict_group_key, concept_key,
                event_type, status, candidate_set_hash, candidates_json,
                resolution_method, selected_candidate_keys_json,
                resolved_value_json, verification, effective_at, recorded_at,
                source, actor_user_id, actor_username, supersedes_event_id,
                note, content_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CONFIRMED', ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                patient_link_id,
                collection_key,
                group.group_key,
                group.concept_key,
                event_type.value,
                status.value,
                group.candidate_set_hash,
                json.dumps(candidates, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                resolution_method.value if resolution_method else None,
                json.dumps(list(selected_candidate_keys), ensure_ascii=False, separators=(",", ":")),
                (
                    json.dumps(resolved_value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    if resolved_value is not None
                    else None
                ),
                _text_time(effective_at),
                _text_time(recorded_at),
                source,
                actor_user_id,
                actor_username,
                supersedes_event_id,
                note,
                cls._event_hash(payload),
            ),
        )
        return int(cursor.lastrowid)

    def resolve(
        self,
        *,
        patient_link_id: int,
        collection_key: str,
        conflict_group_key: str,
        method: str | ConflictResolutionMethod,
        actor_username: str,
        actor_user_id: int | None,
        expected_candidate_set_hash: str,
        expected_current_event_id: int | None,
        selected_candidate_keys=(),
        source: str = "clinician",
        note: str | None = None,
        effective_at: datetime | str | None = None,
    ) -> dict[str, Any]:
        actor = " ".join(str(actor_username or "").strip().split())
        if not actor:
            raise ClinicalDataConflictError("actor_username is required")
        if source not in {"clinician", "patient", "caregiver", "imported", "system"}:
            raise ClinicalDataConflictError("invalid resolution source")
        resolution = ConflictResolutionMethod(method)
        selected = tuple(sorted({str(value) for value in selected_candidate_keys if str(value).strip()}))
        recorded = _local_naive(self.clock())
        effective = _local_naive(effective_at or recorded)
        clean_note = " ".join(str(note or "").strip().split()) or None
        if clean_note and len(clean_note) > 1000:
            raise ClinicalDataConflictError("resolution note is too long")

        db = self._db()
        db.execute("BEGIN IMMEDIATE")
        try:
            patient = db.execute(
                "SELECT id FROM patient_links WHERE id=? AND is_active=1",
                (patient_link_id,),
            ).fetchone()
            if not patient:
                raise LookupError("patient not found or inactive")
            groups = self._groups_db(
                db,
                patient_link_id,
                collection_key,
                as_of_at=recorded,
            )
            group = next(
                (item for item in groups if item.group_key == conflict_group_key),
                None,
            )
            if group is None:
                raise ClinicalDataConflictError("conflict group no longer exists")
            if group.candidate_set_hash != str(expected_candidate_set_hash or ""):
                raise ClinicalDataConflictStale(
                    "candidate sources changed; reload before resolving"
                )
            head = self._head(
                db,
                patient_link_id,
                collection_key,
                conflict_group_key,
            )
            head_id = int(head["id"]) if head else None
            if head_id != expected_current_event_id:
                raise ClinicalDataConflictStale(
                    "conflict resolution changed; reload before recording another resolution"
                )

            by_key = {candidate.candidate_key: candidate for candidate in group.candidates}
            resolved_value = None
            if resolution is ConflictResolutionMethod.SELECT_CANDIDATE:
                if len(selected) != 1 or selected[0] not in by_key:
                    raise ClinicalDataConflictError("select exactly one current candidate")
                chosen = by_key[selected[0]]
                if chosen.assertion.value != "PRESENT":
                    raise ClinicalDataConflictError(
                        "SELECT_CANDIDATE requires a PRESENT candidate; "
                        "use CONFIRMED_ABSENT or MARK_UNKNOWN explicitly"
                    )
                resolved_value = dict(chosen.item)
                effective = chosen.effective_at
            elif resolution is ConflictResolutionMethod.MERGE_CANDIDATES:
                if len(selected) < 2 or any(key not in by_key for key in selected):
                    raise ClinicalDataConflictError("merge requires current candidate keys")
                resolved_value = merge_candidate_items(by_key[key] for key in selected)
                effective = min(by_key[key].effective_at for key in selected)
            elif resolution in {
                ConflictResolutionMethod.CONFIRMED_ABSENT,
                ConflictResolutionMethod.MARK_UNKNOWN,
            }:
                if selected:
                    raise ClinicalDataConflictError("this resolution method does not select candidates")

            open_id: int
            if head and (
                str(head["status"]) == ConflictEventStatus.OPEN.value
                and str(head["candidate_set_hash"]) == group.candidate_set_hash
            ):
                open_id = int(head["id"])
            else:
                event_type = (
                    ConflictEventType.REOPENED if head else ConflictEventType.OPENED
                )
                open_id = self._append_event(
                    db,
                    patient_link_id=patient_link_id,
                    collection_key=collection_key,
                    group=group,
                    event_type=event_type,
                    status=ConflictEventStatus.OPEN,
                    actor_username=actor,
                    actor_user_id=actor_user_id,
                    source=source,
                    effective_at=effective,
                    recorded_at=recorded,
                    supersedes_event_id=head_id,
                    note=clean_note,
                )

            resolution_id = self._append_event(
                db,
                patient_link_id=patient_link_id,
                collection_key=collection_key,
                group=group,
                event_type=ConflictEventType.RESOLVED,
                status=ConflictEventStatus.RESOLVED,
                actor_username=actor,
                actor_user_id=actor_user_id,
                source=source,
                effective_at=effective,
                recorded_at=recorded,
                supersedes_event_id=open_id,
                resolution_method=resolution,
                selected_candidate_keys=selected,
                resolved_value=resolved_value,
                note=clean_note,
            )
            row = db.execute(
                "SELECT * FROM clinical_data_conflict_events WHERE id=?",
                (resolution_id,),
            ).fetchone()
            db.commit()
            return dict(row)
        except Exception:
            db.rollback()
            raise
