"""FO-1 deterministic source discovery and explicit Episode/link backfill."""
from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3

from src.adapters.sqlite.followup_episode_repo import FollowupEpisodeRepository
from src.services.followup_orchestration.identity import EpisodeIdentity, canonical_hash


def _safe(value):
    if isinstance(value, bytes):
        return value.hex()
    return value


def _revision_for(source_type: str, row) -> str:
    """Hash immutable source identity fields, not mutable lifecycle state."""
    keys_by_type = {
        "ADMIN_TASK": (
            "id",
            "patient_link_id",
            "source_engine",
            "source_rule",
            "source_event",
        ),
        "CLINICAL_TASK": (
            "id",
            "patient_link_id",
            "source_engine",
            "clinical_task_key",
            "clinical_due_period",
        ),
        "ENCOUNTER_COMMITMENT": (
            "commitment_id",
            "patient_link_id",
            "document_event_id",
            "client_key",
        ),
        "ENGAGEMENT_APPROVAL": (
            "id",
            "patient_link_id",
            "event_key",
            "period_key",
        ),
        "SMS_MESSAGE": (
            "id",
            "patient_link_id",
            "source_type",
            "source_ref",
        ),
        "APPOINTMENT": ("id", "patient_link_id"),
        "CONTACT_EVENT": (
            "id",
            "task_id",
            "patient_link_id",
            "idempotency_key",
        ),
        "CLINICAL_OUTCOME": ("id", "task_id", "content_hash"),
    }
    keys = keys_by_type[source_type]
    available = set(row.keys())
    return canonical_hash(
        {key: _safe(row[key]) if key in available else None for key in keys}
    )


def _date(value, fallback: str = "undated") -> str:
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 else fallback


def _source_at(row, *, period_key: str | None = None) -> str | None:
    for key in (
        "created_at",
        "recorded_at",
        "occurred_at",
        "linked_at",
        "opened_at",
        "scheduled_at",
        "effective_at",
        "taken_at",
        "due_date",
        "original_due_at",
    ):
        if key in row.keys():
            value = str(row[key] or "").strip()
            if len(value) >= 19:
                return value[:19]
            if len(value) >= 10:
                return value[:10] + " 00:00:00"
    period = str(period_key or "").strip()
    if len(period) >= 10 and period[4:5] == "-" and period[7:8] == "-":
        return period[:10] + " 00:00:00"
    return None


@dataclass(frozen=True, slots=True)
class Candidate:
    identity: EpisodeIdentity
    source_type: str
    source_id: str
    source_revision: str
    relation_type: str
    source_at: str

    @property
    def key(self) -> tuple[str, str, str]:
        return self.identity.episode_id, self.source_type, self.source_id


