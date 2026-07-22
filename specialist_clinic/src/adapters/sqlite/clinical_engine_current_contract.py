"""Exact current-rollout validation shared by all Clinical Engine writes.

There is intentionally no legacy or test-only bypass.  Tests construct the same sealed
rollout contract as production; an older engine version, missing revision, different
ruleset, raw setting change or revoked seal always fails closed.
"""
from __future__ import annotations

import json

from src.adapters.sqlite.clinical_engine_activation_repo import (
    ClinicalEngineActivationRepository,
)


VISIBLE_MODES = frozenset({"on_selected", "on"})


def snapshot_revision(snapshot_json: str | None) -> int | None:
    try:
        payload = json.loads(snapshot_json or "{}")
        value = payload.get("clinical_data_revision")
        return int(value) if value is not None else None
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def same_optional_int(left, right) -> bool:
    return (int(left) if left is not None else None) == (
        int(right) if right is not None else None
    )


def assert_current_rollout_contract(
    db,
    *,
    context,
    patient_revision: int,
    mode: str,
    engine_version: str,
    ruleset_id: int | None,
    clinical_data_revision: int,
    error_code: str,
    activation: ClinicalEngineActivationRepository | None = None,
) -> None:
    """Raise ``RuntimeError(error_code)`` unless every current-run dimension matches."""
    activation = activation or ClinicalEngineActivationRepository()
    raw = db.execute(
        "SELECT value FROM settings WHERE key='clinical_engine_v2_mode'"
    ).fetchone()
    raw_mode = str(raw["value"] if raw else "off").strip().lower()
    seal = activation.get_json("seal")
    seal_ruleset_id = (
        int(seal["ruleset_id"])
        if isinstance(seal, dict) and seal.get("ruleset_id") is not None
        else None
    )
    valid = (
        mode in VISIBLE_MODES
        and raw_mode == mode
        and str(context["engine_version"]) == str(engine_version)
        and ruleset_id is not None
        and same_optional_int(context["ruleset_id"], ruleset_id)
        and same_optional_int(seal_ruleset_id, ruleset_id)
        and snapshot_revision(context["fact_snapshot_json"])
        == int(clinical_data_revision)
        and int(patient_revision) == int(clinical_data_revision)
        and activation.valid_seal(mode)
    )
    if not valid:
        raise RuntimeError(error_code)
