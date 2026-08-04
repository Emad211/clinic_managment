#!/usr/bin/env python3
"""Explicit operator CLI for FOUX-V1 FO-6 governed CARE SMS.

No command is scheduled or called from application startup.  ``publish``, ``collect``
and ``execute`` require FOLLOWUP_SMS_AUTO_GUARDED=1.  ``status`` is read-only and may
be used while the flag is off.
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
from src.services.sms.auto_guard_service import (  # noqa: E402
    DEFAULT_TTL_HOURS,
    SmsAutoGuardError,
    SmsAutoGuardService,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Explicit FOUX-V1 FO-6 governed CARE SMS operations."
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=SPECIALIST_ROOT / "specialist.db",
    )
    parser.add_argument(
        "--actor",
        default="system:fo6-cli",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    publish = sub.add_parser("publish", help="Publish immutable policy/templates")
    publish.add_argument("--ttl-hours", type=int, default=DEFAULT_TTL_HOURS)

    collect = sub.add_parser("collect", help="Collect bounded due candidates")
    collect.add_argument("--limit", type=int, default=100)
    collect.add_argument("--patient-id", type=int, action="append", default=[])

    execute = sub.add_parser("execute", help="Execute bounded available candidates")
    execute.add_argument("--limit", type=int, default=20)
    execute.add_argument("--candidate-id", type=int)

    status = sub.add_parser("status", help="Read PHI-minimized status")
    status.add_argument("--limit", type=int, default=100)
    return parser


def _redact_status(payload: dict) -> dict:
    """Keep CLI output operational and PHI-minimized."""
    candidates = []
    for item in payload.get("candidates", []):
        candidates.append(
            {
                "id": item.get("id"),
                "patient_link_id": item.get("patient_link_id"),
                "event_key": item.get("event_key"),
                "period_key": item.get("period_key"),
                "generation_no": item.get("generation_no"),
                "expires_at": item.get("expires_at"),
                "state": item.get("state"),
            }
        )
    decisions = []
    for item in payload.get("decisions", []):
        decisions.append(
            {
                "id": item.get("id"),
                "candidate_id": item.get("candidate_id"),
                "decision_type": item.get("decision_type"),
                "attempt_no": item.get("attempt_no"),
                "reason_code": item.get("reason_code"),
                "message_id": item.get("message_id"),
                "recorded_at": item.get("recorded_at"),
            }
        )
    return {
        "program": "FOUX-V1",
        "tranche": "FO-6",
        "storage_ready": bool(payload.get("storage_ready")),
        "feature_enabled": bool(payload.get("feature_enabled")),
        "policy_version": (payload.get("policy") or {}).get("version"),
        "template_versions": {
            key: (value or {}).get("version")
            for key, value in (payload.get("templates") or {}).items()
        },
        "candidates": candidates,
        "decisions": decisions,
        "contains_raw_phone_or_body": False,
    }


def main() -> int:
    args = _build_parser().parse_args()
    database = args.database.resolve()
    if not database.is_file():
        raise FileNotFoundError(database)
    os.environ["SPECIALIST_DB_PATH"] = str(database)
    app = create_app(
        {
            "DATABASE_PATH": str(database),
            "SECRET_KEY": "fo6-explicit-cli",
        }
    )
    try:
        with app.app_context():
            service = SmsAutoGuardService(get_db())
            if args.command == "publish":
                result = service.publish_current_contract(
                    actor_username=args.actor,
                    ttl_hours=args.ttl_hours,
                )
            elif args.command == "collect":
                result = service.collect_candidates(
                    actor_username=args.actor,
                    limit=args.limit,
                    patient_ids=args.patient_id or None,
                )
            elif args.command == "execute":
                if args.candidate_id:
                    result = service.execute_candidate(
                        args.candidate_id,
                        actor_username=args.actor,
                    )
                else:
                    result = service.execute_pending(
                        actor_username=args.actor,
                        limit=args.limit,
                    )
            else:
                result = _redact_status(service.status(limit=args.limit))
    except SmsAutoGuardError as exc:
        print(
            json.dumps(
                {"ok": False, "reason": exc.code, "message": exc.message},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
