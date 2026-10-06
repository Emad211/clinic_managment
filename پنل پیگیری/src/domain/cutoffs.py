"""Clinical cut-offs (docs/05 §6, ADR-0009). Pure.

The panel ships with *no* clinical numbers. A draft with any empty threshold
cannot be approved; only the director doctor approves. Rules are checked top
to bottom and the first match decides the actions.
"""
from __future__ import annotations

from typing import Any, Mapping

from ..common.persian_text import fa_digits

METRICS: dict[str, dict[str, tuple[int, int] | tuple[str, ...]]] = {
    "bp": {"systolic": (60, 300), "diastolic": (30, 200)},
    "bs": {"glucose": (20, 700), "glucose_type": ("fasting", "random")},
}
ACTIONS = {"bp": ("invite_visit", "control_series_bp"), "bs": ("invite_visit", "control_series_bs")}
OPS = ("gte", "lte", "eq")
SERIES_COUNT = (1, 10)
SERIES_EVERY = (1, 7)

# The shape of docs/05 §6 with every number empty — what a new draft starts from.
EMPTY_TEMPLATE: dict[str, Any] = {
    "bp": [
        {"when": {"any": [{"metric": "systolic", "gte": None}, {"metric": "diastolic", "gte": None}]},
         "actions": ["invite_visit", "control_series_bp"]},
        {"when": {"any": [{"metric": "systolic", "gte": None}, {"metric": "diastolic", "gte": None}]},
         "actions": ["control_series_bp"]},
    ],
    "bs": [
        {"when": {"all": [{"metric": "glucose_type", "eq": "fasting"}, {"metric": "glucose", "gte": None}]},
         "actions": ["invite_visit"]},
        {"when": {"all": [{"metric": "glucose_type", "eq": "random"}, {"metric": "glucose", "gte": None}]},
         "actions": ["invite_visit"]},
    ],
    "series": {"count": 3, "every_days": 1},
}

LABELS = {"systolic": "سیستولیک", "diastolic": "دیاستولیک", "glucose": "قند", "glucose_type": "نوع قند"}


def _condition_errors(kind: str, cond: Any, where: str) -> list[str]:
    if not isinstance(cond, Mapping) or cond.get("metric") not in METRICS[kind]:
        return [f"{where}: شاخص نامعتبر"]
    ops = [op for op in OPS if op in cond]
    if len(ops) != 1 or set(cond) - {"metric", *OPS}:
        return [f"{where}: هر شرط دقیقاً یک عملگر (≥، ≤ یا =) لازم دارد"]
    metric, op, value = cond["metric"], ops[0], cond[ops[0]]
    bounds = METRICS[kind][metric]
    if isinstance(bounds[0], str):
        return [] if op == "eq" and value in bounds else [f"{where}: مقدار «{LABELS[metric]}» نامعتبر است"]
    if value is None:
        return [f"{where}: عدد «{LABELS[metric]}» خالی است؛ پزشک مدیر باید آن را تعیین کند"]
    if type(value) is not int or not bounds[0] <= value <= bounds[1]:
        return [f"{where}: عدد «{LABELS[metric]}» باید بین {fa_digits(bounds[0])} و {fa_digits(bounds[1])} باشد"]
    if op == "eq":
        return [f"{where}: برای اعداد فقط ≥ یا ≤ مجاز است"]
    return []


def validate(rules: Any) -> list[str]:
    """Persian problems; empty list means the ruleset can be approved."""
    if not isinstance(rules, Mapping):
        return ["قالب کات‌آف نامعتبر است"]
    errors: list[str] = []
    for kind in ("bp", "bs"):
        items = rules.get(kind)
        if not isinstance(items, list) or not items:
            errors.append(f"قاعدهٔ «{'فشار' if kind == 'bp' else 'قند'}» تعریف نشده است")
            continue
        for i, rule in enumerate(items, start=1):
            where = f"{'فشار' if kind == 'bp' else 'قند'}، قاعدهٔ {fa_digits(i)}"
            when = rule.get("when") if isinstance(rule, Mapping) else None
            if not isinstance(when, Mapping) or len(when) != 1 or next(iter(when)) not in ("any", "all") \
                    or not isinstance(next(iter(when.values())), list) or not next(iter(when.values())):
                errors.append(f"{where}: شرط باید «هرکدام» یا «همه» با دست‌کم یک بند باشد")
                continue
            for cond in next(iter(when.values())):
                errors += _condition_errors(kind, cond, where)
            actions = rule.get("actions")
            if not isinstance(actions, list) or not actions or any(a not in ACTIONS[kind] for a in actions):
                errors.append(f"{where}: اقدام نامعتبر یا خالی است")
    series = rules.get("series")
    if not isinstance(series, Mapping):
        errors.append("تنظیم سری کنترل تعریف نشده است")
    else:
        c, e = series.get("count"), series.get("every_days")
        if type(c) is not int or not SERIES_COUNT[0] <= c <= SERIES_COUNT[1]:
            errors.append(f"تعداد نوبت سری باید بین {fa_digits(SERIES_COUNT[0])} و {fa_digits(SERIES_COUNT[1])} باشد")
        if type(e) is not int or not SERIES_EVERY[0] <= e <= SERIES_EVERY[1]:
            errors.append(f"فاصلهٔ نوبت‌های سری باید بین {fa_digits(SERIES_EVERY[0])} و {fa_digits(SERIES_EVERY[1])} روز باشد")
    return errors


def _holds(cond: Mapping[str, Any], m: Mapping[str, Any]) -> bool:
    value = m.get(cond["metric"])
    if value is None:
        return False
    if "eq" in cond:
        return value == cond["eq"]
    if "gte" in cond:
        return value >= cond["gte"]
    return value <= cond["lte"]


def evaluate(rules: Mapping[str, Any], kind: str, measurement: Mapping[str, Any]) -> list[str]:
    """Actions of the first matching rule for this measurement (``kind``: 'bp' | 'bs')."""
    for rule in rules.get(kind, []):
        (mode, conds), = rule["when"].items()
        hits = [_holds(c, measurement) for c in conds]
        if (any(hits) if mode == "any" else all(hits)):
            return list(rule["actions"])
    return []
