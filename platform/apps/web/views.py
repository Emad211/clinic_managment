"""Minimal server-rendered frontend (Django templates; HTMX layered next).

Demoable slice of the wedge: login -> patient list -> patient snapshot + live
ADA suggestions (the ported rule engine). Tenant context is set by
TenantMiddleware from the session; login follows the RLS-correct ordering
(resolve clinic by slug, then authenticate against app_user in tenant context).
"""

import csv
from functools import wraps

from django.contrib import messages
from django.db import transaction as db_transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import Payment, Plan, Subscription
from apps.billing.services import confirm_payment
from apps.billing.services import subscribe as start_subscription

from apps.accounting import reports as acc_reports
from apps.accounting import services as acc
from apps.accounting.models import InsurancePlan, Invoice, Tariff
from apps.chronic import rule_engine
from apps.chronic.models import (
    ClinicalRule, FollowupTask, SuggestionLog, VitalReading, WalletTransaction,
)
from apps.messaging.models import SmsMessage
from apps.common.activity import log_activity
from apps.common.knowledge import knowledge_client
from apps.common.models import ActivityLog
from apps.common.tenant import tenant_context
from apps.identity.models import AppUser, Clinic
from apps.identity.services import AuthError, authenticate
from apps.patients.models import Patient
from apps.messaging.services import send_sms
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
        # Resolve the user fresh every request so a deactivated/deleted account
        # loses access immediately (not only at next login) — matches the ninja
        # SessionAuth contract. A stale session is flushed.
        if _current_user(request) is None:
            request.session.flush()
            return redirect("web:login")
        return view(request, *args, **kwargs)

    return wrapper


def _current_user(request):
    """The logged-in, still-active user — or None. is_active is re-checked on
    every call so deactivation revokes web access at once (security audit)."""
    uid = request.session.get("user_id")
    if not uid:
        return None
    return AppUser.objects.filter(id=uid, is_active=True).first()


