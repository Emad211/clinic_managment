"""Service categories of accounting items (docs/03 §9).

An item may carry several categories. Order of precedence for procedures:
the manager's manual map first (``procedure_category_map``), then keywords.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..common.persian_text import compact, normalize

VISIT = "visit"
BS_TEST = "bs_test"
BP_CHECK = "bp_check"
NEBULIZER = "nebulizer"
SUTURE_REMOVAL = "suture_removal"
DRESSING = "dressing"
EAR_IRRIGATION = "ear_irrigation"

ALL = (VISIT, BS_TEST, BP_CHECK, DRESSING, SUTURE_REMOVAL, EAR_IRRIGATION, NEBULIZER)

LABELS_FA = {
    VISIT: "ویزیت", BS_TEST: "تست قند", BP_CHECK: "کنترل فشار", NEBULIZER: "نبولایزر",
    SUTURE_REMOVAL: "کشیدن بخیه", DRESSING: "پانسمان", EAR_IRRIGATION: "شستشوی گوش",
}

BS_TEST_NAME = "تست قند"
BP_CHECK_NAME = "کنترل فشار"
NEBULIZER_WORD = "نبولایزر"

_WASH_STEMS = ("شست", "شتشو", "ستشو", "شستو")


@dataclass(frozen=True)
class ServiceIds:
    """Nursing-service ids resolved by name from accounting's ``nursing_services``."""
    bs_test: frozenset[int] = frozenset()
    bp_check: frozenset[int] = frozenset()
    nebulizer: frozenset[int] = frozenset()


def resolve_service_ids(services: list[tuple[int, str]]) -> ServiceIds:
    bs, bp, neb = set(), set(), set()
    for sid, name in services:
        n = normalize(name)
        if n == normalize(BS_TEST_NAME):
            bs.add(sid)
        elif n == normalize(BP_CHECK_NAME):
            bp.add(sid)
        if NEBULIZER_WORD in compact(name):
            neb.add(sid)
    return ServiceIds(frozenset(bs), frozenset(bp), frozenset(neb))


def injection_categories(service_id: int | None, injection_type: str | None, ids: ServiceIds) -> set[str]:
    name = normalize(injection_type)
    out = set()
    if service_id in ids.bs_test or (service_id not in ids.bp_check and name == normalize(BS_TEST_NAME)):
        out.add(BS_TEST)
    if service_id in ids.bp_check or (service_id not in ids.bs_test and name == normalize(BP_CHECK_NAME)):
        out.add(BP_CHECK)
    if service_id in ids.nebulizer or NEBULIZER_WORD in compact(injection_type):
        out.add(NEBULIZER)
    return out


def procedure_keyword_categories(procedure_type: str | None) -> set[str]:
    text = normalize(procedure_type)
    flat = text.replace(" ", "")
    out = set()
    if "بخی" in flat and any(word.startswith("کش") for word in text.split(" ")):
        out.add(SUTURE_REMOVAL)
    if "پانسم" in flat:
        out.add(DRESSING)
    if "گوش" in flat and any(stem in flat for stem in _WASH_STEMS) and "سوراخ" not in flat:
        out.add(EAR_IRRIGATION)
    return out


def procedure_categories(procedure_type: str | None, manual_map: dict[str, str | None]) -> set[str]:
    """``manual_map``: normalized name → category, or None for «unrelated»."""
    key = normalize(procedure_type)
    if key in manual_map:
        cat = manual_map[key]
        return {cat} if cat else set()
    return procedure_keyword_categories(procedure_type)


def is_ambiguous_procedure(procedure_type: str | None) -> bool:
    """Names that mention a suture but not which action — go to the manager's review list."""
    return "بخی" in compact(procedure_type) and not procedure_keyword_categories(procedure_type)
