# -*- coding: utf-8 -*-
r"""Rebuild the canonical 10-patient longitudinal v2 safety cohort.

Run:  .venv\Scripts\python.exe seed_demo_data.py
Only synthetic identifiers TEST0001..TEST0010 are replaced.  After the source seed is
committed, the command explicitly reconciles FOUX Episodes and rebuilds the disposable
Unified projection so the seeded Worklist is immediately reviewable.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from src.app import create_app


def main():
    from src.adapters.sqlite.core import get_db
    from src.services.clinical_engine.demo_cohort import DemoCohortService
    from src.services.followup_orchestration.demo_seed_preparation import (
        DemoSeedFollowupPreparationService,
    )

    app = create_app({"TESTING": True, "SECRET_KEY": "seed"})
    with app.app_context():
        cohort_service = DemoCohortService()
        summary = cohort_service.ensure(actor="seed-demo-cli", force=True)
        followup = DemoSeedFollowupPreparationService(get_db()).run(
            as_of_at=cohort_service.reference_at(),
            actor_username="seed-demo-cli",
        )
        print(
            f"Rebuilt {summary['patient_count']} patients: "
            f"{summary['totals']['vitals']} vitals, "
            f"{summary['totals']['labs']} labs, "
            f"{summary['totals']['medication_events']} medication events, "
            f"{summary['totals']['notes']} clinical notes; "
            f"prepared {followup['demo_episode_count']} follow-up episodes and "
            f"{followup['demo_projection_count']} Unified rows."
        )


if __name__ == "__main__":
    main()
