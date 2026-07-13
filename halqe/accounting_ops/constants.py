"""Stable accounting migration constants shared by command services."""

PRICING_VERSION_VISIT_V1 = "halqe_visit_v1"
PRICING_VERSION_VISIT_NURSING_V1 = "halqe_visit_nursing_v1"
PRICING_VERSION_VISIT_PROCEDURE_V1 = "halqe_visit_procedure_v1"

PAYMENT_TYPES = frozenset({"cash", "card", "insurance", "supplementary"})
PAYMENT_LABELS = {
    "cash": "نقد",
    "card": "کارت",
    "insurance": "بیمه",
    "supplementary": "بیمهٔ تکمیلی",
}

VISIT_ITEM_TYPES = frozenset({"visit"})
NURSING_ITEM_TYPES = frozenset({"visit", "injection", "consumable"})
PROCEDURE_ITEM_TYPES = frozenset(
    {"visit", "injection", "procedure", "consumable"}
)