def roles_required(*roles):
    """Gate a web view to one of ``roles`` (inline pattern, like the Flask apps).
    Composes under @login_required_web."""
    def deco(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            user = _current_user(request)
            if user is None or user.role not in roles:
                messages.error(request, "دسترسی به این بخش مجاز نیست.")
                return redirect("web:dashboard")
            return view(request, *args, **kwargs)
        return wrapper
    return deco


def clinical_license_required(view):
    """Gate a "physician decides" action (acknowledge an ADA suggestion, issue an
    e-prescription) to a user holding a نظام‌پزشکی license. Unlicensed users are
    bounced back with a message rather than silently completing the action —
    REGULATORY §1/§6 ("the system suggests; a licensed physician decides")."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        user = _current_user(request)
        if user is None or not user.can_practice_clinically():
            messages.error(
                request,
                "این اقدام بالینی نیازمند کاربر دارای پروانهٔ نظام‌پزشکی است.",
            )
            if "patient_id" in kwargs:
                return redirect("web:patient_detail", patient_id=kwargs["patient_id"])
            if "rx_id" in kwargs:
                return redirect("web:rx_detail", rx_id=kwargs["rx_id"])
            return redirect("web:patients")
        return view(request, *args, **kwargs)

    return wrapper


def index(request):
    if request.session.get("user_id"):
        return redirect("web:dashboard")
    return redirect("web:login")


@login_required_web
def dashboard(request):
    """Clinic-at-a-glance landing for the manager."""
    user = _current_user(request)
    today = timezone.localdate()
    open_fu = FollowupTask.objects.filter(status="open")
    kpis = {
        "patients": Patient.objects.filter(is_active=True).count(),
        "followups_open": open_fu.count(),
        "followups_overdue": open_fu.filter(due_date__lt=today).count(),
        "rx_registered": Prescription.objects.filter(status="registered").count(),
        "sms_sent": SmsMessage.objects.exclude(status="failed").count(),
        "suggestions_acked": SuggestionLog.objects.exclude(acknowledged_at__isnull=True).count(),
    }
    overdue_list = list(
        open_fu.filter(due_date__lt=today).select_related("patient").order_by("due_date")[:5]
    )
    sub = (
        Subscription.objects.filter(clinic=user.clinic, status="active")
        .select_related("plan").first()
        if user else None
    )
    revenue_today = acc_reports.revenue_summary(today, today)["total_gross"]
    return render(request, "web/dashboard.html", {
        "kpis": kpis, "overdue_list": overdue_list, "subscription": sub,
        "revenue_today": revenue_today,
    })


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
        # Rotate the session id at the auth boundary to defeat session fixation
        # (a pre-auth/planted cookie must not remain valid after login).
        request.session.cycle_key()
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
    wallet_txns = list(
        WalletTransaction.objects.filter(patient=patient).order_by("-created_at")[:8]
    )

    # best-effort ICD-11 crosswalk from the knowledge pipeline (empty if the
    # ai_service is not configured/reachable — the page is unaffected)
    kc = knowledge_client()
    condition_crosswalk = {}
    for code in facts.get("conditions", []):
        concept = kc.concept(code)
        if concept and concept.get("icd11"):
            condition_crosswalk[code] = concept["icd11"]

    user = _current_user(request)
    can_sign = bool(user and user.can_practice_clinically())

    return render(request, "web/patient_detail.html", {
        "patient": patient,
        "facts": facts,
        "suggestions": suggestions,
        "snapshot": snapshot,
        "acked": acked,
        "prescriptions": prescriptions,
        "insurer_labels": INSURER_LABELS,
        "wallet_txns": wallet_txns,
        "condition_crosswalk": condition_crosswalk,
        "can_sign": can_sign,
    })


@login_required_web
def wallet_txn(request, patient_id):
    """Append-only wallet credit/debit (the lawful substitute for discount/free).
    Updates the patient balance and records a WalletTransaction atomically."""
    patient = get_object_or_404(Patient, id=patient_id)
    if request.method == "POST":
        kind = request.POST.get("kind")
        reason = request.POST.get("reason", "")
        try:
            amount = int(request.POST.get("amount") or 0)
        except ValueError:
            amount = 0
        if amount > 0 and kind in ("credit", "debit"):
            with db_transaction.atomic():
                p = Patient.objects.select_for_update().get(id=patient.id)
                if kind == "debit":
                    amount = min(amount, p.wallet_balance)  # never go negative
                if amount > 0:
                    actor = _current_user(request)
                    p.wallet_balance += amount if kind == "credit" else -amount
                    p.save(update_fields=["wallet_balance", "updated_at"])
                    WalletTransaction.objects.create(
                        clinic=p.clinic, patient=p, kind=kind, amount=amount,
                        balance_after=p.wallet_balance, reason=reason,
                        created_by=actor,
                    )
                    log_activity(
                        p.clinic, actor, f"wallet.{kind}",
                        summary=f"{'واریز' if kind == 'credit' else 'برداشت'} {amount} ریال — {p.full_name}",
                        entity_type="patient", entity_id=p.id,
                        metadata={"amount": amount, "balance_after": p.wallet_balance, "reason": reason},
                    )
    return redirect("web:patient_detail", patient_id=patient_id)


# ── billing / subscription (ZarinPal) ─────────────────────────────────────

@login_required_web
def billing_home(request):
    user = _current_user(request)
    plans = list(Plan.objects.filter(is_active=True).order_by("price_rial"))
    sub = (
        Subscription.objects.filter(clinic=user.clinic, status="active")
        .select_related("plan").order_by("-period_end").first()
        if user else None
    )
    return render(request, "web/billing.html", {"plans": plans, "subscription": sub})


@login_required_web
def billing_subscribe(request, plan_id):
    if request.method != "POST":
        return redirect("web:billing")
    user = _current_user(request)
    plan = get_object_or_404(Plan, id=plan_id)
    callback = request.build_absolute_uri(reverse("web:billing_callback"))
    _payment, url = start_subscription(user.clinic, plan, callback)
    if url:  # paid plan -> go to gateway (or simulated callback)
        return redirect(url)
    return redirect("web:billing")  # free plan activated immediately


@login_required_web
def billing_callback(request):
    # Lock the payment row so two concurrent callbacks can't both pass the
    # 'pending' gate (the request is already inside an ATOMIC_REQUESTS tx).
    with db_transaction.atomic():
        payment = (
            Payment.objects.select_for_update()
            .filter(id=request.GET.get("payment"))
            .first()
        )
        if payment and request.GET.get("Status") == "OK" and payment.status == "pending":
            # plan is bound to the Payment at request time (never re-derived by price)
            confirm_payment(payment)
    return redirect("web:billing")


# ── e-prescription (Epic 1) — WebView bridge workflow ──────────────────────

@login_required_web
@clinical_license_required
def rx_new(request, patient_id):
    """Start a draft prescription for a patient (channel=webview)."""
    patient = get_object_or_404(Patient, id=patient_id)
    if request.method != "POST":
        return redirect("web:patient_detail", patient_id=patient_id)
    insurer = (request.POST.get("insurer") or "tamin").strip()
    if insurer not in INSURER_PORTALS:
        insurer = "tamin"
    actor = _current_user(request)
    rx = Prescription.objects.create(
        clinic=patient.clinic, patient=patient, doctor=actor,
        insurer=insurer, status="draft", channel="webview",
    )
    InsurerLog.objects.create(
        clinic=patient.clinic, prescription=rx, insurer=insurer,
        action="draft_created", status="draft", payload={},
    )
    log_activity(
        patient.clinic, actor, "rx.create",
        summary=f"ایجاد نسخهٔ {INSURER_LABELS.get(insurer, insurer)} برای {patient.full_name}",
        entity_type="prescription", entity_id=rx.id, metadata={"insurer": insurer},
    )
    return redirect("web:rx_detail", rx_id=rx.id)


@login_required_web
def rx_detail(request, rx_id):
    rx = get_object_or_404(Prescription, id=rx_id)
    items = list(PrescriptionItem.objects.filter(prescription=rx))
    logs = list(InsurerLog.objects.filter(prescription=rx).order_by("created_at"))
    user = _current_user(request)
    return render(request, "web/rx_detail.html", {
        "rx": rx, "items": items, "logs": logs,
        "portal_url": INSURER_PORTALS.get(rx.insurer, ""),
        "insurer_label": INSURER_LABELS.get(rx.insurer, rx.insurer),
        # the clinical content (items) + registration are physician acts, and a
        # submitted/registered script is frozen — drive the UI from these flags
        "can_edit_rx": bool(user and user.can_practice_clinically() and rx.status == "draft"),
        "can_register_rx": bool(
            user and user.can_practice_clinically() and rx.status in ("draft", "submitted")
        ),
    })


@login_required_web
@clinical_license_required
def rx_add_item(request, rx_id):
    """Add a line item (drug/dose/order) to a DRAFT prescription. This writes the
    clinical substance of the script, so it is license-gated like rx_new/rx_register
    (security audit: was previously only login-gated) and refused once the script
    has been submitted/registered (append-only after sign-off)."""
    rx = get_object_or_404(Prescription, id=rx_id)
    if request.method == "POST":
        if rx.status != "draft":
            messages.error(request, "نسخهٔ ثبت/ارسال‌شده قابل ویرایش نیست.")
            return redirect("web:rx_detail", rx_id=rx.id)
        name = (request.POST.get("item_name") or "").strip()
        if name:
            item = PrescriptionItem.objects.create(
                clinic=rx.clinic, prescription=rx, kind=request.POST.get("kind", "drug"),
                item_name=name, dose=request.POST.get("dose", ""),
                count=(request.POST.get("count") or None),
                instruction=request.POST.get("instruction", ""),
            )
            log_activity(
                rx.clinic, _current_user(request), "rx.add_item",
                summary=f"افزودن قلم «{name}» به نسخه",
                entity_type="prescription", entity_id=rx.id,
                metadata={"item": name, "kind": item.kind},
            )
    return redirect("web:rx_detail", rx_id=rx.id)


@login_required_web
@clinical_license_required
def rx_register(request, rx_id):
    """Record the insurer tracking code returned by the portal and mark the
    prescription registered (logs to InsurerLog for the audit trail). Refused on
    an already-registered script so the local record can't diverge from what was
    submitted to the insurer."""
    rx = get_object_or_404(Prescription, id=rx_id)
    if request.method == "POST":
        if rx.status not in ("draft", "submitted"):
            messages.error(request, "این نسخه قبلاً ثبت شده است.")
            return redirect("web:rx_detail", rx_id=rx.id)
        code = (request.POST.get("tracking_code") or "").strip()
        rx.tracking_code = code
        rx.status = "registered" if code else "submitted"
        rx.issued_at = timezone.now()
        rx.save(update_fields=["tracking_code", "status", "issued_at", "updated_at"])
        InsurerLog.objects.create(
            clinic=rx.clinic, prescription=rx, insurer=rx.insurer,
            action="register", status=rx.status, payload={"tracking_code": code},
        )
        log_activity(
            rx.clinic, _current_user(request), "rx.register",
            summary=f"ثبت نسخه با کد رهگیری {code or '—'} ({rx.status})",
            entity_type="prescription", entity_id=rx.id,
            metadata={"tracking_code": code, "status": rx.status},
        )
    return redirect("web:rx_detail", rx_id=rx.id)


@login_required_web
def activity_log(request):
    """Append-only audit trail (REGULATORY §6 — ممیزی). Manager-only: the audit
    view is for clinic oversight, not day-to-day clinical staff."""
    user = _current_user(request)
    if user is None or user.role != "clinic_manager":
        messages.error(request, "دسترسی به گزارشِ ممیزی فقط برای مدیر مجاز است.")
        return redirect("web:dashboard")
    action = (request.GET.get("action") or "").strip()
    qs = ActivityLog.objects.all()
    if action:
        qs = qs.filter(action=action)
    rows = list(qs.select_related("actor").order_by("-created_at")[:200])
    actions = list(
        ActivityLog.objects.values_list("action", flat=True).distinct().order_by("action")
    )
    return render(request, "web/activity.html", {
        "rows": rows, "actions": actions, "action": action,
    })


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
            log_activity(
                t.clinic, _current_user(request), "followup.done",
                summary=f"انجام پیگیری: {t.title or t.item_key}",
                entity_type="followup_task", entity_id=t.id,
            )
    return redirect("web:worklist")


@login_required_web
def followup_remind(request, task_id):
    """Send the patient an SMS reminder for a due follow-up (Epic 6). Falls back
    to a simulated send when no Mediana key is configured."""
    if request.method == "POST":
        t = FollowupTask.objects.select_related("patient").filter(id=task_id).first()
        if t and t.patient:
            label = t.title or t.item_key
            body = f"یادآوری پیگیری سلامت: {label}"
            if t.due_date:
                body += f" — سررسید {t.due_date}"
            send_sms(t.clinic, t.patient.phone_number, body, patient=t.patient)
            log_activity(
                t.clinic, _current_user(request), "followup.remind",
                summary=f"ارسال یادآور پیامکی: {label} — {t.patient.full_name}",
                entity_type="followup_task", entity_id=t.id,
            )
    return redirect("web:worklist")


@login_required_web
@clinical_license_required
def acknowledge_suggestion(request, patient_id):
    """Physician acknowledges a suggestion -> append-only SuggestionLog row.
    Embodies the safety principle: the system suggests, the physician decides,
    and the decision is logged (gated to a licensed clinical user)."""
    if request.method != "POST":
        return redirect("web:patient_detail", patient_id=patient_id)
    patient = get_object_or_404(Patient, id=patient_id)
    rule_code = (request.POST.get("rule_code") or "").strip()
    rule = ClinicalRule.objects.filter(code=rule_code).first()
    if rule and not SuggestionLog.objects.filter(
        patient=patient, rule_code=rule_code
    ).exclude(acknowledged_at__isnull=True).exists():
        actor = _current_user(request)
        SuggestionLog.objects.create(
            clinic=patient.clinic,
            patient=patient,
            rule_code=rule_code,
            severity=rule.severity,
            message_fa=rule.recommendation or rule.title,
            acknowledged_by=actor,
            acknowledged_at=timezone.now(),
        )
        log_activity(
            patient.clinic, actor, "suggestion.acknowledge",
            summary=f"تأیید پیشنهاد {rule_code} برای {patient.full_name}",
            entity_type="patient", entity_id=patient.id,
            metadata={"rule_code": rule_code, "severity": rule.severity},
        )
    return redirect("web:patient_detail", patient_id=patient_id)


# ── reception desk / invoicing (accounting port, ACCOUNTING.md phase 3) ─────
SHIFT_CHOICES = [("morning", "صبح"), ("evening", "عصر"), ("night", "شب")]
PAY_METHODS = [("cash", "نقد"), ("card", "کارت"), ("wallet", "کیف‌پول"), ("insurance", "بیمه")]
_DESK_ROLES = ("reception", "clinic_manager")
# tariff.kind -> the service that books it as a priced, insurance-split item
_KIND_TO_ADDER = {
    "visit": acc.add_visit,
    "injection": acc.add_injection,
    "nursing": acc.add_injection,
    "procedure": acc.add_procedure,
    "service": acc.add_procedure,
}


@login_required_web
@roles_required(*_DESK_ROLES)
def reception(request):
    """The desk: open a new invoice for a patient (by national id) and see the
    open/partial invoices to settle."""
    user = _current_user(request)
    today = timezone.localdate()
    if request.method == "POST":
        nid = (request.POST.get("national_id") or "").strip()
        shift = request.POST.get("shift") or "morning"
        patient = Patient.objects.filter(national_id=nid, is_active=True).first()
        if not patient:
            messages.error(request, "بیمار با این کد ملی یافت نشد.")
            return redirect("web:reception")
        inv = acc.open_invoice(user.clinic, patient, today, shift, created_by=user)
        return redirect("web:invoice_detail", invoice_id=inv.id)
    open_invoices = list(
        Invoice.objects.filter(status__in=["open", "partial"])
        .select_related("patient").order_by("-created_at")[:50]
    )
    return render(request, "web/reception.html", {
        "open_invoices": open_invoices, "shifts": SHIFT_CHOICES, "today": today,
    })


@login_required_web
@roles_required(*_DESK_ROLES)
def invoice_open_for_patient(request, patient_id):
    """Open an invoice directly from a patient's page."""
    patient = get_object_or_404(Patient, id=patient_id)
    if request.method == "POST":
        user = _current_user(request)
        shift = request.POST.get("shift") or "morning"
        inv = acc.open_invoice(user.clinic, patient, timezone.localdate(), shift, created_by=user)
        return redirect("web:invoice_detail", invoice_id=inv.id)
    return redirect("web:patient_detail", patient_id=patient_id)


@login_required_web
@roles_required(*_DESK_ROLES)
def invoice_detail(request, invoice_id):
    inv = get_object_or_404(Invoice, id=invoice_id)
    visits = list(inv.visits.select_related("insurance_plan", "tariff").all())
    injections = list(inv.injections.select_related("insurance_plan").all())
    procedures = list(inv.procedures.select_related("insurance_plan").all())
    payments = list(inv.payments.all())
    tariffs = list(Tariff.objects.filter(is_active=True).order_by("kind", "name"))
    plans = list(InsurancePlan.objects.filter(is_active=True).order_by("name"))
    editable = inv.status in ("open", "partial")
    return render(request, "web/invoice_detail.html", {
        "inv": inv, "visits": visits, "injections": injections, "procedures": procedures,
        "payments": payments, "tariffs": tariffs, "plans": plans,
        "methods": PAY_METHODS, "editable": editable,
    })


@login_required_web
@roles_required(*_DESK_ROLES)
def invoice_add_item(request, invoice_id):
    inv = get_object_or_404(Invoice, id=invoice_id)
    if request.method == "POST" and inv.status in ("open", "partial"):
        tariff = Tariff.objects.filter(id=request.POST.get("tariff_id"), is_active=True).first()
        plan = InsurancePlan.objects.filter(id=request.POST.get("insurance_plan_id")).first()
        manual_name = (request.POST.get("name") or "").strip()
        try:
            manual_amount = int(request.POST.get("amount") or 0) or None
        except ValueError:
            manual_amount = None
        kind = tariff.kind if tariff else (request.POST.get("kind") or "procedure")
        adder = _KIND_TO_ADDER.get(kind, acc.add_procedure)
        if tariff or manual_amount:
            kwargs = {"tariff": tariff, "amount_rial": manual_amount, "insurance_plan": plan}
            if adder is acc.add_visit:
                adder(inv, **kwargs)
            else:
                adder(inv, name=manual_name or None, **kwargs)
    return redirect("web:invoice_detail", invoice_id=inv.id)


@login_required_web
@roles_required(*_DESK_ROLES)
def invoice_pay(request, invoice_id):
    inv = get_object_or_404(Invoice, id=invoice_id)
    if request.method == "POST":
        try:
            amount = int(request.POST.get("amount") or 0)
        except ValueError:
            amount = 0
        method = request.POST.get("method") or "cash"
        if amount > 0:
            acc.record_payment(inv, amount, method, actor=_current_user(request))
    return redirect("web:invoice_detail", invoice_id=inv.id)


@login_required_web
@roles_required(*_DESK_ROLES)
def invoice_close(request, invoice_id):
    inv = get_object_or_404(Invoice, id=invoice_id)
    if request.method == "POST":
        acc.close_invoice(inv, actor=_current_user(request))
    return redirect("web:invoice_detail", invoice_id=inv.id)


@login_required_web
@roles_required("clinic_manager")
def tariffs(request):
    """Manager: the per-clinic price list (the generalisation — editable data, not
    code). Add a tariff or toggle one active/inactive."""
    user = _current_user(request)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add":
            name = (request.POST.get("name") or "").strip()
            try:
                amount = int(request.POST.get("amount") or 0)
            except ValueError:
                amount = 0
            if name:
                Tariff.objects.create(
                    clinic=user.clinic, kind=request.POST.get("kind") or "service",
                    name=name, amount_rial=amount, category=request.POST.get("category") or "",
                )
        elif action == "toggle":
            t = Tariff.objects.filter(id=request.POST.get("tariff_id")).first()
            if t:
                t.is_active = not t.is_active
                t.save(update_fields=["is_active", "updated_at"])
        return redirect("web:tariffs")
    rows = list(Tariff.objects.all().order_by("kind", "name"))
    return render(request, "web/tariffs.html", {
        "tariffs": rows, "kinds": Tariff.KIND, "categories": Tariff.CATEGORY,
    })


def _report_range(request):
    """Resolve the report window from ?from=&to= (Gregorian ISO), default = this
    month to today."""
    today = timezone.localdate()
    default_from = today.replace(day=1)

    def _parse(s, fallback):
        from datetime import date
        try:
            y, m, d = (int(x) for x in str(s).split("-"))
            return date(y, m, d)
        except (ValueError, AttributeError):
            return fallback

    dfrom = _parse(request.GET.get("from"), default_from)
    dto = _parse(request.GET.get("to"), today)
    return dfrom, dto


@login_required_web
@roles_required("clinic_manager")
def reports(request):
    """Financial reports (manager): revenue today + range, broken down by service
    kind, shift, insurance and doctor. Revenue = visit+injection+procedure gross."""
    today = timezone.localdate()
    dfrom, dto = _report_range(request)
    return render(request, "web/reports.html", {
        "today_summary": acc_reports.revenue_summary(today, today),
        "range_summary": acc_reports.revenue_summary(dfrom, dto),
        "by_insurance": acc_reports.revenue_by_insurance(dfrom, dto),
        "by_doctor": acc_reports.revenue_by_doctor(dfrom, dto),
        "dfrom": dfrom, "dto": dto, "today": today,
    })


@login_required_web
@roles_required("clinic_manager")
def reports_export_csv(request):
    """Export the range's invoices as CSV (UTF-8 BOM so Excel reads Persian)."""
    dfrom, dto = _report_range(request)
    invoices = (
        Invoice.objects.filter(work_date__gte=dfrom, work_date__lte=dto)
        .select_related("patient").order_by("work_date", "created_at")
    )
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="invoices_{dfrom}_{dto}.csv"'
    resp.write("﻿")  # BOM for Excel
    w = csv.writer(resp)
    w.writerow(["work_date", "shift", "patient", "national_id", "total_rial", "paid_rial", "status"])
    for inv in invoices:
        w.writerow([
            inv.work_date, inv.shift, inv.patient.full_name, inv.patient.national_id or "",
            inv.total_rial, inv.paid_rial, inv.status,
        ])
    return resp
