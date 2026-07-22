"""Retired Clinical Engine v1 seed boundary.

The mutable ``clinical_rules`` catalog is no longer populated. Clinical decision rules
are versioned, reviewed and activated exclusively through Clinical Engine v2 packages.
The function remains temporarily import-compatible for installed code paths while the
legacy table is removed in a later schema-cleanup tranche.
"""
from __future__ import annotations

import sqlite3


def seed_clinical_rules(_db: sqlite3.Connection) -> int:
    """Perform no writes and report that zero legacy rules were seeded."""
    return 0
