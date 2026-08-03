"""Persistence adapter for canonical TEST cohort follow-up preparation metrics."""
from __future__ import annotations

import sqlite3


class DemoSeedFollowupRepository:
    """Keep TEST cohort schema knowledge out of orchestration services."""

    def __init__(self, db: sqlite3.Connection):
        self.db = db
        self.db.row_factory = sqlite3.Row

    def counts(self) -> dict[str, int]:
        row = self.db.execute(
            """WITH demo_patients AS (
                   SELECT id FROM patient_links
                   WHERE national_id GLOB 'TEST[0-9][0-9][0-9][0-9]'
               )
               SELECT
                 (SELECT COUNT(*) FROM demo_patients) AS patient_count,
                 (SELECT COUNT(*) FROM followup_tasks task
                  WHERE task.patient_link_id IN (SELECT id FROM demo_patients))
                    AS followup_task_count,
                 (SELECT COUNT(*) FROM followup_episodes episode
                  WHERE episode.patient_link_id IN (SELECT id FROM demo_patients))
                    AS episode_count,
                 (SELECT COUNT(*) FROM followup_work_item_projection projection
                  WHERE projection.patient_link_id IN (SELECT id FROM demo_patients))
                    AS projection_count"""
        ).fetchone()
        return {
            "patient_count": int(row["patient_count"]),
            "followup_task_count": int(row["followup_task_count"]),
            "episode_count": int(row["episode_count"]),
            "projection_count": int(row["projection_count"]),
        }


__all__ = ["DemoSeedFollowupRepository"]
