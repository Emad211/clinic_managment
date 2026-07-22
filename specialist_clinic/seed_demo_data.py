# -*- coding: utf-8 -*-
r"""Rebuild the canonical 10-patient longitudinal v2 safety cohort.

Run:  .venv\Scripts\python.exe seed_demo_data.py
Only synthetic identifiers TEST0001..TEST0010 are replaced.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from src.app import create_app


def main():
    from src.services.clinical_engine.demo_cohort import DemoCohortService

    app = create_app({"TESTING": True, "SECRET_KEY": "seed"})
    with app.app_context():
        summary = DemoCohortService().ensure(actor="seed-demo-cli", force=True)
        print(
            f"Rebuilt {summary['patient_count']} patients: "
            f"{summary['totals']['vitals']} vitals, "
            f"{summary['totals']['labs']} labs, "
            f"{summary['totals']['medication_events']} medication events, "
            f"{summary['totals']['notes']} clinical notes."
        )


if __name__ == "__main__":
    main()
