"""FO-2 deterministic shadow projection and explainable legacy parity."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import time
import sqlite3

from src.adapters.sqlite.followup_projection_repo import FollowupProjectionRepository
from src.adapters.sqlite.followup_projection_schema import PROJECTION_VERSION
from src.services.followup_orchestration.identity import canonical_hash
from src.services.followup_orchestration.next_action_policy import (
    FollowupNextActionPolicy,
)
from src.services.followup_orchestration.source_state import FollowupSourceStateReader

_IRAN_TZ = timezone(timedelta(hours=3, minutes=30))
_NONTERMINAL_CLINICAL = ("OPEN", "ASSIGNED", "SCHEDULED", "IN_PROGRESS", "DEFERRED")
_NONTERMINAL_PLAN = ("OPEN", "IN_PROGRESS", "SCHEDULED")


def _normalize(value: datetime | str) -> str:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(_IRAN_TZ).replace(tzinfo=None)
    return parsed.isoformat(sep=" ", timespec="seconds")


def _now() -> str:
    return datetime.now(_IRAN_TZ).replace(tzinfo=None).isoformat(
        sep=" ", timespec="seconds"
    )


def _percent(numerator: int, denominator: int) -> float:
    return round(100.0 * numerator / denominator, 2) if denominator else 100.0


class FollowupProjectionService:
    """Build shadow Work Items; never mutate an operational source."""

    def __init__(
        self,
        db: sqlite3.Connection,
        *,
        reader: FollowupSourceStateReader | None = None,
        policy: FollowupNextActionPolicy | None = None,
    ):
        self.db = db
        self.db.row_factory = sqlite3.Row
        self.reader = reader or FollowupSourceStateReader(db)
        self.policy = policy or FollowupNextActionPolicy()

    def build_rows(
        self,
        *,
        as_of_at: datetime | str,
        rebuilt_at: datetime | str | None = None,
    ) -> list[dict]:
        as_of = _normalize(as_of_at)
        rebuilt = _normalize(rebuilt_at) if rebuilt_at is not None else _now()
        rows: list[dict] = []
        for episode in self.reader.episodes():
            snapshot = self.reader.snapshot(episode)
            decision = self.policy.decide(snapshot, as_of_at=as_of)
            row = {
                "episode_id": str(episode["episode_id"]),
                "patient_link_id": int(episode["patient_link_id"]),
                "episode_type": str(episode["episode_type"]),
                **decision.as_dict(),
                "owner_user_id": None,
                "last_source_event_at": snapshot["last_source_event_at"],
                "last_episode_event_id": snapshot["last_episode_event_id"],
                "source_count": int(snapshot["source_count"]),
                "source_fingerprint": str(snapshot["source_fingerprint"]),
                "projection_version": PROJECTION_VERSION,
                "policy_version": self.policy.version,
                "as_of_at": as_of,
                "rebuilt_at": rebuilt,
            }
            hash_payload = {
                key: value
                for key, value in row.items()
                if key not in {"rebuilt_at", "projection_hash"}
            }
            row["projection_hash"] = canonical_hash(hash_payload)
            rows.append(row)
        rows.sort(key=lambda row: row["episode_id"])
        return rows

    @staticmethod
    def set_hash(rows: list[dict]) -> str:
        return canonical_hash(
            [
                {
                    "episode_id": row["episode_id"],
                    "projection_hash": row["projection_hash"],
                }
                for row in sorted(rows, key=lambda item: item["episode_id"])
            ]
        )

    def _legacy_open_keys(self) -> set[str]:
        keys: set[str] = set()
        if self._table("followup_tasks"):
            for row in self.db.execute(
                """SELECT id FROM followup_tasks
                   WHERE status='open'
                     AND COALESCE(source_engine,'') NOT IN (
                         'clinical_v2','encounter_plan'
                     )"""
            ).fetchall():
                keys.add(f"ADMIN_TASK:{int(row[0])}")
        if self._table("clinical_task_events") and self._table("followup_tasks"):
            placeholders = ",".join("?" for _ in _NONTERMINAL_CLINICAL)
            for row in self.db.execute(
                f"""SELECT task.id FROM followup_tasks task
                    JOIN clinical_task_events event ON event.task_id=task.id
                    WHERE task.source_engine='clinical_v2'
                      AND event.status IN ({placeholders})
                      AND NOT EXISTS (
                          SELECT 1 FROM clinical_task_events child
                          WHERE child.supersedes_event_id=event.id
                      )""",
                _NONTERMINAL_CLINICAL,
            ).fetchall():
                keys.add(f"CLINICAL_TASK:{int(row[0])}")
        if self._table("care_plan_commitment_events"):
            placeholders = ",".join("?" for _ in _NONTERMINAL_PLAN)
            for row in self.db.execute(
                f"""SELECT event.commitment_id
                    FROM care_plan_commitment_events event
                    WHERE event.status IN ({placeholders})
                      AND NOT EXISTS (
                          SELECT 1 FROM care_plan_commitment_events child
                          WHERE child.supersedes_event_id=event.id
                      )""",
                _NONTERMINAL_PLAN,
            ).fetchall():
                keys.add(f"ENCOUNTER_COMMITMENT:{str(row[0])}")
        return keys

    def _table(self, name: str) -> bool:
        return bool(
            self.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (name,),
            ).fetchone()
        )

    def parity_report(self, rows: list[dict]) -> dict:
        legacy = self._legacy_open_keys()
        links_by_episode: dict[str, set[str]] = {}
        if self._table("followup_episode_links"):
            for link in self.db.execute(
                """SELECT episode_id, source_type, source_id
                   FROM followup_episode_links"""
            ).fetchall():
                key = f"{str(link['source_type'])}:{str(link['source_id'])}"
                links_by_episode.setdefault(str(link["episode_id"]), set()).add(key)

        projected_nonterminal = {
            row["episode_id"]: row
            for row in rows
            if row["state_class"] != "TERMINAL"
        }
        projected_terminal = {
            row["episode_id"]: row
            for row in rows
            if row["state_class"] == "TERMINAL"
        }
        active_coverage = {
            key
            for episode_id in projected_nonterminal
            for key in links_by_episode.get(episode_id, set())
        }
        terminal_coverage = {
            key
            for episode_id in projected_terminal
            for key in links_by_episode.get(episode_id, set())
        }

        matched = legacy & active_coverage
        legacy_only = legacy - matched
        legacy_reason_counts: dict[str, int] = {}
        for key in sorted(legacy_only):
            if key in terminal_coverage:
                reason = "PROJECTION_TERMINAL_WHILE_LEGACY_OPEN"
            elif key in {
                linked
                for values in links_by_episode.values()
                for linked in values
            }:
                reason = "EPISODE_NOT_NONTERMINAL_OR_NOT_PROJECTED"
            else:
                reason = "LEGACY_SOURCE_NOT_LINKED"
            legacy_reason_counts[reason] = legacy_reason_counts.get(reason, 0) + 1

        projection_only_reason_counts: dict[str, int] = {}
        projection_only = 0
        for episode_id, row in projected_nonterminal.items():
            keys = links_by_episode.get(episode_id, set())
            if keys & legacy:
                continue
            projection_only += 1
            if row["episode_type"] == "ENGAGEMENT":
                reason = "ENGAGEMENT_EPISODE_WITHOUT_OPEN_WORKLIST_SOURCE"
            elif row["state_class"] == "BLOCKED":
                reason = "BLOCKED_EPISODE_WITHOUT_LEGACY_OPEN_SOURCE"
            else:
                reason = "NONTERMINAL_EPISODE_WITHOUT_LEGACY_OPEN_SOURCE"
            projection_only_reason_counts[reason] = (
                projection_only_reason_counts.get(reason, 0) + 1
            )

        classified_mismatches = sum(legacy_reason_counts.values()) + sum(
            projection_only_reason_counts.values()
        )
        mismatch_total = len(legacy_only) + projection_only
        return {
            "legacy_open_count": len(legacy),
            "projected_nonterminal_count": len(projected_nonterminal),
            "projected_terminal_count": len(projected_terminal),
            "matched_legacy_sources": len(matched),
            "legacy_only_count": len(legacy_only),
            "projection_only_count": projection_only,
            "legacy_only_reasons": dict(sorted(legacy_reason_counts.items())),
            "projection_only_reasons": dict(
                sorted(projection_only_reason_counts.items())
            ),
            "coverage_percent": _percent(len(matched), len(legacy)),
            "explainable_mismatch_percent": _percent(
                classified_mismatches, mismatch_total
            ),
            "hidden_legacy_source_count": legacy_reason_counts.get(
                "LEGACY_SOURCE_NOT_LINKED", 0
            ),
        }

    @staticmethod
    def lag_metrics(rows: list[dict]) -> dict:
        lags: list[int] = []
        for row in rows:
            source_at = row.get("last_source_event_at")
            if not source_at:
                continue
            rebuilt = datetime.fromisoformat(str(row["rebuilt_at"]))
            source = datetime.fromisoformat(str(source_at))
            lags.append(max(int((rebuilt - source).total_seconds()), 0))
        return {
            "measured_count": len(lags),
            "max_lag_seconds": max(lags, default=0),
            "average_lag_seconds": (
                round(sum(lags) / len(lags), 2) if lags else 0.0
            ),
        }

    def run(
        self,
        *,
        as_of_at: datetime | str,
        apply: bool,
    ) -> dict:
        started = time.perf_counter()
        rebuilt_at = _now()
        rows = self.build_rows(as_of_at=as_of_at, rebuilt_at=rebuilt_at)
        parity = self.parity_report(rows)
        result = {
            "mode": "apply" if apply else "dry_run",
            "projection_version": PROJECTION_VERSION,
            "policy_version": self.policy.version,
            "as_of_at": _normalize(as_of_at),
            "projection_count": len(rows),
            "projection_set_hash": self.set_hash(rows),
            "state_class_counts": {
                state_class: sum(
                    1 for row in rows if row["state_class"] == state_class
                )
                for state_class in (
                    "ACTION_REQUIRED",
                    "WAITING",
                    "BLOCKED",
                    "TERMINAL",
                )
            },
            "role_proposal_counts": {
                role: sum(
                    1 for row in rows if row["owner_role_proposal"] == role
                )
                for role in ("RECEPTION", "NURSING", "PHYSICIAN", "MANAGER")
            },
            "parity": parity,
            "lag": self.lag_metrics(rows),
        }
        if apply:
            repository = FollowupProjectionRepository(self.db)
            write = repository.replace_all(rows)
            result.update(write)
        result["duration_ms"] = round(
            (time.perf_counter() - started) * 1000.0, 2
        )
        return result


__all__ = ["FollowupProjectionService"]
