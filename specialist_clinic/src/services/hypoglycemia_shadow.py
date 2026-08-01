"""Shadow-only hypoglycemia event and clinician-review vertical slice.

No Clinical Engine rule, medication advice/action, order, referral, patient-facing
message, automatic duplicate merge, route, or UI is created here.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import sqlite3
from typing import Any, Callable
from uuid import uuid4

from src.common.utils import IRAN_TZ


EVENT_LEVELS = {"LEVEL_2", "LEVEL_3", "UNKNOWN"}
TRI_STATES = {"YES", "NO", "UNKNOWN"}
VERIFICATIONS = {"CONFIRMED", "PROVISIONAL", "UNVERIFIED", "CONFLICT"}
REPORTERS = {"PATIENT", "CAREGIVER", "CLINICIAN", "EMS", "DEVICE", "IMPORTED", "SYSTEM"}
DECISIONS = {"CONFIRMED", "CONFLICT", "REJECTED", "ENTERED_IN_ERROR"}
DISPOSITIONS = {
    "NO_CHANGE",
    "MEDICATION_CHANGE_RECORDED",
    "EDUCATION",
    "DEVICE_REVIEW",
    "REFERRAL_RECORDED",
    "FOLLOWUP",
    "OTHER",
}


class HypoglycemiaShadowError(RuntimeError):
    pass


class HypoglycemiaShadowConflict(HypoglycemiaShadowError):
    pass


class HypoglycemiaShadowValidationError(HypoglycemiaShadowError):
    pass


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _required(value: Any, field: str) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text:
        raise HypoglycemiaShadowValidationError(f"{field} is required")
    return text


def _optional(value: Any) -> str | None:
    text = " ".join(str(value or "").strip().split())
    return text or None


def _enum(value: Any, allowed: set[str], field: str) -> str:
    normalized = str(value or "").strip().upper()
    if normalized not in allowed:
        raise HypoglycemiaShadowValidationError(f"invalid {field}: {value!r}")
    return normalized


def _time(value: datetime | str | None, clock: Callable[[], datetime]) -> str:
    if value is None:
        parsed = clock()
    elif isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise HypoglycemiaShadowValidationError("invalid datetime") from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(IRAN_TZ).replace(tzinfo=None)
    return parsed.isoformat(sep=" ", timespec="seconds")


def _glucose_mg_dl(value: Any, unit: Any) -> tuple[float, str, float]:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise HypoglycemiaShadowValidationError("glucose value must be numeric") from exc
    if numeric < 0:
        raise HypoglycemiaShadowValidationError("glucose value cannot be negative")
    normalized = str(unit or "").strip().lower()
    if normalized == "mg/dl":
        return numeric, "mg/dL", numeric
    if normalized == "mmol/l":
        return numeric, "mmol/L", numeric * 18.0
    raise HypoglycemiaShadowValidationError("glucose unit must be mg/dL or mmol/L")


def ensure_hypoglycemia_shadow_storage(db: sqlite3.Connection) -> None:
    """Install two isolated append-only ledgers on first shadow-service use."""
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS hypoglycemia_shadow_event_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL CHECK (length(trim(event_id)) >= 12),
            version_number INTEGER NOT NULL CHECK (version_number > 0),
            patient_link_id INTEGER NOT NULL,
            source_system TEXT NOT NULL CHECK (length(trim(source_system)) > 0),
            source_record_id TEXT NOT NULL CHECK (length(trim(source_record_id)) > 0),
            status TEXT NOT NULL CHECK (status IN (
                'CANDIDATE','CONFIRMED','CONFLICT','REJECTED','ENTERED_IN_ERROR'
            )),
            event_level TEXT NOT NULL CHECK (event_level IN (
                'LEVEL_2','LEVEL_3','UNKNOWN'
            )),
            occurred_at TEXT CHECK (
                occurred_at IS NULL OR datetime(occurred_at) IS NOT NULL
            ),
            recorded_at TEXT NOT NULL CHECK (datetime(recorded_at) IS NOT NULL),
            glucose_value REAL CHECK (glucose_value IS NULL OR glucose_value >= 0),
            glucose_unit TEXT CHECK (
                glucose_unit IS NULL OR glucose_unit IN ('mg/dL','mmol/L')
            ),
            external_assistance TEXT NOT NULL CHECK (
                external_assistance IN ('YES','NO','UNKNOWN')
            ),
            altered_function TEXT NOT NULL CHECK (
                altered_function IN ('YES','NO','UNKNOWN')
            ),
            reporter_type TEXT NOT NULL CHECK (reporter_type IN (
                'PATIENT','CAREGIVER','CLINICIAN','EMS','DEVICE','IMPORTED','SYSTEM'
            )),
            verification TEXT NOT NULL CHECK (verification IN (
                'CONFIRMED','PROVISIONAL','UNVERIFIED','CONFLICT'
            )),
            actor_username TEXT NOT NULL CHECK (length(trim(actor_username)) > 0),
            note TEXT,
            supersedes_version_id INTEGER,
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash) = 64),
            UNIQUE(event_id, version_number),
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id),
            FOREIGN KEY(supersedes_version_id)
                REFERENCES hypoglycemia_shadow_event_versions(id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_hypo_shadow_source_root
        ON hypoglycemia_shadow_event_versions(source_system, source_record_id)
        WHERE version_number = 1;
        CREATE INDEX IF NOT EXISTS idx_hypo_shadow_patient_event
        ON hypoglycemia_shadow_event_versions(
            patient_link_id, event_id, version_number DESC
        );

        CREATE TABLE IF NOT EXISTS hypoglycemia_shadow_review_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            review_id TEXT NOT NULL CHECK (length(trim(review_id)) >= 12),
            sequence_number INTEGER NOT NULL CHECK (sequence_number > 0),
            patient_link_id INTEGER NOT NULL,
            event_version_id INTEGER NOT NULL,
            owner_username TEXT NOT NULL CHECK (length(trim(owner_username)) > 0),
            event_type TEXT NOT NULL CHECK (event_type IN (
                'OPENED','DISPOSITION_RECORDED','ENTERED_IN_ERROR'
            )),
            disposition_type TEXT CHECK (
                disposition_type IS NULL OR disposition_type IN (
                    'NO_CHANGE','MEDICATION_CHANGE_RECORDED','EDUCATION',
                    'DEVICE_REVIEW','REFERRAL_RECORDED','FOLLOWUP','OTHER'
                )
            ),
            rationale TEXT,
            recorded_at TEXT NOT NULL CHECK (datetime(recorded_at) IS NOT NULL),
            actor_username TEXT NOT NULL CHECK (length(trim(actor_username)) > 0),
            supersedes_event_id INTEGER,
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash) = 64),
            UNIQUE(review_id, sequence_number),
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id),
            FOREIGN KEY(event_version_id)
                REFERENCES hypoglycemia_shadow_event_versions(id),
            FOREIGN KEY(supersedes_event_id)
                REFERENCES hypoglycemia_shadow_review_events(id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_hypo_shadow_review_root
        ON hypoglycemia_shadow_review_events(event_version_id)
        WHERE sequence_number = 1;
        CREATE INDEX IF NOT EXISTS idx_hypo_shadow_review_history
        ON hypoglycemia_shadow_review_events(review_id, sequence_number DESC);

        CREATE TRIGGER IF NOT EXISTS trg_hypo_shadow_event_no_update
        BEFORE UPDATE ON hypoglycemia_shadow_event_versions
        BEGIN SELECT RAISE(ABORT, 'hypoglycemia shadow events are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS trg_hypo_shadow_event_no_delete
        BEFORE DELETE ON hypoglycemia_shadow_event_versions
        BEGIN SELECT RAISE(ABORT, 'hypoglycemia shadow events cannot be deleted'); END;

        CREATE TRIGGER IF NOT EXISTS trg_hypo_shadow_event_root
        BEFORE INSERT ON hypoglycemia_shadow_event_versions
        WHEN (
            NEW.version_number = 1 AND NEW.supersedes_version_id IS NOT NULL
        ) OR (
            NEW.version_number > 1 AND NEW.supersedes_version_id IS NULL
        )
        BEGIN SELECT RAISE(ABORT, 'invalid hypoglycemia shadow root'); END;

        CREATE TRIGGER IF NOT EXISTS trg_hypo_shadow_event_linear
        BEFORE INSERT ON hypoglycemia_shadow_event_versions
        WHEN NEW.version_number > 1 AND NOT EXISTS (
            SELECT 1 FROM hypoglycemia_shadow_event_versions prior
            WHERE prior.id = NEW.supersedes_version_id
              AND prior.event_id = NEW.event_id
              AND prior.patient_link_id = NEW.patient_link_id
              AND prior.version_number = NEW.version_number - 1
              AND prior.version_number = (
                  SELECT MAX(head.version_number)
                  FROM hypoglycemia_shadow_event_versions head
                  WHERE head.event_id = NEW.event_id
              )
        )
        BEGIN SELECT RAISE(ABORT, 'hypoglycemia shadow history must be linear'); END;

        CREATE TRIGGER IF NOT EXISTS trg_hypo_shadow_confirmed
        BEFORE INSERT ON hypoglycemia_shadow_event_versions
        WHEN NEW.status = 'CONFIRMED' AND (
            NEW.verification <> 'CONFIRMED'
            OR NEW.occurred_at IS NULL
            OR NEW.event_level = 'UNKNOWN'
            OR (
                NEW.event_level = 'LEVEL_2'
                AND (NEW.glucose_value IS NULL OR NEW.glucose_unit IS NULL)
            )
            OR (
                NEW.event_level = 'LEVEL_3'
                AND (
                    NEW.external_assistance <> 'YES'
                    OR NEW.altered_function <> 'YES'
                )
            )
        )
        BEGIN SELECT RAISE(ABORT, 'confirmed hypoglycemia evidence is incomplete'); END;

        CREATE TRIGGER IF NOT EXISTS trg_hypo_shadow_review_no_update
        BEFORE UPDATE ON hypoglycemia_shadow_review_events
        BEGIN SELECT RAISE(ABORT, 'hypoglycemia shadow reviews are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS trg_hypo_shadow_review_no_delete
        BEFORE DELETE ON hypoglycemia_shadow_review_events
        BEGIN SELECT RAISE(ABORT, 'hypoglycemia shadow reviews cannot be deleted'); END;

        CREATE TRIGGER IF NOT EXISTS trg_hypo_shadow_review_root
        BEFORE INSERT ON hypoglycemia_shadow_review_events
        WHEN (
            NEW.sequence_number = 1
            AND (
                NEW.event_type <> 'OPENED'
                OR NEW.supersedes_event_id IS NOT NULL
                OR NOT EXISTS (
                    SELECT 1
                    FROM hypoglycemia_shadow_event_versions version
                    WHERE version.id = NEW.event_version_id
                      AND version.patient_link_id = NEW.patient_link_id
                      AND version.status = 'CONFIRMED'
                      AND version.verification = 'CONFIRMED'
                      AND version.version_number = (
                          SELECT MAX(head.version_number)
                          FROM hypoglycemia_shadow_event_versions head
                          WHERE head.event_id = version.event_id
                      )
                )
            )
        )
        BEGIN SELECT RAISE(ABORT, 'review requires current confirmed event'); END;

        CREATE TRIGGER IF NOT EXISTS trg_hypo_shadow_review_linear
        BEFORE INSERT ON hypoglycemia_shadow_review_events
        WHEN NEW.sequence_number > 1 AND NOT EXISTS (
            SELECT 1 FROM hypoglycemia_shadow_review_events prior
            WHERE prior.id = NEW.supersedes_event_id
              AND prior.review_id = NEW.review_id
              AND prior.patient_link_id = NEW.patient_link_id
              AND prior.event_version_id = NEW.event_version_id
              AND prior.owner_username = NEW.owner_username
              AND prior.sequence_number = NEW.sequence_number - 1
              AND prior.sequence_number = (
                  SELECT MAX(head.sequence_number)
                  FROM hypoglycemia_shadow_review_events head
                  WHERE head.review_id = NEW.review_id
              )
        )
        BEGIN SELECT RAISE(ABORT, 'hypoglycemia shadow review history must be linear'); END;

        CREATE TRIGGER IF NOT EXISTS trg_hypo_shadow_review_payload
        BEFORE INSERT ON hypoglycemia_shadow_review_events
        WHEN (
            NEW.event_type = 'DISPOSITION_RECORDED'
            AND (
                NEW.disposition_type IS NULL
                OR length(trim(COALESCE(NEW.rationale, ''))) = 0
            )
        ) OR (
            NEW.event_type <> 'DISPOSITION_RECORDED'
            AND NEW.disposition_type IS NOT NULL
        )
        BEGIN SELECT RAISE(ABORT, 'invalid shadow review payload'); END;
        """
    )
    db.commit()


