"""Governed v2 rule-count projections for the disease manager page."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

import pytest


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))
if str(SPECIALIST_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT / "tests"))

from test_clinical_engine_v2_compiler import valid_rule
from src.adapters.sqlite.clinical_engine_rules_repo import (
    ClinicalEngineRulesRepository,
)
from src.services.clinical_engine.compiler import RuleCompiler


@pytest.fixture()
def projection_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app({
        "TESTING": True,
        "DATABASE_PATH": str(tmp_path / "rule-projection.db"),
        "BACKUP_FOLDER": str(tmp_path / "backups"),
        "SECRET_KEY": "rule-projection-test",
    })
    context = app.app_context()
    context.push()
    yield app
    context.pop()
    core._initialized = False


def _store_rule(
    repository,
    *,
    code: str,
    version: str,
    condition_codes: list[str],
) -> int:
    raw = deepcopy(valid_rule())
    raw["rule_code"] = code
    raw["version"] = version
    raw["semantic_key"] = f"projection:{code.lower()}"
    raw["scope"]["condition_codes"] = condition_codes
    compiled = RuleCompiler().compile(raw)
    rule_id = repository.create_rule_version(
        compiled, created_by="pytest"
    )
    repository.mark_validated(rule_id, compiled)
    repository.approve_rule_version(rule_id, approved_by="reviewer")
    return rule_id


def test_condition_counts_use_one_governed_ruleset_not_historical_versions(
    projection_app,
):
    repository = ClinicalEngineRulesRepository()
    diabetes = _store_rule(
        repository,
        code="COUNT-DIABETES",
        version="2.0.0",
        condition_codes=["diabetes"],
    )
    cross_disease = _store_rule(
        repository,
        code="COUNT-ALL",
        version="2.0.0",
        condition_codes=[],
    )
    executable_id = repository.create_ruleset(
        "general-outpatient",
        "projection-active",
        [
            {"rule_version_id": diabetes, "sort_order": 10},
            {"rule_version_id": cross_disease, "sort_order": 20},
        ],
        created_by="pytest",
    )
    repository.activate_ruleset(
        executable_id, activated_by="pytest", silent=True
    )

    # A newer draft is under construction, but must not replace the executable
    # package in an operational manager count.
    hypertension = _store_rule(
        repository,
        code="COUNT-HYPERTENSION",
        version="2.0.0",
        condition_codes=["hypertension"],
    )
    repository.create_ruleset(
        "general-outpatient",
        "projection-draft",
        [{"rule_version_id": hypertension, "sort_order": 10}],
        created_by="pytest",
    )

    assert repository.condition_rule_counts() == {
        "all": 1,
        "diabetes": 1,
    }


def test_condition_counts_fall_back_to_latest_draft_before_activation(
    projection_app,
):
    repository = ClinicalEngineRulesRepository()
    thyroid = _store_rule(
        repository,
        code="COUNT-THYROID",
        version="2.0.0",
        condition_codes=["thyroid"],
    )
    repository.create_ruleset(
        "general-outpatient",
        "projection-only-draft",
        [{"rule_version_id": thyroid, "sort_order": 10}],
        created_by="pytest",
    )

    assert repository.condition_rule_counts() == {"thyroid": 1}