class FollowupEpisodeBackfillService:
    """Plan links from provable source relationships; never guess ambiguous links."""

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

    def _rows(self, table: str, sql: str | None = None, params=()):
        if not self._table(table):
            return []
        return self.db.execute(sql or f"SELECT * FROM {table}", params).fetchall()

    @staticmethod
    def _orphan(source_type: str, source_id: object, reason: str) -> dict:
        return {
            "source_type": str(source_type),
            "source_id": str(source_id),
            "reason": str(reason),
        }

    def plan(self) -> dict:
        candidates: dict[tuple[str, str, str], Candidate] = {}
        orphans: list[dict] = []
        task_identity: dict[int, EpisodeIdentity] = {}

        dispatch_by_task: dict[int, list] = {}
        for row in self._rows(
            "engagement_dispatch",
            """SELECT * FROM engagement_dispatch
               WHERE channel='worklist' AND ref_id IS NOT NULL""",
        ):
            dispatch_by_task.setdefault(int(row["ref_id"]), []).append(row)

        commitments = {
            str(row["commitment_id"]): row
            for row in self._rows("care_plan_commitments")
        }
        task_links = {
            int(row["task_id"]): str(row["commitment_id"])
            for row in self._rows("care_plan_commitment_task_links")
        }

        def add(
            identity: EpisodeIdentity,
            source_type: str,
            source_id: object,
            row,
            relation: str = "PRIMARY",
        ) -> None:
            source_at = _source_at(row, period_key=identity.period_key)
            if not source_at:
                orphans.append(
                    self._orphan(source_type, source_id, "SOURCE_TIMESTAMP_MISSING")
                )
                return
            candidate = Candidate(
                identity=identity,
                source_type=str(source_type),
                source_id=str(source_id),
                source_revision=_revision_for(source_type, row),
                relation_type=str(relation),
                source_at=source_at,
            )
            prior = candidates.get(candidate.key)
            if prior and prior.source_revision != candidate.source_revision:
                orphans.append(
                    self._orphan(
                        source_type,
                        source_id,
                        "DUPLICATE_SOURCE_REVISION_CONFLICT",
                    )
                )
                return
            candidates[candidate.key] = candidate

        for row in self._rows(
            "followup_tasks", "SELECT * FROM followup_tasks ORDER BY id"
        ):
            task_id = int(row["id"])
            patient_id = int(row["patient_link_id"])
            source_engine = (
                str(row["source_engine"] or "")
                if "source_engine" in row.keys()
                else ""
            )
            source_type = "ADMIN_TASK"

            if source_engine == "clinical_v2":
                key = (
                    str(row["clinical_task_key"] or "").strip()
                    if "clinical_task_key" in row.keys()
                    else ""
                )
                if not key:
                    orphans.append(
                        self._orphan(
                            "CLINICAL_TASK", task_id, "CLINICAL_TASK_KEY_MISSING"
                        )
                    )
                    continue
                period = _date(
                    row["clinical_due_period"]
                    if "clinical_due_period" in row.keys()
                    else None,
                    _date(row["due_date"] if "due_date" in row.keys() else None),
                )
                identity = EpisodeIdentity.build(
                    patient_link_id=patient_id,
                    episode_type="CLINICAL_TASK",
                    semantic_key=f"clinical-task:{key}",
                    period_key=period,
                )
                source_type = "CLINICAL_TASK"
            elif source_engine == "encounter_plan":
                commitment_id = task_links.get(task_id) or str(
                    row["source_rule"] or ""
                ).strip()
                commitment = commitments.get(commitment_id)
                if not commitment:
                    orphans.append(
                        self._orphan(
                            "ADMIN_TASK",
                            task_id,
                            "ENCOUNTER_COMMITMENT_NOT_FOUND",
                        )
                    )
                    continue
                if int(commitment["patient_link_id"]) != patient_id:
                    orphans.append(
                        self._orphan(
                            "ADMIN_TASK",
                            task_id,
                            "ENCOUNTER_COMMITMENT_PATIENT_MISMATCH",
                        )
                    )
                    continue
                identity = EpisodeIdentity.build(
                    patient_link_id=patient_id,
                    episode_type="ENCOUNTER_COMMITMENT",
                    semantic_key=f"commitment:{commitment_id}",
                    period_key=_date(commitment["original_due_at"]),
                )
                add(
                    identity,
                    "ENCOUNTER_COMMITMENT",
                    commitment_id,
                    commitment,
                    "PRIMARY",
                )
            else:
                dispatches = dispatch_by_task.get(task_id, [])
                if len(dispatches) == 1:
                    dispatch = dispatches[0]
                    identity = EpisodeIdentity.build(
                        patient_link_id=patient_id,
                        episode_type="ENGAGEMENT",
                        semantic_key=f"engagement:{dispatch['event_key']}",
                        period_key=str(dispatch["period_key"]),
                    )
                else:
                    if len(dispatches) > 1:
                        orphans.append(
                            self._orphan(
                                "ADMIN_TASK",
                                task_id,
                                "MULTIPLE_WORKLIST_DISPATCH_ROWS",
                            )
                        )
                    period = _date(
                        row["due_date"] if "due_date" in row.keys() else None,
                        _date(
                            row["created_at"]
                            if "created_at" in row.keys()
                            else None
                        ),
                    )
                    identity = EpisodeIdentity.build(
                        patient_link_id=patient_id,
                        episode_type="ADMIN_FOLLOWUP",
                        semantic_key=f"admin-task:{task_id}",
                        period_key=period,
                    )

            task_identity[task_id] = identity
            add(identity, source_type, task_id, row, "PRIMARY")

        approval_identity: dict[int, EpisodeIdentity] = {}
        for row in self._rows(
            "engagement_approvals",
            "SELECT * FROM engagement_approvals ORDER BY id",
        ):
            approval_id = int(row["id"])
            patient_id = int(row["patient_link_id"])
            event_key = str(row["event_key"] or "").strip()
            period_key = str(row["period_key"] or "").strip()
            if not event_key or not period_key:
                orphans.append(
                    self._orphan(
                        "ENGAGEMENT_APPROVAL",
                        approval_id,
                        "ENGAGEMENT_IDENTITY_MISSING",
                    )
                )
                continue
            identity = EpisodeIdentity.build(
                patient_link_id=patient_id,
                episode_type="ENGAGEMENT",
                semantic_key=f"engagement:{event_key}",
                period_key=period_key,
            )
            approval_identity[approval_id] = identity
            add(identity, "ENGAGEMENT_APPROVAL", approval_id, row, "PRIMARY")

        for row in self._rows(
            "sms_messages", "SELECT * FROM sms_messages ORDER BY id"
        ):
            message_id = int(row["id"])
            source_type = (
                str(row["source_type"] or "").strip().lower()
                if "source_type" in row.keys()
                else ""
            )
            source_ref = (
                str(row["source_ref"] or "").strip()
                if "source_ref" in row.keys()
                else ""
            )
            if source_type != "engagement" or not source_ref.isdigit():
                orphans.append(
                    self._orphan(
                        "SMS_MESSAGE",
                        message_id,
                        "SMS_OUTSIDE_FOLLOWUP_ENGAGEMENT",
                    )
                )
                continue
            identity = approval_identity.get(int(source_ref))
            if not identity:
                orphans.append(
                    self._orphan(
                        "SMS_MESSAGE",
                        message_id,
                        "ENGAGEMENT_APPROVAL_NOT_FOUND",
                    )
                )
                continue
            if (
                row["patient_link_id"] is None
                or int(row["patient_link_id"]) != identity.patient_link_id
            ):
                orphans.append(
                    self._orphan(
                        "SMS_MESSAGE", message_id, "SMS_PATIENT_MISMATCH"
                    )
                )
                continue
            add(identity, "SMS_MESSAGE", message_id, row, "COMMUNICATION")

        for row in self._rows(
            "followup_contact_events",
            "SELECT * FROM followup_contact_events ORDER BY id",
        ):
            contact_id = int(row["id"])
            identity = task_identity.get(int(row["task_id"]))
            if not identity:
                orphans.append(
                    self._orphan(
                        "CONTACT_EVENT",
                        contact_id,
                        "CONTACT_TASK_EPISODE_NOT_FOUND",
                    )
                )
                continue
            if int(row["patient_link_id"]) != identity.patient_link_id:
                orphans.append(
                    self._orphan(
                        "CONTACT_EVENT", contact_id, "CONTACT_PATIENT_MISMATCH"
                    )
                )
                continue
            add(identity, "CONTACT_EVENT", contact_id, row, "CONTACT")

        for row in self._rows(
            "clinical_outcome_events",
            "SELECT * FROM clinical_outcome_events ORDER BY id",
        ):
            outcome_id = int(row["id"])
            identity = task_identity.get(int(row["task_id"]))
            if not identity or identity.episode_type != "CLINICAL_TASK":
                orphans.append(
                    self._orphan(
                        "CLINICAL_OUTCOME",
                        outcome_id,
                        "CLINICAL_TASK_EPISODE_NOT_FOUND",
                    )
                )
                continue
            add(identity, "CLINICAL_OUTCOME", outcome_id, row, "OUTCOME")

        appointment_targets: dict[int, set[EpisodeIdentity]] = {}
        for row in self._rows(
            "followup_tasks",
            """SELECT id, appointment_id FROM followup_tasks
               WHERE appointment_id IS NOT NULL""",
        ):
            identity = task_identity.get(int(row["id"]))
            if identity:
                appointment_targets.setdefault(
                    int(row["appointment_id"]), set()
                ).add(identity)
        for row in self._rows(
            "clinical_task_events",
            """SELECT task_id, appointment_id FROM clinical_task_events
               WHERE appointment_id IS NOT NULL""",
        ):
            identity = task_identity.get(int(row["task_id"]))
            if identity:
                appointment_targets.setdefault(
                    int(row["appointment_id"]), set()
                ).add(identity)
        for row in self._rows(
            "care_plan_commitment_events",
            """SELECT commitment_id, appointment_id
               FROM care_plan_commitment_events
               WHERE appointment_id IS NOT NULL""",
        ):
            commitment = commitments.get(str(row["commitment_id"]))
            if commitment:
                identity = EpisodeIdentity.build(
                    patient_link_id=int(commitment["patient_link_id"]),
                    episode_type="ENCOUNTER_COMMITMENT",
                    semantic_key=f"commitment:{commitment['commitment_id']}",
                    period_key=_date(commitment["original_due_at"]),
                )
                appointment_targets.setdefault(
                    int(row["appointment_id"]), set()
                ).add(identity)
        for row in self._rows("followup_booking_requests"):
            try:
                task_ids = json.loads(str(row["task_ids_json"]))
                if not isinstance(task_ids, list):
                    raise ValueError("task_ids_json must be a list")
            except (TypeError, ValueError, json.JSONDecodeError):
                orphans.append(
                    self._orphan(
                        "APPOINTMENT",
                        row["appointment_id"],
                        "BOOKING_TASK_LIST_INVALID",
                    )
                )
                continue
            for task_id in task_ids:
                identity = task_identity.get(int(task_id))
                if identity:
                    appointment_targets.setdefault(
                        int(row["appointment_id"]), set()
                    ).add(identity)

        appointment_rows = {
            int(row["id"]): row for row in self._rows("appointments")
        }
        for appointment_id, identities in sorted(appointment_targets.items()):
            appointment = appointment_rows.get(appointment_id)
            if not appointment:
                orphans.append(
                    self._orphan(
                        "APPOINTMENT", appointment_id, "APPOINTMENT_NOT_FOUND"
                    )
                )
                continue
            for identity in sorted(
                identities, key=lambda item: item.episode_id
            ):
                if int(appointment["patient_link_id"]) != identity.patient_link_id:
                    orphans.append(
                        self._orphan(
                            "APPOINTMENT",
                            appointment_id,
                            "APPOINTMENT_PATIENT_MISMATCH",
                        )
                    )
                    continue
                add(
                    identity,
                    "APPOINTMENT",
                    appointment_id,
                    appointment,
                    "SCHEDULE",
                )

        ordered = sorted(
            candidates.values(),
            key=lambda item: (
                item.identity.episode_id,
                item.source_at,
                item.source_type,
                item.source_id,
            ),
        )
        by_source: dict[str, int] = {}
        for candidate in ordered:
            by_source[candidate.source_type] = (
                by_source.get(candidate.source_type, 0) + 1
            )
        by_reason: dict[str, int] = {}
        for orphan in orphans:
            by_reason[orphan["reason"]] = by_reason.get(orphan["reason"], 0) + 1

        episode_opened_at: dict[str, str] = {}
        for candidate in ordered:
            current = episode_opened_at.get(candidate.identity.episode_id)
            if current is None or candidate.source_at < current:
                episode_opened_at[candidate.identity.episode_id] = candidate.source_at

        ordered_orphans = sorted(
            orphans,
            key=lambda item: (
                item["source_type"],
                item["source_id"],
                item["reason"],
            ),
        )
        return {
            "schema_version": "1.0",
            "episodes_planned": len(episode_opened_at),
            "links_planned": len(ordered),
            "candidate_counts": dict(sorted(by_source.items())),
            "orphan_count": len(orphans),
            "orphan_reasons": dict(sorted(by_reason.items())),
            "orphans": ordered_orphans,
            "episode_opened_at": episode_opened_at,
            "candidates": ordered,
            "plan_hash": canonical_hash(
                {
                    "candidates": [
                        {
                            "episode_id": item.identity.episode_id,
                            "relation_type": item.relation_type,
                            "source_at": item.source_at,
                            "source_id": item.source_id,
                            "source_revision": item.source_revision,
                            "source_type": item.source_type,
                        }
                        for item in ordered
                    ],
                    "orphans": ordered_orphans,
                    "schema_version": "1.0",
                }
            ),
        }

    def run(
        self,
        *,
        apply: bool,
        actor_username: str = "system:foux-fo1-backfill",
    ) -> dict:
        planned = self.plan()
        result = {
            key: value
            for key, value in planned.items()
            if key not in {"candidates", "episode_opened_at"}
        }
        result.update(
            {
                "mode": "apply" if apply else "dry_run",
                "episodes_created": 0,
                "episodes_existing": 0,
                "links_created": 0,
                "links_existing": 0,
            }
        )
        if not apply:
            return result

        repo = FollowupEpisodeRepository(self.db)
        processed_episodes: set[str] = set()
        try:
            for candidate in planned["candidates"]:
                episode_id = candidate.identity.episode_id
                if episode_id not in processed_episodes:
                    opened_at = planned["episode_opened_at"][episode_id]
                    _, created = repo.create_episode_once(
                        candidate.identity,
                        actor_username=actor_username,
                        opened_at=opened_at,
                        recorded_at=opened_at,
                        commit=False,
                    )
                    result[
                        "episodes_created" if created else "episodes_existing"
                    ] += 1
                    processed_episodes.add(episode_id)
                _, linked = repo.link_source_once(
                    episode_id=episode_id,
                    patient_link_id=candidate.identity.patient_link_id,
                    source_type=candidate.source_type,
                    source_id=candidate.source_id,
                    source_revision=candidate.source_revision,
                    relation_type=candidate.relation_type,
                    actor_username=actor_username,
                    linked_at=candidate.source_at,
                    recorded_at=candidate.source_at,
                    commit=False,
                )
                result["links_created" if linked else "links_existing"] += 1
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return result


__all__ = ["Candidate", "FollowupEpisodeBackfillService"]
