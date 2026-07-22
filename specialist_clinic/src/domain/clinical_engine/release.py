"""Release identity shared by package, activation and runtime boundaries.

Changing the bundled package version is a safety event: an activation seal tied to an
older ruleset must fail closed until the new immutable package is reviewed and tested.
"""
from __future__ import annotations


RULESET_CODE = "general-outpatient"
CURRENT_BUNDLED_PACKAGE_VERSION = "2026.1-draft.2"


def base_ruleset_version(version: str | None) -> str:
    """Strip only the guided-workflow attempt suffix from a ruleset version."""
    return str(version or "").split("-attempt.", 1)[0]


def is_current_package_version(version: str | None) -> bool:
    return base_ruleset_version(version) == CURRENT_BUNDLED_PACKAGE_VERSION
