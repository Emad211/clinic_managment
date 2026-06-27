"""
Management command: demo_sandbox  (ROADMAP step 57 — Demo Sandbox)

ONE COMMAND → a fully-populated, sales-demoable care loop in the UI.

It does NOT re-implement seeding logic.  It ORCHESTRATES the existing, already
tested management commands (reuse, never duplicate) so every care-loop surface
lights up in a single run:

    1. seed_clinical_rules     → the rule catalog (drives suggestions + due events)
    2. seed_engagement_events  → event→channel routing (drives SMS approvals)
    3. seed_demo               → 4 representative patients + admin/admin user
    4. generate_followups      → followup_tasks  (lights up the Worklist + Control Room "due" items)
    5. run_engagement          → routes due events:
                                   worklist/both → followup_tasks (+ dispatch ledger)
                                   sms/both      → engagement_approvals in 'pending'
                                                   (lights up /manager/engagement review queue)

After this run, these UI surfaces are populated for the demo tenant:
    /patients              — enrolled patient list
    /patients/<uuid>       — record + live rule-engine suggestions ("پیشنهاد — تأیید با پزشک")
    /worklist              — rule-driven followup_tasks (the prioritized "due" list +
                             manager-only revenue column) — this is the demo's
                             cohort/prioritization surface
    /manager/engagement    — ≥1 pending engagement approval (physician review queue)
    /manager/outcomes      — derived analytics (acceptance / funnel / control trend)

NOTE: the Control Room is currently an API only (GET /control-room) — the
standalone /control-room *page* is not built yet (ROADMAP cluster D/H deferral).
The Worklist is the clickable prioritization surface in the demo; do NOT navigate
to a /control-room page in a live demo (it would 404).

Login: admin / admin  (manager)

────────────────────────────────────────────────────────────────────────────
⚠️  DANGER — SUPERUSER PATH.  DO NOT POINT AT PRODUCTION.
────────────────────────────────────────────────────────────────────────────
This command seeds SYNTHETIC demo data and uses the SUPERUSER credentials
(PG_USER/PG_PASSWORD) for the accounting.patients seed path — exactly like
seed_demo — because the least-privilege app role is SELECT-only on accounting.*.
Running it against a live clinic database would inject fake "DEMO" patients into
real data.  Only ever run it against a throwaway / staging / local demo DB.

Demo data is clearly synthetic:
  - national_ids TEST0001..TEST0007, names "نمونه …"
  - vital_readings.source = 'demo'
  - NO real PHI, NO real SMS (SMS is only ENQUEUED as a pending approval —
    nothing is sent; the send path requires manager approval + KYC + SMS_LIVE_ENABLED)
  - accounting DB is read-only from the app; this writes only the demo DB.

Idempotency:
  Every sub-command is idempotent (ON CONFLICT DO NOTHING / dedup ledgers /
  recall-window guards), so re-running demo_sandbox does NOT create duplicate
  patients, rules, events, followups, or approvals — counts stay stable/sane.

Usage:
    python manage.py demo_sandbox
    python manage.py demo_sandbox --tenant-id 1
    python manage.py demo_sandbox --admin-password admin
    python manage.py demo_sandbox --base-url http://127.0.0.1:8000   # for the printed links
"""
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Build a complete demo sandbox (patients + rules + events + followups + "
        "pending engagement approvals) in ONE run by orchestrating the existing "
        "seed/generate commands.  Idempotent.  SUPERUSER PATH — never point at "
        "production (it seeds synthetic DEMO data like seed_demo)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant-id",
            type=int,
            default=1,
            help="Tenant ID to build the demo for (default: 1).",
        )
        parser.add_argument(
            "--admin-password",
            default="admin",
            help="Password for the demo admin user (default: 'admin').",
        )
        parser.add_argument(
            "--base-url",
            default="http://127.0.0.1:3000",
            help=(
                "Base URL of the running web panel, used only to print clickable "
                "demo links at the end (default: http://127.0.0.1:3000)."
            ),
        )

    def handle(self, *args, **options):
        from clinical.models import (
            PatientLink,
            FollowupTask,
            EngagementApproval,
        )
        from platform_core.tenant_context import set_tenant_guc, clear_tenant_guc

        tenant_id: int = options["tenant_id"]
        admin_password: str = options["admin_password"]
        base_url: str = options["base_url"].rstrip("/")

        # ── Loud safety banner (also in --help) ──────────────────────────────
        self.stdout.write(self.style.WARNING("=" * 72))
        self.stdout.write(self.style.WARNING(
            "  demo_sandbox — SYNTHETIC DEMO DATA via the SUPERUSER path."
        ))
        self.stdout.write(self.style.WARNING(
            "  ⚠️  DO NOT POINT THIS AT A PRODUCTION DATABASE."
        ))
        self.stdout.write(self.style.WARNING(
            "  No real PHI · No real SMS (only enqueued, never sent) · "
            "accounting is read-only."
        ))
        self.stdout.write(self.style.WARNING("=" * 72))
        self.stdout.write("")

        # ── 1. Clinical rule catalog ─────────────────────────────────────────
        # Drives both the suggestion engine and due_clinical_events (→ followups
        # + sms approvals).  RLS NOTE: clinical.clinical_rules is FORCE-RLS
        # (slice5).  seed_clinical_rules itself does NOT set the tenant GUC, so we
        # set it on this command's connection first, exactly as auth_bearer does
        # in a request and as run_engagement does per-tenant.  Without this, every
        # INSERT would be rejected by the tenant_isolation WITH CHECK policy.
        self.stdout.write(self.style.NOTICE("[1/5] Seeding clinical rule catalog …"))
        set_tenant_guc(tenant_id)
        try:
            call_command("seed_clinical_rules", tenant_id=tenant_id, verbosity=0)
            # ── 2. Engagement event→channel routing ──────────────────────────
            # Needed so SMS-channel events (monitoring_due/screening_due/...) exist
            # for the dispatcher to enqueue approvals.  This command sets its own
            # GUC, but we keep ours set for symmetry (no harm — same tenant).
            self.stdout.write(self.style.NOTICE("[2/5] Seeding engagement event catalog …"))
            call_command("seed_engagement_events", tenant_id=tenant_id, verbosity=0)
        finally:
            clear_tenant_guc()

        # ── 3. Demo patients + admin user ────────────────────────────────────
        # seed_demo uses its OWN superuser psycopg connection (it must, to write
        # accounting.patients) and is RLS-exempt on that path — so no GUC needed
        # here.  4 patients: controlled DM / uncontrolled DM / DM+HTN+CKD / frail.
        self.stdout.write(self.style.NOTICE("[3/5] Seeding demo patients + admin user …"))
        call_command(
            "seed_demo",
            tenant_id=tenant_id,
            admin_password=admin_password,
            verbosity=1,
        )

        # ── 4. Rule-driven follow-up worklist ────────────────────────────────
        # generate_followups sets the tenant GUC per-tenant internally (it must,
        # for RLS) — so we call it plainly.  Creates monitoring/screening tasks
        # that are actually DUE → the Worklist and Control-Room "due" items.
        self.stdout.write(self.style.NOTICE("[4/5] Generating follow-up tasks …"))
        call_command("generate_followups", tenant_id=tenant_id, verbosity=1)

        # ── 5. Engagement dispatch → pending approvals + worklist ────────────
        # run_engagement also sets the tenant GUC internally and is protected by a
        # global advisory lock.  It NEVER sends SMS — sms-channel events are
        # ENQUEUED as 'pending' EngagementApproval rows (the physician gate).  This
        # is what lights up /manager/engagement with a review queue.
        self.stdout.write(self.style.NOTICE("[5/5] Running engagement dispatcher (enqueue only, no SMS sent) …"))
        call_command("run_engagement", tenant_id=tenant_id, verbosity=1)

        # ── Summary counts (read under the tenant GUC) ───────────────────────
        set_tenant_guc(tenant_id)
        try:
            patient_count = PatientLink.objects.filter(
                tenant_id=tenant_id, is_active=True
            ).count()
            followup_count = FollowupTask.objects.filter(
                tenant_id=tenant_id, status="open"
            ).count()
            pending_approvals = EngagementApproval.objects.filter(
                tenant_id=tenant_id,
                status=EngagementApproval.STATUS_PENDING,
            ).count()
        finally:
            clear_tenant_guc()

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=" * 72))
        self.stdout.write(self.style.SUCCESS("  DEMO SANDBOX READY"))
        self.stdout.write(self.style.SUCCESS("=" * 72))
        self.stdout.write(f"  Tenant ............... {tenant_id}")
        self.stdout.write(f"  Active patients ...... {patient_count}")
        self.stdout.write(f"  Open follow-up tasks . {followup_count}")
        self.stdout.write(f"  Pending approvals .... {pending_approvals}")
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"  LOGIN:  admin / {admin_password}   (manager)"
        ))
        self.stdout.write("")
        self.stdout.write("  Demo URLs (start the web panel, then visit):")
        self.stdout.write(f"    Dashboard ........... {base_url}/dashboard")
        self.stdout.write(f"    Patients ............ {base_url}/patients")
        self.stdout.write(f"    Worklist ............ {base_url}/worklist   (prioritized 'due' list)")
        self.stdout.write(f"    Engagement queue .... {base_url}/manager/engagement")
        self.stdout.write(f"    Outcomes ............ {base_url}/manager/outcomes")
        self.stdout.write(self.style.NOTICE(
            "    (Control Room is API-only — GET /control-room; no standalone page yet.)"
        ))
        self.stdout.write("")
        self.stdout.write(self.style.NOTICE(
            "  Demo patients: TEST0001 (controlled DM), TEST0002 (uncontrolled DM), "
            "TEST0003 (DM+HTN+CKD), TEST0007 (elderly frail)."
        ))
        self.stdout.write(self.style.NOTICE(
            "  All data synthetic (source='demo'); no SMS sent; accounting read-only."
        ))
        self.stdout.write("")

        if pending_approvals == 0:
            # Not a failure — but flag it so the demo operator knows the engagement
            # queue may be empty (e.g. all sms events already dispatched on a re-run,
            # or no sms-channel event was due).  The approvals are idempotent, so a
            # second run won't add more once a period's bucket is taken.
            self.stdout.write(self.style.WARNING(
                "  NOTE: 0 pending approvals. On a FIRST run this is unexpected; on a "
                "re-run it is normal (idempotent — buckets already dispatched). The "
                "approval queue keeps any rows from the first run."
            ))
