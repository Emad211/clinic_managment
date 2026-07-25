"""Release identity shared by package, validation, activation and runtime boundaries.

Changing either the bundled package or executable fact/context/validation contract is a
safety event. Reports and seals from a previous identity remain audit evidence but cannot
activate the new runtime.
"""
from __future__ import annotations


RULESET_CODE = "general-outpatient"
CURRENT_BUNDLED_PACKAGE_VERSION = "2026.1-draft.2"
CURRENT_ENGINE_VERSION = "2.8.0-validation-release"


def base_ruleset_version(version: str | None) -> str:
    """Strip only the guided-workflow attempt suffix from a ruleset version."""
    return str(version or "").split("-attempt.", 1)[0]


def is_current_package_version(version: str | None) -> bool:
    return base_ruleset_version(version) == CURRENT_BUNDLED_PACKAGE_VERSION
