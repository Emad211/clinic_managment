"""Shared test support for the exact production Clinical Engine contract.

Tests are not allowed to bypass activation, use an older 2.x label, or omit the patient
revision.  This helper constructs the smallest valid report/approval/seal chain so
application tests exercise the same contract as production.
"""
from __future__ import annotations

import hashlib

from src.adapters.sqlite.clinical_engine_activation_repo import (
    ClinicalEngineActivationRepository,
    content_hash,
    report_core,
)
from src.adapters.sqlite.core import get_db
from src.domain.clinical_engine.release import (
    CURRENT_BUNDLED_PACKAGE_VERSION,
    CURRENT_ENGINE_VERSION,
    RULESET_CODE,
)


_FIXED_AT = "2026-07-22 10:00:00"


def install_sealed_rollout(
    *,
    mode: str = "on_selected",
    ruleset_status: str | None = None,
) -> int:
    """Create or reuse one exact ruleset and seal it for ``mode``."""
    if mode not in {"on_selected", "on"}:
        raise ValueError("test rollout mode must be on_selected or on")
    expected_status = ruleset_status or (
        "SILENT" if mode == "on_selected" else "ACTIVE"
    )
    if expected_status not in {"SILENT", "ACTIVE"}:
        raise ValueError("test ruleset must be SILENT or ACTIVE")

    db = get_db()
    row = db.execute(
        """SELECT * FROM clinical_rulesets
           WHERE ruleset_code=? AND version=?""",
        (RULESET_CODE, CURRENT_BUNDLED_PACKAGE_VERSION),
    ).fetchone()
    if row:
        ruleset_id = int(row["id"])
        db.execute(
            """UPDATE clinical_rulesets
               SET status=?, activated_by='pytest', activated_at=?
               WHERE id=?""",
            (expected_status, _FIXED_AT, ruleset_id),
        )
    else:
        ruleset_hash = hashlib.sha256(
            b"pytest-current-clinical-ruleset"
        ).hexdigest()
        ruleset_id = int(
            db.execute(
                """INSERT INTO clinical_rulesets
                   (ruleset_code, version, content_hash, status,
                    created_by, created_at, activated_by, activated_at)
                   VALUES (?, ?, ?, ?, 'pytest', ?, 'pytest', ?)""",
                (
                    RULESET_CODE,
                    CURRENT_BUNDLED_PACKAGE_VERSION,
                    ruleset_hash,
                    expected_status,
                    _FIXED_AT,
                    _FIXED_AT,
                ),
            ).lastrowid
        )
    db.commit()

    ruleset = db.execute(
        """SELECT id, ruleset_code, version, content_hash, status
           FROM clinical_rulesets WHERE id=?""",
        (ruleset_id,),
    ).fetchone()
    report = {
        "schema_version": "1.1",
        "engine_version": CURRENT_ENGINE_VERSION,
        "as_of_at": _FIXED_AT,
        "cohort": [],
        "ruleset": dict(ruleset),
        "patients": [],
        "failures": [],
        "checks": {"exact_test_contract": True},
        "status": "PASS",
    }
    report["report_hash"] = content_hash(report_core(report))

    state = ClinicalEngineActivationRepository()
    state.put_json("last_report", report)
    for role in ("clinical", "technical"):
        state.put_json(
            f"approval_{role}",
            {
                "role": role,
                "reviewer": f"pytest-{role}",
                "note": "exact current-run test contract",
                "report_hash": report["report_hash"],
                "engine_version": CURRENT_ENGINE_VERSION,
                "approved_at": _FIXED_AT,
            },
        )
    seal_body = {
        "mode": mode,
        "engine_version": CURRENT_ENGINE_VERSION,
        "ruleset_id": ruleset_id,
        "report_hash": report["report_hash"],
        "activated_by": "pytest",
        "activated_at": _FIXED_AT,
    }
    state.put_json(
        "seal",
        {**seal_body, "seal_hash": content_hash(seal_body)},
    )
    state.set_raw_mode(mode)
    assert state.valid_seal(mode)
    return ruleset_id


def current_snapshot(patient_link_id: int, *, revision: int = 0) -> dict:
    return {
        "schema_version": "2.0",
        "patient_link_id": int(patient_link_id),
        "clinical_data_revision": int(revision),
        "as_of_at": "2026-07-22T10:00:00+03:30",
        "encounter_key": None,
        "facts": [],
        "content_hash": hashlib.sha256(
            f"pytest:{patient_link_id}:{revision}".encode("utf-8")
        ).hexdigest(),
    }
