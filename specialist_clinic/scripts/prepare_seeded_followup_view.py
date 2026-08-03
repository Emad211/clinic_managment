#!/usr/bin/env python3
"""Prepare Episodes and the Unified projection for an already-seeded local DB.

This is an explicit maintenance command. It never runs from a GET request or normal
startup. Applying requires FOLLOWUP_PROJECTION_SHADOW=1 so the default remains safe.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
SPECIALIST_ROOT = SCRIPT_DIR.parent
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))

from src.adapters.sqlite.core import get_db  # noqa: E402
from src.app import create_app  # noqa: E402
from src.services.clinical_engine.demo_cohort import DemoCohortService  # noqa: E402
from src.services.followup_orchestration.demo_seed_preparation import (  # noqa: E402
    DemoSeedFollowupPreparationService,
)


def _enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def run(database: Path, *, as_of_at: str) -> dict:
    if not database.is_file():
        raise FileNotFoundError(database)
    if not _enabled("FOLLOWUP_PROJECTION_SHADOW"):
        raise RuntimeError(
            "preparation requires FOLLOWUP_PROJECTION_SHADOW=1; default remains OFF"
        )

    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(database),
            "SECRET_KEY": "seeded-followup-recovery",
        }
    )
    with app.app_context():
        result = DemoSeedFollowupPreparationService(get_db()).run(
            as_of_at=as_of_at,
            actor_username="seeded-followup-recovery-cli",
        )
    return {
        "program": "FOUX-V1",
        "repair": "SEEDED_UNIFIED_VIEW_PREPARATION",
        "database": database.name,
        "contains_phi": False,
        **result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare FOUX Episodes and Unified projection after demo seeding."
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=SPECIALIST_ROOT / "specialist.db",
    )
    parser.add_argument(
        "--as-of",
        default=DemoCohortService.reference_at().isoformat(sep=" "),
    )
    args = parser.parse_args()
    payload = run(args.database.resolve(), as_of_at=args.as_of)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
