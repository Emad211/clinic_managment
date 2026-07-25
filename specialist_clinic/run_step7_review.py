"""Start an isolated, pre-populated local review environment for Step 7."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys
import threading
import webbrowser


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app import create_app
from src.services.clinical_engine.activation import (
    ClinicalEngineActivationService,
)
from src.services.clinical_engine.demo_cohort import DemoCohortService
from src.services.clinical_engine.package_service import ClinicalRulePackageService


def _prepare(app, *, reset: bool) -> dict:
    with app.app_context():
        package_service = ClinicalRulePackageService()
        projection = package_service.projection()
        if projection["state"] == "missing":
            package_service.prepare(actor="local-review-technical")
            projection = package_service.projection()
        if projection["state"] == "review":
            ruleset = projection["ruleset"]
            package_service.approve_and_freeze(
                int(ruleset["id"]),
                reviewer="local-review-physician",
                attested_codes=[rule["code"] for rule in projection["rules"]],
                note=(
                    "Local review fixture: eligibility, trigger, recommendation, "
                    "scope and automation limits reviewed."
                ),
            )

        cohort = DemoCohortService()
        cohort.ensure(actor="local-review", force=reset)
        activation = ClinicalEngineActivationService()
        report = activation.build_report(
            as_of_at=cohort.reference_at(),
            created_by="local-review",
        )
        if report["status"] == "PASS":
            state = activation.state
            for role, reviewer, note in (
                (
                    "clinical",
                    "local-review-physician",
                    "Golden cases, explanations and clinical boundaries reviewed.",
                ),
                (
                    "technical",
                    "local-review-engineer",
                    "Determinism, hashes, storage and failure metrics reviewed.",
                ),
            ):
                current = state.get_json(f"approval_{role}")
                if not current or current.get("report_hash") != report["report_hash"]:
                    activation.approve(
                        role,
                        reviewer=reviewer,
                        report_hash=report["report_hash"],
                        note=note,
                    )
        return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the isolated Clinical Engine Step 7 review environment."
    )
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--port", type=int, default=5057)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    review_root = ROOT / "instance" / "step7-review"
    database = review_root / "clinic-step7-review.db"
    backups = review_root / "backups"
    if args.reset and review_root.exists():
        shutil.rmtree(review_root)
    review_root.mkdir(parents=True, exist_ok=True)
    backups.mkdir(parents=True, exist_ok=True)

    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(database),
            "BACKUP_FOLDER": str(backups),
            "SECRET_KEY": "local-step7-review-only",
            "PRODUCTION": False,
        }
    )
    report = _prepare(app, reset=args.reset)
    url = f"http://127.0.0.1:{args.port}/manager/clinical-engine?step=3#engine-actions"
    print("=" * 72)
    print("Clinical Engine Step 7 local review")
    print(f"database: {database}")
    print(f"validation: {(report.get('validation') or {}).get('status', 'UNKNOWN')}")
    print(f"activation report: {report.get('status', 'UNKNOWN')}")
    print(f"open: {url}")
    print("login: admin / admin (development review database only)")
    print("=" * 72)
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(
        debug=False,
        host="127.0.0.1",
        port=args.port,
        use_reloader=False,
        threaded=True,
    )


if __name__ == "__main__":
    main()
