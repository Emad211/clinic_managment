"""Explicit vocabulary corrections for the versioned synthetic activation cohort.

This is not a fuzzy production mapper.  Each entry documents one known seed-only label
that must be converted to the exact canonical catalog display/class before persistence.
Unknown labels remain unchanged and the repository subsequently fails loudly when no
single active catalog concept exists.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable


_DRUG_ALIASES = {
    # Historical fixture typo; canonical drug_catalog generic_fa is
    # «روزوواستاتین».
    ("رزوواستاتین", "statin"): ("روزوواستاتین", "statin"),
}


def _clean(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def canonical_demo_patients(
    patients: Iterable[dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Return a detached cohort with only declared seed aliases corrected."""
    normalized: list[dict[str, Any]] = []
    for source in patients:
        patient = deepcopy(source)
        for medication in patient.get("meds") or []:
            key = (
                _clean(medication.get("name")),
                _clean(medication.get("drug_class")),
            )
            canonical = _DRUG_ALIASES.get(key)
            if canonical:
                medication["name"], medication["drug_class"] = canonical
        normalized.append(patient)
    return tuple(normalized)
