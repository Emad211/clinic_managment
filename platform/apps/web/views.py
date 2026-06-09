"""Minimal server-rendered frontend (Django templates; HTMX layered next).

Demoable slice of the wedge: login -> patient list -> patient snapshot + live
ADA suggestions (the ported rule engine). Tenant context is set by
TenantMiddleware from the session; login follows the RLS-correct ordering
(resolve clinic by slug, then authenticate against app_user in tenant context).
"""

from functools import wraps

from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.chronic import rule_engine
from apps.chronic.models import ClinicalRule, VitalReading
from apps.common.tenant import tenant_context
from apps.identity.models import Clinic
from apps.identity.services import AuthError, authenticate
from apps.patients.models import Patient


def login_required_web(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.session.get("user_id"):
            return redirect("web:login")
        return view(request, *args, **kwargs)

    return wrapper


def index(request):
    if request.session.get("user_id"):
        return redirect("web:patients")
    return redirect("web:login")


def login_view(request):
    if request.method == "POST":
        slug = (request.POST.get("clinic_slug") or "").strip()
        username = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""
        ctx = {"slug": slug, "username": username}
        try:
            clinic = Clinic.objects.get(slug=slug)
        except Clinic.DoesNotExist:
            return render(request, "web/login.html", {**ctx, "error": "کلینیک یافت نشد."})
        try:
            with tenant_context(clinic.id):
                user = authenticate(clinic, username, password)
        except AuthError as e:
            return render(request, "web/login.html", {**ctx, "error": e.message})
        request.session["clinic_id"] = str(clinic.id)
        request.session["user_id"] = str(user.id)
        return redirect("web:patients")
    return render(request, "web/login.html", {})


def logout_view(request):
    request.session.flush()
    return redirect("web:login")


@login_required_web
def patient_list(request):
    q = (request.GET.get("q") or "").strip()
    qs = Patient.objects.filter(is_active=True)
    if q:
        qs = qs.filter(
            Q(national_id__icontains=q) | Q(last_name__icontains=q) | Q(first_name__icontains=q)
        )
    patients = list(qs.order_by("last_name", "first_name")[:100])
    return render(request, "web/patients.html", {"patients": patients, "q": q})


@login_required_web
def patient_detail(request, patient_id):
    patient = get_object_or_404(Patient, id=patient_id)
    facts = rule_engine.build_facts(patient)
    suggestions = rule_engine.grouped(facts, ClinicalRule.objects.filter(is_active=True))

    # latest reading per indicator (One-Page Snapshot)
    snapshot, seen = [], set()
    for vr in VitalReading.objects.filter(patient=patient).order_by("indicator_key", "-measured_at"):
        if vr.indicator_key in seen:
            continue
        seen.add(vr.indicator_key)
        snapshot.append(vr)

    return render(request, "web/patient_detail.html", {
        "patient": patient,
        "facts": facts,
        "suggestions": suggestions,
        "snapshot": snapshot,
    })
