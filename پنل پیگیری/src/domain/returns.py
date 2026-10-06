"""Return matching (docs/05 §4, ADR-0006). Pure.

A *return* is a valid accounting item (M2) of an expected category on a
later, non-origin invoice of the same person (M3), assigned to the best
pending expect step (M4), one-to-one (M5).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Item:
    item_type: str
    item_id: int
    invoice_id: int
    work_date: date | None
    categories: frozenset[str]
    is_paid: bool
    deleted: bool
    invoice_closed: bool
    invoice_total: float | None


@dataclass(frozen=True)
class OpenStep:
    step_id: int
    journey_id: int
    category: str
    due_date: date
    window_end: date
    accept_early: bool
    journey_start: date
    origin_invoice_id: int | None


def basis(item: Item) -> str | None:
    """M2: 'paid', 'zero_total_closed' or None (not a valid return item)."""
    if item.deleted or not item.categories or item.work_date is None:
        return None
    if item.is_paid:
        return "paid"
    if item.invoice_closed and (item.invoice_total or 0) == 0:
        return "zero_total_closed"
    return None


def eligible(item: Item, step: OpenStep, category: str) -> bool:
    """M3 + M4 date rules for one step."""
    if step.category != category or item.invoice_id == step.origin_invoice_id:
        return False
    day = item.work_date
    if day is None or day <= step.journey_start or day > step.window_end:
        return False
    return step.accept_early or day >= step.due_date


def choose(item: Item, steps: list[OpenStep], taken: set[int]) -> tuple[OpenStep, str] | None:
    """Best step for this item: lowest due date, then oldest journey (M4). ``taken``: steps already used."""
    candidates = [(s, c) for c in sorted(item.categories) for s in steps
                  if s.step_id not in taken and eligible(item, s, c)]
    if not candidates:
        return None
    return min(candidates, key=lambda sc: (sc[0].due_date, sc[0].journey_id, sc[0].step_id))
