"""Read-only authoritative source-state snapshots for FO-2 shadow projection."""
from __future__ import annotations

from dataclasses import dataclass
import sqlite3

from src.services.followup_orchestration.identity import canonical_hash


def _text(value) -> str | None:
    rendered = str(value or "").strip()
    if not rendered:
        return None
    if len(rendered) == 10:
        return rendered + " 00:00:00"
    return rendered[:19] if len(rendered) >= 19 else rendered


def _row_dict(row) -> dict | None:
    return dict(row) if row else None


def _value(row: dict | None, key: str, default=None):
    if not row or key not in row:
        return default
    return row[key]


@dataclass(frozen=True, slots=True)
class SourceState:
    source_type: str
    source_id: str
    relation_type: str
    source_revision: str
    status: str
    event_at: str | None
    action_due_at: str | None
    target_at: str | None
    details: dict
    error_code: str | None = None

    def as_dict(self) -> dict:
        return {
            "source_type": self.source_type,
            "source_id": self.source_id,
            "relation_type": self.relation_type,
            "source_revision": self.source_revision,
            "status": self.status,
            "event_at": self.event_at,
            "action_due_at": self.action_due_at,
            "target_at": self.target_at,
            "details": self.details,
            "error_code": self.error_code,
        }


class FollowupSourceStateReader:
    """Read FO-1 links and current source heads without mutating any table."""

    def __init__(self, db: sqlite3.Connection):
        self.db = db
        self.db.row_factory = sqlite3.Row

    def _table(self, name: str) -> bool:
        return bool(
            self.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (name,),
            ).fetchone()
        )

    def _one(self, sql: str, params=()) -> dict | None:
        try:
            return _row_dict(self.db.execute(sql, params).fetchone())
        except sqlite3.OperationalError:
            return None

    def episodes(self) -> list[dict]:
        if not self._table("followup_episodes"):
            return []
        return [
            dict(row)
            for row in self.db.execute(
                "SELECT * FROM followup_episodes ORDER BY episode_id"
            ).fetchall()
        ]

    def _links(self, episode_id: str) -> list[dict]:
        if not self._table("followup_episode_links"):
            return []
        return [
            dict(row)
            for row in self.db.execute(
                """SELECT * FROM followup_episode_links
                   WHERE episode_id=? ORDER BY source_type, source_id, id""",
                (str(episode_id),),
            ).fetchall()
        ]

    def _latest_episode_event(self, episode_id: str) -> dict | None:
        if not self._table("followup_episode_events"):
            return None
        return self._one(
            """SELECT event.* FROM followup_episode_events event
               WHERE event.episode_id=? AND NOT EXISTS (
                   SELECT 1 FROM followup_episode_events child
                   WHERE child.supersedes_event_id=event.id
               )
               ORDER BY event.id DESC LIMIT 1""",
            (str(episode_id),),
        )

    def _error(self, link: dict, code: str) -> SourceState:
        return SourceState(
            source_type=str(link["source_type"]),
            source_id=str(link["source_id"]),
            relation_type=str(link["relation_type"]),
            source_revision=str(link["source_revision"]),
            status="UNAVAILABLE",
            event_at=None,
            action_due_at=None,
            target_at=None,
            details={},
            error_code=code,
        )

    @staticmethod
    def _scope(
        link: dict,
        episode: dict,
        patient_link_id: object,
    ) -> str | None:
        if patient_link_id is None:
            return "SOURCE_PATIENT_MISSING"
        if int(patient_link_id) != int(episode["patient_link_id"]):
            return "SOURCE_PATIENT_MISMATCH"
        if int(link["patient_link_id"]) != int(episode["patient_link_id"]):
            return "LINK_PATIENT_MISMATCH"
        return None

    def _admin_task(self, episode: dict, link: dict) -> SourceState:
        row = self._one("SELECT * FROM followup_tasks WHERE id=?", (int(link["source_id"]),))
        if not row:
            return self._error(link, "ADMIN_TASK_NOT_FOUND")
        scope = self._scope(link, episode, row.get("patient_link_id"))
        if scope:
            return self._error(link, scope)
        engine = str(row.get("source_engine") or "")
        if engine == "clinical_v2":
            return self._error(link, "ADMIN_TASK_SOURCE_TYPE_MISMATCH")
        return SourceState(
            source_type="ADMIN_TASK",
            source_id=str(link["source_id"]),
            relation_type=str(link["relation_type"]),
            source_revision=str(link["source_revision"]),
            status=str(row.get("status") or "open").upper(),
            event_at=_text(row.get("resolved_at") or row.get("created_at")),
            action_due_at=_text(row.get("due_date")),
            target_at=None,
            details={
                "reason": str(row.get("reason") or "manual"),
                "source_event": str(row.get("source_event") or ""),
                "fulfillment": str(row.get("fulfillment") or "in_person"),
                "appointment_id": row.get("appointment_id"),
                "assigned": bool(str(row.get("assigned_to") or "").strip()),
            },
        )

    def _clinical_task(self, episode: dict, link: dict) -> SourceState:
        task_id = int(link["source_id"])
        task = self._one("SELECT * FROM followup_tasks WHERE id=?", (task_id,))
        if not task:
            return self._error(link, "CLINICAL_TASK_NOT_FOUND")
        scope = self._scope(link, episode, task.get("patient_link_id"))
        if scope:
            return self._error(link, scope)
        if str(task.get("source_engine") or "") != "clinical_v2":
            return self._error(link, "CLINICAL_TASK_SOURCE_TYPE_MISMATCH")
        head = self._one(
            """SELECT event.* FROM clinical_task_events event
               WHERE event.task_id=? AND NOT EXISTS (
                   SELECT 1 FROM clinical_task_events child
                   WHERE child.supersedes_event_id=event.id
               )
               ORDER BY event.id DESC LIMIT 1""",
            (task_id,),
        )
        if not head:
            return self._error(link, "CLINICAL_TASK_HEAD_MISSING")
        outcome = self._one(
            """SELECT id, verification, observed_at, recorded_at
               FROM clinical_outcome_events WHERE task_id=?
               ORDER BY recorded_at DESC, id DESC LIMIT 1""",
            (task_id,),
        )
        return SourceState(
            source_type="CLINICAL_TASK",
            source_id=str(task_id),
            relation_type=str(link["relation_type"]),
            source_revision=str(link["source_revision"]),
            status=str(head.get("status") or "OPEN").upper(),
            event_at=_text(head.get("recorded_at") or task.get("created_at")),
            action_due_at=_text(head.get("due_at") or task.get("due_date")),
            target_at=None,
            details={
                "appointment_id": head.get("appointment_id"),
                "assigned": bool(str(head.get("assigned_to") or "").strip()),
                "latest_outcome_id": outcome.get("id") if outcome else None,
                "latest_outcome_verification": (
                    str(outcome.get("verification") or "") if outcome else None
                ),
                "latest_outcome_at": (
                    _text(outcome.get("recorded_at")) if outcome else None
                ),
            },
        )

    def _commitment(self, episode: dict, link: dict) -> SourceState:
        commitment_id = str(link["source_id"])
        commitment = self._one(
            "SELECT * FROM care_plan_commitments WHERE commitment_id=?",
            (commitment_id,),
        )
        if not commitment:
            return self._error(link, "ENCOUNTER_COMMITMENT_NOT_FOUND")
        scope = self._scope(link, episode, commitment.get("patient_link_id"))
        if scope:
            return self._error(link, scope)
        head = self._one(
            """SELECT event.* FROM care_plan_commitment_events event
               WHERE event.commitment_id=? AND NOT EXISTS (
                   SELECT 1 FROM care_plan_commitment_events child
                   WHERE child.supersedes_event_id=event.id
               )
               ORDER BY event.id DESC LIMIT 1""",
            (commitment_id,),
        )
        if not head:
            return self._error(link, "ENCOUNTER_COMMITMENT_HEAD_MISSING")
        return SourceState(
            source_type="ENCOUNTER_COMMITMENT",
            source_id=commitment_id,
            relation_type=str(link["relation_type"]),
            source_revision=str(link["source_revision"]),
            status=str(head.get("status") or "OPEN").upper(),
            event_at=_text(head.get("recorded_at") or commitment.get("created_at")),
            action_due_at=_text(head.get("due_at") or commitment.get("original_due_at")),
            target_at=None,
            details={
                "commitment_type": str(commitment.get("commitment_type") or ""),
                "appointment_id": head.get("appointment_id"),
                "assigned": bool(str(head.get("assigned_to") or "").strip()),
                "evidence_type": head.get("evidence_type"),
                "outcome_code": head.get("outcome_code"),
            },
        )

    def _approval(self, episode: dict, link: dict) -> SourceState:
        row = self._one(
            "SELECT * FROM engagement_approvals WHERE id=?",
            (int(link["source_id"]),),
        )
        if not row:
            return self._error(link, "ENGAGEMENT_APPROVAL_NOT_FOUND")
        scope = self._scope(link, episode, row.get("patient_link_id"))
        if scope:
            return self._error(link, scope)
        return SourceState(
            source_type="ENGAGEMENT_APPROVAL",
            source_id=str(link["source_id"]),
            relation_type=str(link["relation_type"]),
            source_revision=str(link["source_revision"]),
            status=str(row.get("status") or "pending").upper(),
            event_at=_text(row.get("decided_at") or row.get("created_at")),
            action_due_at=_text(row.get("due_date")),
            target_at=_text(row.get("due_date")),
            details={
                "event_key": str(row.get("event_key") or ""),
                "sms_message_id": row.get("sms_message_id"),
                "has_error": bool(str(row.get("last_error") or "").strip()),
            },
        )

    def _sms(self, episode: dict, link: dict) -> SourceState:
        row = self._one("SELECT * FROM sms_messages WHERE id=?", (int(link["source_id"]),))
        if not row:
            return self._error(link, "SMS_MESSAGE_NOT_FOUND")
        scope = self._scope(link, episode, row.get("patient_link_id"))
        if scope:
            return self._error(link, scope)
        status = str(row.get("delivery_status") or row.get("status") or "pending").upper()
        return SourceState(
            source_type="SMS_MESSAGE",
            source_id=str(link["source_id"]),
            relation_type=str(link["relation_type"]),
            source_revision=str(link["source_revision"]),
            status=status,
            event_at=_text(
                row.get("delivered_at")
                or row.get("last_attempt_at")
                or row.get("sent_at")
                or row.get("created_at")
            ),
            action_due_at=_text(row.get("next_status_check_at")),
            target_at=None,
            details={
                "submission_status": str(row.get("status") or "").upper(),
                "delivery_status": str(row.get("delivery_status") or "").upper(),
                "retryable": bool(int(row.get("retryable") or 0)),
                "has_error": bool(str(row.get("error") or "").strip()),
            },
        )

    def _appointment(self, episode: dict, link: dict) -> SourceState:
        row = self._one("SELECT * FROM appointments WHERE id=?", (int(link["source_id"]),))
        if not row:
            return self._error(link, "APPOINTMENT_NOT_FOUND")
        scope = self._scope(link, episode, row.get("patient_link_id"))
        if scope:
            return self._error(link, scope)
        return SourceState(
            source_type="APPOINTMENT",
            source_id=str(link["source_id"]),
            relation_type=str(link["relation_type"]),
            source_revision=str(link["source_revision"]),
            status=str(row.get("status") or "scheduled").upper(),
            event_at=_text(row.get("updated_at") or row.get("created_at")),
            action_due_at=None,
            target_at=_text(row.get("scheduled_at")),
            details={"appointment_type": str(row.get("appt_type") or "")},
        )

    def _contact(self, episode: dict, link: dict) -> SourceState:
        row = self._one(
            "SELECT * FROM followup_contact_events WHERE id=?",
            (int(link["source_id"]),),
        )
        if not row:
            return self._error(link, "CONTACT_EVENT_NOT_FOUND")
        scope = self._scope(link, episode, row.get("patient_link_id"))
        if scope:
            return self._error(link, scope)
        return SourceState(
            source_type="CONTACT_EVENT",
            source_id=str(link["source_id"]),
            relation_type=str(link["relation_type"]),
            source_revision=str(link["source_revision"]),
            status=str(row.get("outcome") or "OTHER").upper(),
            event_at=_text(row.get("occurred_at") or row.get("recorded_at")),
            action_due_at=_text(row.get("next_contact_at")),
            target_at=None,
            details={"channel": str(row.get("channel") or "OTHER").upper()},
        )

    def _outcome(self, episode: dict, link: dict) -> SourceState:
        row = self._one(
            """SELECT outcome.*, task.patient_link_id
               FROM clinical_outcome_events outcome
               JOIN followup_tasks task ON task.id=outcome.task_id
               WHERE outcome.id=?""",
            (int(link["source_id"]),),
        )
        if not row:
            return self._error(link, "CLINICAL_OUTCOME_NOT_FOUND")
        scope = self._scope(link, episode, row.get("patient_link_id"))
        if scope:
            return self._error(link, scope)
        return SourceState(
            source_type="CLINICAL_OUTCOME",
            source_id=str(link["source_id"]),
            relation_type=str(link["relation_type"]),
            source_revision=str(link["source_revision"]),
            status=str(row.get("verification") or "UNVERIFIED").upper(),
            event_at=_text(row.get("recorded_at")),
            action_due_at=None,
            target_at=_text(row.get("observed_at")),
            details={"outcome_type": str(row.get("outcome_type") or "OTHER")},
        )

    def _read(self, episode: dict, link: dict) -> SourceState:
        readers = {
            "ADMIN_TASK": self._admin_task,
            "CLINICAL_TASK": self._clinical_task,
            "ENCOUNTER_COMMITMENT": self._commitment,
            "ENGAGEMENT_APPROVAL": self._approval,
            "SMS_MESSAGE": self._sms,
            "APPOINTMENT": self._appointment,
            "CONTACT_EVENT": self._contact,
            "CLINICAL_OUTCOME": self._outcome,
        }
        reader = readers.get(str(link["source_type"]))
        if reader is None:
            return self._error(link, "SOURCE_TYPE_UNSUPPORTED")
        try:
            return reader(episode, link)
        except (KeyError, TypeError, ValueError, sqlite3.Error):
            return self._error(link, "SOURCE_STATE_READ_FAILED")

    def snapshot(self, episode: dict) -> dict:
        links = self._links(str(episode["episode_id"]))
        states = [self._read(episode, link) for link in links]
        state_dicts = [state.as_dict() for state in states]
        state_dicts.sort(key=lambda item: (item["source_type"], item["source_id"]))
        latest = max(
            (state.event_at for state in states if state.event_at),
            default=None,
        )
        current_event = self._latest_episode_event(str(episode["episode_id"]))
        errors = sorted(
            {state.error_code for state in states if state.error_code}
        )
        return {
            "episode": {
                "episode_id": str(episode["episode_id"]),
                "patient_link_id": int(episode["patient_link_id"]),
                "episode_type": str(episode["episode_type"]),
                "semantic_key": str(episode["semantic_key"]),
                "period_key": str(episode["period_key"]),
                "opened_at": _text(episode.get("opened_at")),
                "identity_hash": str(episode["identity_hash"]),
            },
            "sources": state_dicts,
            "source_count": len(state_dicts),
            "source_fingerprint": canonical_hash(state_dicts),
            "last_source_event_at": latest,
            "last_episode_event_id": (
                int(current_event["id"]) if current_event else None
            ),
            "errors": errors,
        }


__all__ = ["FollowupSourceStateReader", "SourceState"]
