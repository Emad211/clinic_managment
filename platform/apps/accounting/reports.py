"""Financial reporting aggregations (ACCOUNTING.md phase 5).

Revenue = visits + injections + procedures (consumables are NOT revenue) —
preserved from the legacy app. Amounts are attributed by the explicit work_date
(a night shift can cross midnight). Generic across clinics: relies on RLS for
tenant scoping (same pattern as the other web views), so call inside the clinic's
tenant context. Gross = full service price; patient share = collected at the desk;
insurer share = billed to the payer.
"""

from django.db.models import Count, Sum

from apps.accounting.models import Injection, Procedure, Visit

REVENUE_MODELS = {"visit": Visit, "injection": Injection, "procedure": Procedure}
SHIFTS = ("morning", "evening", "night")


def _between(qs, date_from, date_to):
    if date_from:
        qs = qs.filter(work_date__gte=date_from)
    if date_to:
        qs = qs.filter(work_date__lte=date_to)
    return qs


def revenue_summary(date_from=None, date_to=None):
    """Totals + per-kind + per-shift breakdown for a date range."""
    by_kind, by_shift = {}, {s: 0 for s in SHIFTS}
    total_gross = total_patient = count = 0
    for kind, Model in REVENUE_MODELS.items():
        agg = _between(Model.objects.all(), date_from, date_to).aggregate(
            g=Sum("amount_rial"), p=Sum("patient_share_rial"), c=Count("id")
        )
        g, p, c = agg["g"] or 0, agg["p"] or 0, agg["c"] or 0
        by_kind[kind] = {"gross": g, "patient": p, "count": c}
        total_gross += g
        total_patient += p
        count += c
        for sh in SHIFTS:
            s = _between(Model.objects.filter(shift=sh), date_from, date_to).aggregate(
                g=Sum("amount_rial")
            )["g"] or 0
            by_shift[sh] += s
    return {
        "total_gross": total_gross,
        "total_patient_share": total_patient,
        "total_insurer_share": total_gross - total_patient,
        "by_kind": by_kind,
        "by_shift": by_shift,
        "count": count,
    }


def revenue_by_insurance(date_from=None, date_to=None):
    rows = {}
    for Model in REVENUE_MODELS.values():
        qs = (
            _between(Model.objects.all(), date_from, date_to)
            .values("insurance_plan__name")
            .annotate(g=Sum("amount_rial"), c=Count("id"))
        )
        for r in qs:
            name = r["insurance_plan__name"] or "آزاد"
            slot = rows.setdefault(name, {"gross": 0, "count": 0})
            slot["gross"] += r["g"] or 0
            slot["count"] += r["c"] or 0
    return [
        {"name": k, **v}
        for k, v in sorted(rows.items(), key=lambda x: -x[1]["gross"])
    ]


def revenue_by_doctor(date_from=None, date_to=None):
    """By visiting doctor (visits only — that's where the doctor is recorded)."""
    qs = (
        _between(Visit.objects.all(), date_from, date_to)
        .values("doctor__full_name", "doctor__username")
        .annotate(g=Sum("amount_rial"), c=Count("id"))
    )
    out = [
        {
            "name": r["doctor__full_name"] or r["doctor__username"] or "—",
            "gross": r["g"] or 0,
            "count": r["c"],
        }
        for r in qs
    ]
    return sorted(out, key=lambda x: -x["gross"])


def daily_series(date_from, date_to):
    """[(work_date, gross), …] across all revenue kinds — for a simple chart/table."""
    totals = {}
    for Model in REVENUE_MODELS.values():
        qs = (
            _between(Model.objects.all(), date_from, date_to)
            .values("work_date")
            .annotate(g=Sum("amount_rial"))
        )
        for r in qs:
            totals[r["work_date"]] = totals.get(r["work_date"], 0) + (r["g"] or 0)
    return [{"date": d, "gross": g} for d, g in sorted(totals.items())]
