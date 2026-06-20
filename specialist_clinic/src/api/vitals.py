from flask import Blueprint, request, redirect, url_for, flash, g
from src.api.auth import login_required
from src.adapters.sqlite.vitals_repo import VitalsRepository, VITAL_TYPES
from src.services.activity_logger import log_activity
from src.common.utils import jalali_to_gregorian_str

bp = Blueprint("vitals", __name__, url_prefix="/vitals")


@bp.route("/<int:pid>/add", methods=["POST"])
@login_required
def add_reading(pid):
    from src.adapters.sqlite.clinical_rules_repo import ClinicalRulesRepository
    repo = VitalsRepository()
    measured = jalali_to_gregorian_str(request.form.get("measured_date", ""))
    measured_at = f"{measured} 12:00:00" if measured else None
    added = 0
    # Accept any indicator defined in the editable rules (plus legacy vital types).
    indicators = ClinicalRulesRepository().as_map()
    keys = set(indicators.keys()) | set(VITAL_TYPES.keys())
    for vtype in keys:
        raw = request.form.get(vtype, "").strip()
        if raw == "":
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        unit = (indicators.get(vtype) or {}).get('unit') or VITAL_TYPES.get(vtype, {}).get('unit')
        repo.add_reading(pid, vtype=vtype, value=value, unit=unit, measured_at=measured_at,
                         recorded_by=g.user["username"])
        added += 1
    if added:
        log_activity("vitals_add", f"ثبت {added} شاخص حیاتی", patient_link_id=pid)
        flash(f"{added} شاخص ثبت شد", "success")
    else:
        flash("هیچ مقداری وارد نشد")
    return redirect(url_for("patients.detail", pid=pid) + "#vitals")


@bp.route("/<int:pid>/reading/<int:reading_id>/delete", methods=["POST"])
@login_required
def delete_reading(pid, reading_id):
    VitalsRepository().delete_reading(reading_id)
    return redirect(url_for("patients.detail", pid=pid) + "#vitals")


def _to_float(raw):
    raw = (raw or "").strip()
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


@bp.route("/<int:pid>/lab/add", methods=["POST"])
@login_required
def add_lab(pid):
    """Batch + catalog-aware lab entry.

    The redesigned record form posts parallel arrays (one row per chosen test):
    test_name[], test_key[], value[], unit[], ref_low[], ref_high[] + a single
    taken_date. Each row with a non-empty test_name AND value is inserted.
    Falls back to the legacy single-row fields if the arrays aren't present.
    """
    repo = VitalsRepository()
    taken = jalali_to_gregorian_str(request.form.get("taken_date", ""))
    taken_at = f"{taken} 12:00:00" if taken else None

    names = request.form.getlist("test_name[]")
    if names:
        values = request.form.getlist("value[]")
        units = request.form.getlist("unit[]")
        keys = request.form.getlist("test_key[]")
        ref_lows = request.form.getlist("ref_low[]")
        ref_highs = request.form.getlist("ref_high[]")

        def at(arr, i):
            return arr[i] if i < len(arr) else ""

        added = 0
        for i, raw_name in enumerate(names):
            name = (raw_name or "").strip()
            value = _to_float(at(values, i))
            if not name or value is None:
                continue
            repo.add_lab(
                pid, test_name=name, test_key=(at(keys, i) or "").strip() or None, value=value,
                unit=(at(units, i) or "").strip() or None,
                ref_low=_to_float(at(ref_lows, i)),
                ref_high=_to_float(at(ref_highs, i)),
                taken_at=taken_at,
                recorded_by=g.user["username"],
            )
            added += 1
        if added:
            log_activity("lab_add", f"ثبت {added} آزمایش", patient_link_id=pid)
            flash(f"{added} آزمایش ثبت شد", "success")
        else:
            flash("هیچ آزمایشی ثبت نشد")
        return redirect(url_for("patients.detail", pid=pid) + "#record")

    # ---- legacy single-row fallback ----
    name = request.form.get("test_name", "").strip()
    if not name:
        flash("نام آزمایش الزامی است")
        return redirect(url_for("patients.detail", pid=pid) + "#record")
    repo.add_lab(
        pid, test_name=name, test_key=(request.form.get("test_key") or "").strip() or None,
        value=_to_float(request.form.get("value")),
        unit=request.form.get("unit") or None,
        ref_low=_to_float(request.form.get("ref_low")),
        ref_high=_to_float(request.form.get("ref_high")),
        taken_at=taken_at,
        notes=request.form.get("notes") or None,
        recorded_by=g.user["username"],
    )
    log_activity("lab_add", f"ثبت آزمایش: {name}", patient_link_id=pid)
    flash("آزمایش ثبت شد", "success")
    return redirect(url_for("patients.detail", pid=pid) + "#record")


@bp.route("/<int:pid>/lab/<int:lab_id>/delete", methods=["POST"])
@login_required
def delete_lab(pid, lab_id):
    VitalsRepository().delete_lab(lab_id)
    return redirect(url_for("patients.detail", pid=pid) + "#labs")
