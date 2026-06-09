"""Minimal server-rendered frontend (Django templates; HTMX layered next).

Demoable slice of the wedge: login -> patient list -> patient snapshot + live
ADA suggestions (the ported rule engine). Tenant context is set by
TenantMiddleware from the session; login follows the RLS-correct ordering
(resolve clinic by slug, then authenticate against app_user in tenant context).
"""

from functools import wraps

from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.chronic import rule_engine
from apps.chronic.models import ClinicalRule, FollowupTask, SuggestionLog, VitalReading
from apps.common.tenant import tenant_context
from apps.identity.models import AppUser, Clinic
from apps.identity.services import AuthError, authenticate
from apps.patients.models import Patient
from apps.rx.models import InsurerLog, Prescription, PrescriptionItem

# Official insurer portals embedded by the WebView bridge (EPRESCRIPTION.md path A)
INSURER_PORTALS = {
    "tamin": "https://ep.tamin.ir/",
    "ihio": "https://eservices.ihio.gov.ir/",
    "armed": "",
}
INSURER_LABELS = {"tamin": "تأمین اجتماعی", "ihio": "بیمهٔ سلامت", "armed": "نیروهای مسلح"}


def login_required_web(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.session.get("user_id"):
            return redirect("web:login")
        return view(request, *args, **kwargs)

    return wrapper


def _current_user(request):
    uid = request.session.get("user_id")
    if not uid:
        return None
    return AppUser.objects.filter(id=uid).first()


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

    # which suggestions has a physician already acknowledged? (accountability)
    acked = set(
        SuggestionLog.objects.filter(patient=patient)
        .exclude(acknowledged_at__isnull=True)
        .values_list("rule_code", flat=True)
    )

    prescriptions = list(
        Prescription.objects.filter(patient=patient).order_by("-created_at")[:10]
    )

    return render(request, "web/patient_detail.html", {
        "patient": patient,
        "facts": facts,
        "suggestions": suggestions,
        "snapshot": snapshot,
        "acked": acked,
        "prescriptions": prescriptions,
        "insurer_labels": INSURER_LABELS,
    })


# ── e-prescription (Epic 1) — WebView bridge workflow ──────────────────────

@login_required_web
def rx_new(request, patient_id):
    """Start a draft prescription for a patient (channel=webview)."""
    patient = get_object_or_404(Patient, id=patient_id)
    if request.method != "POST":
        return redirect("web:patient_detail", patient_id=patient_id)
    insurer = (request.POST.get("insurer") or "tamin").strip()
    if insurer not in INSURER_PORTALS:
        insurer = "tamin"
    rx = Prescription.objects.create(
        clinic=patient.clinic, patient=patient, doctor=_current_user(request),
        insurer=insurer, status="draft", channel="webview",
    )
    InsurerLog.objects.create(
        clinic=patient.clinic, prescription=rx, insurer=insurer,
        action="draft_created", status="draft", payload={},
    )
    return redirect("web:rx_detail", rx_id=rx.id)


@login_required_web
def rx_detail(request, rx_id):
    rx = get_object_or_404(Prescription, id=rx_id)
    items = list(PrescriptionItem.objects.filter(prescription=rx))
    logs = list(InsurerLog.objects.filter(prescription=rx).order_by("created_at"))
    return render(request, "web/rx_detail.html", {
        "rx": rx, "items": items, "logs": logs,
        "portal_url": INSURER_PORTALS.get(rx.insurer, ""),
        "insurer_label": INSURER_LABELS.get(rx.insurer, rx.insurer),
    })


@login_required_web
def rx_add_item(request, rx_id):
    rx = get_object_or_404(Prescription, id=rx_id)
    if request.method == "POST":
        name = (request.POST.get("item_name") or "").strip()
        if name:
            PrescriptionItem.objects.create(
                clinic=rx.clinic, prescription=rx, kind=request.POST.get("kind", "drug"),
                item_name=name, dose=request.POST.get("dose", ""),
                count=(request.POST.get("count") or None),
                instruction=request.POST.get("instruction", ""),
            )
    return redirect("web:rx_detail", rx_id=rx.id)


@login_required_web
def rx_register(request, rx_id):
    """Record the insurer tracking code returned by the portal and mark the
    prescription registered (logs to InsurerLog for the audit trail)."""
    rx = get_object_or_404(Prescription, id=rx_id)
    if request.method == "POST":
        code = (request.POST.get("tracking_code") or "").strip()
        rx.tracking_code = code
        rx.status = "registered" if code else "submitted"
        rx.issued_at = timezone.now()
        rx.save(update_fields=["tracking_code", "status", "issued_at", "updated_at"])
        InsurerLog.objects.create(
            clinic=rx.clinic, prescription=rx, insurer=rx.insurer,
            action="register", status=rx.status, payload={"tracking_code": code},
        )
    return redirect("web:rx_detail", rx_id=rx.id)


@login_required_web
def worklist(request):
    """Recall / follow-up worklist (Epic 3) — the chronic-disease differentiator
    no competitor has. Lists due monitoring/screening tasks across the clinic,
    split into overdue / due-today / upcoming."""
    today = timezone.localdate()
    tasks = list(
        FollowupTask.objects.filter(status="open")
        .select_related("patient")
        .order_by("due_date")[:300]
    )
    overdue = [t for t in tasks if t.due_date and t.due_date < today]
    due_today = [t for t in tasks if t.due_date == today]
    upcoming = [t for t in tasks if not t.due_date or t.due_date > today]
    return render(request, "web/worklist.html", {
        "overdue": overdue, "due_today": due_today, "upcoming": upcoming,
        "today": today, "total": len(tasks),
    })


@login_required_web
def followup_done(request, task_id):
    if request.method == "POST":
        t = FollowupTask.objects.filter(id=task_id).first()
        if t:
            t.status = "done"
            t.handled_at = timezone.now()
            t.save(update_fields=["status", "handled_at", "updated_at"])
    return redirect("web:worklist")


@login_required_web
def acknowledge_suggestion(request, patient_id):
    """Physician acknowledges a suggestion -> append-only SuggestionLog row.
    Embodies the safety principle: the system suggests, the physician decides,
    and the decision is logged (gated to logged-in clinical users)."""
    if request.method != "POST":
        return redirect("web:patient_detail", patient_id=patient_id)
    patient = get_object_or_404(Patient, id=patient_id)
    rule_code = (request.POST.get("rule_code") or "").strip()
    rule = ClinicalRule.objects.filter(code=rule_code).first()
    if rule and not SuggestionLog.objects.filter(
        patient=patient, rule_code=rule_code
    ).exclude(acknowledged_at__isnull=True).exists():
        SuggestionLog.objects.create(
            clinic=patient.clinic,
            patient=patient,
            rule_code=rule_code,
            severity=rule.severity,
            message_fa=rule.recommendation or rule.title,
            acknowledged_by=_current_user(request),
            acknowledged_at=timezone.now(),
        )
    return redirect("web:patient_detail", patient_id=patient_id)
