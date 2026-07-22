"""Focused guards for explicit seed-only medication vocabulary corrections."""
from __future__ import annotations

from src.domain.clinical_engine.demo_cohort_vocabulary import (
    canonical_demo_patients,
)


def test_short_glargine_seed_label_maps_to_exact_catalog_concept_without_mutation():
    source = ({
        "nid": "TEST0008",
        "meds": [{
            "name": "گلارژین",
            "drug_class": "insulin_basal",
            "dose": "۱۸ واحد",
        }],
    },)

    canonical = canonical_demo_patients(source)

    assert canonical[0]["meds"][0]["name"] == "انسولین گلارژین"
    assert canonical[0]["meds"][0]["drug_class"] == "insulin_basal"
    assert source[0]["meds"][0]["name"] == "گلارژین"


def test_unknown_seed_label_is_not_fuzzily_upgraded():
    source = ({
        "nid": "TEST9999",
        "meds": [{
            "name": "انسولین نامشخص",
            "drug_class": "insulin_basal",
        }],
    },)

    canonical = canonical_demo_patients(source)

    assert canonical == source
    assert canonical is not source
