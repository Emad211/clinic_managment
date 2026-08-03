"""Explicit integration boundary between the synthetic cohort and FOUX read models.

The canonical demo seed owns only TEST0001..TEST0010 source rows.  This service is
invoked explicitly by the seed/recovery commands after those source rows have been
committed.  It never runs from a GET request or normal application startup.
"""
from __future__ import annotations

from datetime import datetime
import sqlite3

from src.services.followup_orchestration.backfill import (
    FollowupEpisodeBackfillService,
)
from src.services.followup_orchestration.projection_service import (
    FollowupProjectionService,
)


class DemoSeedFollowupPreparationService:
    """Backfill Episodes and rebuild the disposable view after synthetic seeding."""

    def __init__(self, db: sqlite3.Connection):
        self.db = db
        self.db.row_factory = sqlite3.Row

    def _demo_patient_ids(self) -> list[int]:
        return [
            int(row[0])
            for row in self.db.execute(
                """SELECT id FROM patient_links
                   WHERE national_id GLOB 'TEST[0-9][0-9][0-9][0-9]'
                   ORDER BY national_id"""
            ).fetchall()
        ]

    @staticmethod
    def _marks(values: list[int]) -> str:
        return ",".join("?" for _ in values)

    def _count_for_patients(self, table: str, patient_ids: list[int]) -> int:
        if not patient_ids:
            return 0
        marks = self._marks(patient_ids)
        return int(
            self.db.execute(
                f"SELECT COUNT(*) FROM {table} WHERE patient_link_id IN ({marks})",
                patient_ids,
            ).fetchone()[0]
        )

    def run(
        self,
        *,
        as_of_at: datetime | str,
        actor_username: str = "seed-demo-followup-view",
    ) -> dict:
        patient_ids = self._demo_patient_ids()
        source_task_count = self._count_for_patients(
            "followup_tasks", patient_ids
        )
        if not patient_ids:
            raise RuntimeError(
                "canonical TEST0001..TEST0010 cohort is not present; run the demo seed first"
            )

        backfill = FollowupEpisodeBackfillService(self.db).run(
            apply=True,
            actor_username=actor_username,
        )
        projection = FollowupProjectionService(self.db).run(
            as_of_at=as_of_at,
            apply=True,
        )

        episode_count = self._count_for_patients(
            "followup_episodes", patient_ids
        )
        projection_count = self._count_for_patients(
            "followup_work_item_projection", patient_ids
        )
        if source_task_count and not projection_count:
            raise RuntimeError(
                "seeded follow-up tasks exist but the Unified projection is empty"
            )

        return {
            "demo_patient_count": len(patient_ids),
            "demo_followup_task_count": source_task_count,
            "demo_episode_count": episode_count,
            "demo_projection_count": projection_count,
            "backfill": backfill,
            "projection": projection,
        }


__all__ = ["DemoSeedFollowupPreparationService"]
