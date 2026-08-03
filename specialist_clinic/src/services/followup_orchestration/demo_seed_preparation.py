"""Explicit integration boundary between the synthetic cohort and FOUX read models.

The canonical demo seed owns only TEST0001..TEST0010 source rows. This service is
invoked explicitly by seed/recovery commands after source rows have committed. It
never runs from a GET request or normal application startup.
"""
from __future__ import annotations

from datetime import datetime
import sqlite3

from src.adapters.sqlite.demo_seed_followup_repo import (
    DemoSeedFollowupRepository,
)
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
        self.repository = DemoSeedFollowupRepository(db)

    def run(
        self,
        *,
        as_of_at: datetime | str,
        actor_username: str = "seed-demo-followup-view",
    ) -> dict:
        before = self.repository.counts()
        if not before["patient_count"]:
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
        after = self.repository.counts()
        if before["followup_task_count"] and not after["projection_count"]:
            raise RuntimeError(
                "seeded follow-up tasks exist but the Unified projection is empty"
            )

        return {
            "demo_patient_count": after["patient_count"],
            "demo_followup_task_count": before["followup_task_count"],
            "demo_episode_count": after["episode_count"],
            "demo_projection_count": after["projection_count"],
            "backfill": backfill,
            "projection": projection,
        }


__all__ = ["DemoSeedFollowupPreparationService"]
