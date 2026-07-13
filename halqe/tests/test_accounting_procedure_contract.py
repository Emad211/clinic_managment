"""Small, database-free guards for the procedure pricing contract."""

from accounting_ops.constants import (
    NURSING_ITEM_TYPES,
    PROCEDURE_ITEM_TYPES,
    PRICING_VERSION_VISIT_NURSING_V1,
    PRICING_VERSION_VISIT_PROCEDURE_V1,
    PRICING_VERSION_VISIT_V1,
)


def test_accounting_pricing_versions_are_distinct_and_explicit():
    assert len(
        {
            PRICING_VERSION_VISIT_V1,
            PRICING_VERSION_VISIT_NURSING_V1,
            PRICING_VERSION_VISIT_PROCEDURE_V1,
        }
    ) == 3
    assert PRICING_VERSION_VISIT_PROCEDURE_V1 == "halqe_visit_procedure_v1"


def test_procedure_engine_is_the_complete_current_item_family():
    assert NURSING_ITEM_TYPES < PROCEDURE_ITEM_TYPES
    assert PROCEDURE_ITEM_TYPES == {
        "visit",
        "injection",
        "procedure",
        "consumable",
    }