class HypoglycemiaShadowService:
    """Small append-only shadow workflow with no external clinical side effect."""

    def __init__(
        self,
        db: sqlite3.Connection | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ):
        self._connection = db
        self._clock = clock or (lambda: datetime.now(IRAN_TZ))

    def _db(self) -> sqlite3.Connection:
        if self._connection is None:
            from src.adapters.sqlite.core import get_db

            db = get_db()
        else:
            db = self._connection
        ensure_hypoglycemia_shadow_storage(db)
        return db

    def get_event(self, event_id: str) -> dict[str, Any]:
        rows = [
            dict(row)
            for row in self._db().execute(
                """SELECT * FROM hypoglycemia_shadow_event_versions
                   WHERE event_id=? ORDER BY version_number""",
                (event_id,),
            ).fetchall()
        ]
        if not rows:
            raise LookupError("hypoglycemia shadow event not found")
        return {"event_id": event_id, "versions": rows, "current": rows[-1]}

    def create_candidate(
        self,
        *,
        patient_link_id: int,
        source_system: str,
        source_record_id: str,
        actor_username: str,
        reporter_type: str,
        occurred_at: datetime | str | None = None,
        event_level: str = "UNKNOWN",
        glucose_value: Any = None,
        glucose_unit: Any = None,
        external_assistance: str = "UNKNOWN",
        altered_function: str = "UNKNOWN",
        verification: str = "UNVERIFIED",
        note: str | None = None,
    ) -> dict[str, Any]:
        db = self._db()
        source_system = _required(source_system, "source_system")
        source_record_id = _required(source_record_id, "source_record_id")
        actor_username = _required(actor_username, "actor_username")
        reporter_type = _enum(reporter_type, REPORTERS, "reporter_type")
        event_level = _enum(event_level, EVENT_LEVELS, "event_level")
        external_assistance = _enum(
            external_assistance, TRI_STATES, "external_assistance"
        )
        altered_function = _enum(altered_function, TRI_STATES, "altered_function")
        verification = _enum(verification, VERIFICATIONS, "verification")

        existing = db.execute(
            """SELECT event_id, patient_link_id
               FROM hypoglycemia_shadow_event_versions
               WHERE source_system=? AND source_record_id=? AND version_number=1""",
            (source_system, source_record_id),
        ).fetchone()
        if existing:
            if int(existing["patient_link_id"]) != int(patient_link_id):
                raise HypoglycemiaShadowConflict(
                    "source identity belongs to another patient"
                )
            return self.get_event(str(existing["event_id"]))
        if not db.execute(
            "SELECT 1 FROM patient_links WHERE id=?", (int(patient_link_id),)
        ).fetchone():
            raise LookupError("patient_link_id not found")

        if (glucose_value is None) != (glucose_unit is None):
            raise HypoglycemiaShadowValidationError(
                "glucose value and unit must be supplied together"
            )
        if glucose_value is not None:
            numeric, normalized_unit, _ = _glucose_mg_dl(
                glucose_value, glucose_unit
            )
        else:
            numeric, normalized_unit = None, None

        event_id = f"hypo-shadow-{uuid4().hex}"
        payload = {
            "event_id": event_id,
            "version_number": 1,
            "patient_link_id": int(patient_link_id),
            "source_system": source_system,
            "source_record_id": source_record_id,
            "status": "CANDIDATE",
            "event_level": event_level,
            "occurred_at": (
                _time(occurred_at, self._clock) if occurred_at is not None else None
            ),
            "recorded_at": _time(None, self._clock),
            "glucose_value": numeric,
            "glucose_unit": normalized_unit,
            "external_assistance": external_assistance,
            "altered_function": altered_function,
            "reporter_type": reporter_type,
            "verification": verification,
            "actor_username": actor_username,
            "note": _optional(note),
            "supersedes_version_id": None,
        }
        with db:
            db.execute(
                """INSERT INTO hypoglycemia_shadow_event_versions
                   (event_id, version_number, patient_link_id,
                    source_system, source_record_id, status, event_level,
                    occurred_at, recorded_at, glucose_value, glucose_unit,
                    external_assistance, altered_function, reporter_type,
                    verification, actor_username, note,
                    supersedes_version_id, content_hash)
                   VALUES (?,1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,?)""",
                (
                    event_id,
                    int(patient_link_id),
                    source_system,
                    source_record_id,
                    "CANDIDATE",
                    event_level,
                    payload["occurred_at"],
                    payload["recorded_at"],
                    numeric,
                    normalized_unit,
                    external_assistance,
                    altered_function,
                    reporter_type,
                    verification,
                    actor_username,
                    payload["note"],
                    _hash(payload),
                ),
            )
        return self.get_event(event_id)

    @staticmethod
    def _transition(current: str, decision: str) -> None:
        allowed = {
            "CANDIDATE": DECISIONS,
            "CONFLICT": {"CONFIRMED", "REJECTED", "ENTERED_IN_ERROR"},
            "CONFIRMED": {"ENTERED_IN_ERROR"},
            "REJECTED": set(),
            "ENTERED_IN_ERROR": set(),
        }
        if decision not in allowed.get(current, set()):
            raise HypoglycemiaShadowValidationError(
                f"invalid event transition: {current} -> {decision}"
            )

    @staticmethod
    def _confirmed(payload: dict[str, Any]) -> None:
        if payload["occurred_at"] is None:
            raise HypoglycemiaShadowValidationError(
                "confirmed event requires occurred_at"
            )
        if payload["event_level"] == "UNKNOWN":
            raise HypoglycemiaShadowValidationError(
                "confirmed event requires event_level"
            )
        if payload["event_level"] == "LEVEL_2":
            if payload["glucose_value"] is None:
                raise HypoglycemiaShadowValidationError(
                    "confirmed Level 2 requires glucose"
                )
            if _glucose_mg_dl(
                payload["glucose_value"], payload["glucose_unit"]
            )[2] >= 54:
                raise HypoglycemiaShadowValidationError(
                    "confirmed Level 2 requires glucose below 54 mg/dL"
                )
        if payload["event_level"] == "LEVEL_3":
            if payload["external_assistance"] != "YES":
                raise HypoglycemiaShadowValidationError(
                    "confirmed Level 3 requires external assistance"
                )
            if payload["altered_function"] != "YES":
                raise HypoglycemiaShadowValidationError(
                    "confirmed Level 3 requires altered functioning"
                )

    def adjudicate(
        self,
        event_id: str,
        *,
        expected_current_version_id: int,
        decision: str,
        actor_username: str,
        occurred_at: datetime | str | None = None,
        event_level: str | None = None,
        glucose_value: Any = None,
        glucose_unit: Any = None,
        external_assistance: str | None = None,
        altered_function: str | None = None,
        reporter_type: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        db = self._db()
        current = self.get_event(event_id)["current"]
        if int(current["id"]) != int(expected_current_version_id):
            raise HypoglycemiaShadowConflict("hypoglycemia event head changed")
        decision = _enum(decision, DECISIONS, "decision")
        self._transition(str(current["status"]), decision)

        value = current["glucose_value"] if glucose_value is None else glucose_value
        unit = current["glucose_unit"] if glucose_unit is None else glucose_unit
        if (value is None) != (unit is None):
            raise HypoglycemiaShadowValidationError(
                "glucose value and unit must be supplied together"
            )
        if value is not None:
            value, unit, _ = _glucose_mg_dl(value, unit)

        payload = {
            "event_id": event_id,
            "version_number": int(current["version_number"]) + 1,
            "patient_link_id": int(current["patient_link_id"]),
            "source_system": str(current["source_system"]),
            "source_record_id": str(current["source_record_id"]),
            "status": decision,
            "event_level": (
                str(current["event_level"])
                if event_level is None
                else _enum(event_level, EVENT_LEVELS, "event_level")
            ),
            "occurred_at": (
                current["occurred_at"]
                if occurred_at is None
                else _time(occurred_at, self._clock)
            ),
            "recorded_at": _time(None, self._clock),
            "glucose_value": value,
            "glucose_unit": unit,
            "external_assistance": (
                str(current["external_assistance"])
                if external_assistance is None
                else _enum(
                    external_assistance, TRI_STATES, "external_assistance"
                )
            ),
            "altered_function": (
                str(current["altered_function"])
                if altered_function is None
                else _enum(altered_function, TRI_STATES, "altered_function")
            ),
            "reporter_type": (
                str(current["reporter_type"])
                if reporter_type is None
                else _enum(reporter_type, REPORTERS, "reporter_type")
            ),
            "verification": (
                "CONFIRMED"
                if decision == "CONFIRMED"
                else ("CONFLICT" if decision == "CONFLICT" else current["verification"])
            ),
            "actor_username": _required(actor_username, "actor_username"),
            "note": _optional(note),
            "supersedes_version_id": int(current["id"]),
        }
        if decision == "CONFIRMED":
            self._confirmed(payload)

        with db:
            try:
                db.execute(
                    """INSERT INTO hypoglycemia_shadow_event_versions
                       (event_id, version_number, patient_link_id,
                        source_system, source_record_id, status, event_level,
                        occurred_at, recorded_at, glucose_value, glucose_unit,
                        external_assistance, altered_function, reporter_type,
                        verification, actor_username, note,
                        supersedes_version_id, content_hash)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        payload["event_id"],
                        payload["version_number"],
                        payload["patient_link_id"],
                        payload["source_system"],
                        payload["source_record_id"],
                        payload["status"],
                        payload["event_level"],
                        payload["occurred_at"],
                        payload["recorded_at"],
                        payload["glucose_value"],
                        payload["glucose_unit"],
                        payload["external_assistance"],
                        payload["altered_function"],
                        payload["reporter_type"],
                        payload["verification"],
                        payload["actor_username"],
                        payload["note"],
                        payload["supersedes_version_id"],
                        _hash(payload),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                if "linear" in str(exc).lower() or "unique" in str(exc).lower():
                    raise HypoglycemiaShadowConflict(
                        "hypoglycemia event head changed"
                    ) from exc
                raise
        return self.get_event(event_id)

    def get_review(self, review_id: str) -> dict[str, Any]:
        rows = [
            dict(row)
            for row in self._db().execute(
                """SELECT * FROM hypoglycemia_shadow_review_events
                   WHERE review_id=? ORDER BY sequence_number""",
                (review_id,),
            ).fetchall()
        ]
        if not rows:
            raise LookupError("hypoglycemia shadow review not found")
        return {"review_id": review_id, "events": rows, "current": rows[-1]}

    def open_review(
        self,
        *,
        event_id: str,
        expected_event_version_id: int,
        owner_username: str,
        actor_username: str,
    ) -> dict[str, Any]:
        db = self._db()
        current = self.get_event(event_id)["current"]
        if int(current["id"]) != int(expected_event_version_id):
            raise HypoglycemiaShadowConflict("confirmed event version is stale")
        if current["status"] != "CONFIRMED" or current["verification"] != "CONFIRMED":
            raise HypoglycemiaShadowValidationError(
                "review requires a confirmed event"
            )
        existing = db.execute(
            """SELECT review_id FROM hypoglycemia_shadow_review_events
               WHERE event_version_id=? AND sequence_number=1""",
            (int(expected_event_version_id),),
        ).fetchone()
        if existing:
            return self.get_review(str(existing["review_id"]))

        review_id = f"hypo-review-{uuid4().hex}"
        payload = {
            "review_id": review_id,
            "sequence_number": 1,
            "patient_link_id": int(current["patient_link_id"]),
            "event_version_id": int(current["id"]),
            "owner_username": _required(owner_username, "owner_username"),
            "event_type": "OPENED",
            "disposition_type": None,
            "rationale": None,
            "recorded_at": _time(None, self._clock),
            "actor_username": _required(actor_username, "actor_username"),
            "supersedes_event_id": None,
        }
        with db:
            db.execute(
                """INSERT INTO hypoglycemia_shadow_review_events
                   (review_id, sequence_number, patient_link_id,
                    event_version_id, owner_username, event_type,
                    disposition_type, rationale, recorded_at,
                    actor_username, supersedes_event_id, content_hash)
                   VALUES (?,1,?,?,?,'OPENED',NULL,NULL,?,?,NULL,?)""",
                (
                    review_id,
                    payload["patient_link_id"],
                    payload["event_version_id"],
                    payload["owner_username"],
                    payload["recorded_at"],
                    payload["actor_username"],
                    _hash(payload),
                ),
            )
        return self.get_review(review_id)

    def record_disposition(
        self,
        review_id: str,
        *,
        expected_current_review_event_id: int,
        disposition_type: str,
        rationale: str,
        actor_username: str,
    ) -> dict[str, Any]:
        db = self._db()
        current = self.get_review(review_id)["current"]
        if int(current["id"]) != int(expected_current_review_event_id):
            raise HypoglycemiaShadowConflict("review head changed")
        if current["event_type"] == "ENTERED_IN_ERROR":
            raise HypoglycemiaShadowValidationError("review is terminal")
        source_state = db.execute(
            """SELECT latest.id, latest.status, latest.verification
               FROM hypoglycemia_shadow_event_versions source
               JOIN hypoglycemia_shadow_event_versions latest
                 ON latest.event_id = source.event_id
               WHERE source.id=?
               ORDER BY latest.version_number DESC
               LIMIT 1""",
            (int(current["event_version_id"]),),
        ).fetchone()
        if (
            not source_state
            or int(source_state["id"]) != int(current["event_version_id"])
            or source_state["status"] != "CONFIRMED"
            or source_state["verification"] != "CONFIRMED"
        ):
            raise HypoglycemiaShadowValidationError(
                "review source event is no longer current confirmed"
            )
        payload = {
            "review_id": review_id,
            "sequence_number": int(current["sequence_number"]) + 1,
            "patient_link_id": int(current["patient_link_id"]),
            "event_version_id": int(current["event_version_id"]),
            "owner_username": str(current["owner_username"]),
            "event_type": "DISPOSITION_RECORDED",
            "disposition_type": _enum(
                disposition_type, DISPOSITIONS, "disposition_type"
            ),
            "rationale": _required(rationale, "rationale"),
            "recorded_at": _time(None, self._clock),
            "actor_username": _required(actor_username, "actor_username"),
            "supersedes_event_id": int(current["id"]),
        }
        with db:
            try:
                db.execute(
                    """INSERT INTO hypoglycemia_shadow_review_events
                       (review_id, sequence_number, patient_link_id,
                        event_version_id, owner_username, event_type,
                        disposition_type, rationale, recorded_at,
                        actor_username, supersedes_event_id, content_hash)
                       VALUES (?,?,?,?,?,'DISPOSITION_RECORDED',?,?,?,?,?,?)""",
                    (
                        review_id,
                        payload["sequence_number"],
                        payload["patient_link_id"],
                        payload["event_version_id"],
                        payload["owner_username"],
                        payload["disposition_type"],
                        payload["rationale"],
                        payload["recorded_at"],
                        payload["actor_username"],
                        payload["supersedes_event_id"],
                        _hash(payload),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                if "linear" in str(exc).lower() or "unique" in str(exc).lower():
                    raise HypoglycemiaShadowConflict("review head changed") from exc
                raise
        return self.get_review(review_id)
