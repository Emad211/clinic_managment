"""Source-level regression guards for the post-v1 Clinical Engine runtime."""
from __future__ import annotations

from pathlib import Path


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
SRC = SPECIALIST_ROOT / "src"


def _source(relative: str) -> str:
    return (SRC / relative).read_text(encoding="utf-8")


def test_compiler_and_dto_have_no_legacy_rule_identity():
    sources = {
        "domain/clinical_engine/rules.py": _source(
            "domain/clinical_engine/rules.py"
        ),
        "services/clinical_engine/compiler.py": _source(
            "services/clinical_engine/compiler.py"
        ),
        "services/clinical_engine/compiler_support.py": _source(
            "services/clinical_engine/compiler_support.py"
        ),
    }
    for path, source in sources.items():
        assert "legacy_rule_id" not in source, path


def test_rule_persistence_has_no_source_lineage_column_contract():
    for relative in (
        "adapters/sqlite/clinical_engine_rules_repo.py",
        "adapters/sqlite/clinical_engine_rule_version_repo.py",
        "adapters/sqlite/clinical_engine_ruleset_repo.py",
    ):
        assert "source_legacy_rule_id" not in _source(relative), relative


def test_decision_runtime_has_no_suggestion_log_lineage_contract():
    for relative in (
        "adapters/sqlite/clinical_engine_audit_repo.py",
        "adapters/sqlite/clinical_engine_decision_audit_repo.py",
        "adapters/sqlite/clinical_engine_audit_projection_repo.py",
        "adapters/sqlite/clinical_engine_action_repo.py",
        "services/clinical_engine/decision_service.py",
    ):
        source = _source(relative)
        assert "legacy_source_suggestion_log_id" not in source, relative
        assert "unimported_legacy_decisions" not in source, relative
