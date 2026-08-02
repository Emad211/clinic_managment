"""Repository for immutable FO-1 episode identities, links and append-only events."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.followup_episode_schema import ensure_followup_episode_storage
from src.services.followup_orchestration.identity import (
    EpisodeIdentity,
    canonical_hash,
    canonical_json,
)

_IRAN_TZ = timezone(timedelta(hours=3, minutes=30))


class FollowupEpisodeConflict(RuntimeError):
    pass


def _text(value: datetime | str | None = None) -> str:
    if value is None:
        parsed = datetime.now(_IRAN_TZ)
    elif isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(_IRAN_TZ).replace(tzinfo=None)
    return parsed.isoformat(sep=" ", timespec="seconds")


def _row(row) -> dict | None:
    return dict(row) if row else None


class FollowupEpisodeRepository:
    def __init__(self, db: sqlite3.Connection | None = None):
        self._connection = db or get_db()
        ensure_followup_episode_storage(self._connection)

    def _db(self) -> sqlite3.Connection:
        return self._connection

    def episode(self, episode_id: str) -> dict | None:
        return _row(
            self._db().execute(
                "SELECT * FROM followup_episodes WHERE episode_id=?",
                (str(episode_id),),
            ).fetchone()
        )

    def current_event(self, episode_id: str) -> dict | None:
        return _row(
            self._db().execute(
                """SELECT event.* FROM followup_episode_events event
                   WHERE event.episode_id=? AND NOT EXISTS (
                       SELECT 1 FROM followup_episode_events child
                       WHERE child.supersedes_event_id=event.id
                   )
                   ORDER BY event.id DESC LIMIT 1""",
                (str(episode_id),),
            ).fetchone()
        )

    def create_episode_once(
        self,
        identity: EpisodeIdentity,
        *,
        actor_username: str,
        opened_at: datetime | str,
        recorded_at: datetime | str | None = None,
        commit: bool = True,
    ) -> tuple[dict, bool]:
        db = self._db()
        existing = db.execute(
            "SELECT * FROM followup_episodes WHERE identity_hash=?",
            (identity.identity_hash,),
        ).fetchone()
        if existing:
            row = dict(existing)
            if (
                row["episode_id"] != identity.episode_id
                or int(row["patient_link_id"]) != identity.patient_link_id
                or row["episode_type"] != identity.episode_type
                or row["semantic_key"] != identity.semantic_key
                or row["period_key"] != identity.period_key
                or row["identity_version"] != identity.identity_version
            ):
                raise FollowupEpisodeConflict("EPISODE_IDENTITY_HASH_CONFLICT")
            return row, False

        actor = str(actor_username or "").strip()
        if not actor:
            raise ValueError("actor_username is required")
        opened = _text(opened_at)
        recorded = _text(recorded_at or opened)
        db.execute(
            """INSERT INTO followup_episodes
               (episode_id, patient_link_id, episode_type, semantic_key,
                period_key, identity_version, opened_at, created_at,
                created_by, identity_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                identity.episode_id,
                identity.patient_link_id,
                identity.episode_type,
                identity.semantic_key,
                identity.period_key,
                identity.identity_version,
                opened,
                recorded,
                actor,
                identity.identity_hash,
            ),
        )
        self.append_event_once(
            episode_id=identity.episode_id,
            event_type="EPISODE_OPENED",
            actor_username=actor,
            effective_at=opened,
            recorded_at=recorded,
            idempotency_key=f"episode-open:{identity.episode_id}",
            payload={
                "identity_hash": identity.identity_hash,
                "identity_version": identity.identity_version,
            },
            commit=False,
        )
        if commit:
            db.commit()
        return self.episode(identity.episode_id), True

    def append_event_once(
        self,
        *,
        episode_id: str,
        event_type: str,
        actor_username: str,
        idempotency_key: str,
        payload: dict | None = None,
        effective_at: datetime | str | None = None,
        recorded_at: datetime | str | None = None,
        actor_user_id: int | None = None,
        commit: bool = True,
    ) -> tuple[dict, bool]:
        db = self._db()
        key = str(idempotency_key or "").strip()
        if len(key) < 16:
            raise ValueError("event idempotency key is required")
        existing = db.execute(
            "SELECT * FROM followup_episode_events WHERE idempotency_key=?",
            (key,),
        ).fetchone()
        if existing:
            row = dict(existing)
            if row["episode_id"] != str(episode_id) or row["event_type"] != str(event_type):
                raise FollowupEpisodeConflict(
                    "EPISODE_EVENT_IDEMPOTENCY_SCOPE_MISMATCH"
                )
            return row, False
        if not self.episode(episode_id):
            raise LookupError("follow-up episode not found")

        actor = str(actor_username or "").strip()
        if not actor:
            raise ValueError("actor_username is required")
        effective = _text(effective_at)
        current = self.current_event(episode_id)
        requested_recorded = _text(recorded_at or effective)
        if current and requested_recorded < str(current["recorded_at"]):
            requested_recorded = str(current["recorded_at"])
        normalized_payload = payload or {}
        payload_json = canonical_json(normalized_payload)
        supersedes = int(current["id"]) if current else None
        hash_payload = {
            "actor_user_id": int(actor_user_id) if actor_user_id else None,
            "actor_username": actor,
            "effective_at": effective,
            "episode_id": str(episode_id),
            "event_type": str(event_type),
            "idempotency_key": key,
            "payload": normalized_payload,
            "recorded_at": requested_recorded,
            "supersedes_event_id": supersedes,
        }
        cursor = db.execute(
            """INSERT INTO followup_episode_events
               (episode_id, event_type, effective_at, recorded_at,
                actor_username, actor_user_id, idempotency_key,
                supersedes_event_id, payload_json, content_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(episode_id),
                str(event_type),
                effective,
                requested_recorded,
                actor,
                int(actor_user_id) if actor_user_id else None,
                key,
                supersedes,
                payload_json,
                canonical_hash(hash_payload),
            ),
        )
        if commit:
            db.commit()
        return (
            _row(
                db.execute(
                    "SELECT * FROM followup_episode_events WHERE id=?",
                    (cursor.lastrowid,),
                ).fetchone()
            ),
            True,
        )

    def _source_patient(self, source_type: str, source_id: str) -> int:
        kind = str(source_type)
        if kind == "ADMIN_TASK":
            sql = (
                "SELECT patient_link_id FROM followup_tasks "
                "WHERE id=? AND COALESCE(source_engine,'')<>'clinical_v2'"
            )
            params = (int(source_id),)
        elif kind == "CLINICAL_TASK":
            sql = (
                "SELECT patient_link_id FROM followup_tasks "
                "WHERE id=? AND source_engine='clinical_v2'"
            )
            params = (int(source_id),)
        elif kind == "ENCOUNTER_COMMITMENT":
            sql = (
                "SELECT patient_link_id FROM care_plan_commitments "
                "WHERE commitment_id=?"
            )
            params = (str(source_id),)
        elif kind == "ENGAGEMENT_APPROVAL":
            sql = "SELECT patient_link_id FROM engagement_approvals WHERE id=?"
            params = (int(source_id),)
        elif kind == "SMS_MESSAGE":
            sql = "SELECT patient_link_id FROM sms_messages WHERE id=?"
            params = (int(source_id),)
        elif kind == "APPOINTMENT":
            sql = "SELECT patient_link_id FROM appointments WHERE id=?"
            params = (int(source_id),)
        elif kind == "CONTACT_EVENT":
            sql = "SELECT patient_link_id FROM followup_contact_events WHERE id=?"
            params = (int(source_id),)
        elif kind == "CLINICAL_OUTCOME":
            sql = (
                "SELECT task.patient_link_id FROM clinical_outcome_events outcome "
                "JOIN followup_tasks task ON task.id=outcome.task_id "
                "WHERE outcome.id=?"
            )
            params = (int(source_id),)
        else:
            raise ValueError("unsupported source_type")
        try:
            row = self._db().execute(sql, params).fetchone()
        except (sqlite3.OperationalError, ValueError) as exc:
            raise LookupError("follow-up episode source unavailable") from exc
        if not row or row[0] is None:
            raise LookupError("follow-up episode source not found")
        return int(row[0])

    def link_source_once(
        self,
        *,
        episode_id: str,
        patient_link_id: int,
        source_type: str,
        source_id: str,
        source_revision: str,
        relation_type: str,
        actor_username: str,
        linked_at: datetime | str,
        recorded_at: datetime | str | None = None,
        commit: bool = True,
    ) -> tuple[dict, bool]:
        db = self._db()
        actual_patient = self._source_patient(str(source_type), str(source_id))
        if actual_patient != int(patient_link_id):
            raise FollowupEpisodeConflict("EPISODE_SOURCE_PATIENT_MISMATCH")
        episode = self.episode(episode_id)
        if not episode or int(episode["patient_link_id"]) != int(patient_link_id):
            raise FollowupEpisodeConflict("EPISODE_LINK_PATIENT_MISMATCH")
        revision = str(source_revision or "").strip()
        if len(revision) != 64:
            raise ValueError("source_revision must be a SHA-256 hex digest")
        actor = str(actor_username or "").strip()
        if not actor:
            raise ValueError("actor_username is required")

        existing = db.execute(
            """SELECT * FROM followup_episode_links
               WHERE episode_id=? AND source_type=? AND source_id=?""",
            (str(episode_id), str(source_type), str(source_id)),
        ).fetchone()
        if existing:
            row = dict(existing)
            if (
                row["source_revision"] != revision
                or int(row["patient_link_id"]) != int(patient_link_id)
                or row["relation_type"] != str(relation_type)
            ):
                raise FollowupEpisodeConflict("EPISODE_SOURCE_LINK_CONFLICT")
            return row, False

        linked = _text(linked_at)
        identity = {
            "episode_id": str(episode_id),
            "patient_link_id": int(patient_link_id),
            "relation_type": str(relation_type),
            "source_id": str(source_id),
            "source_revision": revision,
            "source_type": str(source_type),
        }
        key = "episode-link:" + canonical_hash(identity)
        content_payload = {
            **identity,
            "idempotency_key": key,
            "linked_at": linked,
            "linked_by": actor,
        }
        cursor = db.execute(
            """INSERT INTO followup_episode_links
               (episode_id, patient_link_id, source_type, source_id,
                source_revision, relation_type, linked_at, linked_by,
                idempotency_key, content_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(episode_id),
                int(patient_link_id),
                str(source_type),
                str(source_id),
                revision,
                str(relation_type),
                linked,
                actor,
                key,
                canonical_hash(content_payload),
            ),
        )
        link = _row(
            db.execute(
                "SELECT * FROM followup_episode_links WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
        )
        self.append_event_once(
            episode_id=str(episode_id),
            event_type="SOURCE_LINKED",
            actor_username=actor,
            effective_at=linked,
            recorded_at=recorded_at or linked,
            idempotency_key=f"episode-source-event:{key}",
            payload={
                "link_id": int(link["id"]),
                "source_id": str(source_id),
                "source_type": str(source_type),
            },
            commit=False,
        )
        if commit:
            db.commit()
        return link, True

    def links(self, episode_id: str) -> list[dict]:
        return [
            dict(row)
            for row in self._db().execute(
                """SELECT * FROM followup_episode_links
                   WHERE episode_id=? ORDER BY id""",
                (str(episode_id),),
            ).fetchall()
        ]

    def events(self, episode_id: str) -> list[dict]:
        return [
            dict(row)
            for row in self._db().execute(
                """SELECT * FROM followup_episode_events
                   WHERE episode_id=? ORDER BY id""",
                (str(episode_id),),
            ).fetchall()
        ]


__all__ = ["FollowupEpisodeConflict", "FollowupEpisodeRepository"]
