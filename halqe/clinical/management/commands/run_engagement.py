"""
Management command: run_engagement

Runs the engagement dispatcher for one or all tenants.
This is what the scheduler/cron calls to drive automated outreach.

What it does
------------
- For each active PatientLink in the tenant, collects DUE clinical events
  (rule-engine + engagement_events config).
- Routes each event to the correct channel:
    worklist / both  → create followup_task (deduplicated) + record dispatch.
    sms / both       → enqueue an approval row (physician gate).
    off              → skip.
- SMS is NEVER sent here — only enqueued.  The send path is:
    dispatch → enqueue_approval (pending) → manager approves →
    POST /engagement/approvals/{id}/send → send_approved_sms().

KAVENEGAR KYC GATE
------------------
The live Kavenegar API key returns code 430 (KYC not complete) until the
clinic owner finishes identity verification.  NullProvider is used in ALL
tests and in development.  No real SMS is sent until KYC is complete.

Usage
-----
    python manage.py run_engagement
    python manage.py run_engagement --tenant-id 2
    python manage.py run_engagement --dry-run
    python manage.py run_engagement --worklist-only
    python manage.py run_engagement --tenant-id 1 --dry-run
"""
import logging

from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Run the engagement dispatcher for a tenant. "
        "Collects due events, routes to worklist and/or approval queue. "
        "NEVER sends real SMS — that requires physician approval via the API."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant-id",
            type=int,
            default=None,
            help=(
                "Tenant ID to run for (default: all tenants with active patients). "
                "Pass --tenant-id 1 to restrict to a single tenant."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help=(
                "Compute and print what would be dispatched without any DB writes. "
                "Useful for auditing before a live run."
            ),
        )
        parser.add_argument(
            "--worklist-only",
            action="store_true",
            default=False,
            help=(
                "Only run the worklist channel; skip the SMS (approval-queue) channel entirely. "
                "Useful when SMS is deliberately paused."
            ),
        )

    def handle(self, *args, **options):
        from clinical.engagement_service import run_all
        from clinical.models import PatientLink

        tenant_id: int | None = options["tenant_id"]
        dry_run: bool = options["dry_run"]
        worklist_only: bool = options["worklist_only"]
        verbosity: int = options.get("verbosity", 1)

        if dry_run and verbosity >= 1:
            self.stdout.write(self.style.WARNING("[dry-run] No DB writes will occur."))

        if tenant_id is not None:
            tenant_ids = [tenant_id]
        else:
            # All tenants that have at least one active patient
            tenant_ids = list(
                PatientLink.objects.filter(is_active=True)
                .values_list("tenant_id", flat=True)
                .distinct()
            )
            if not tenant_ids:
                self.stdout.write(self.style.WARNING("No active tenants found."))
                return

        for tid in tenant_ids:
            if verbosity >= 1:
                self.stdout.write(f"Running engagement dispatcher for tenant_id={tid} ...")

            try:
                result = run_all(
                    tid,
                    dry_run=dry_run,
                    worklist_only=worklist_only,
                )
            except Exception as exc:
                self.stderr.write(
                    self.style.ERROR(f"ERROR for tenant_id={tid}: {exc}")
                )
                logger.exception("run_engagement: error for tenant_id=%s", tid)
                continue

            if verbosity >= 1:
                prefix = "[dry-run] " if dry_run else ""
                self.stdout.write(
                    self.style.SUCCESS(
                        f"{prefix}tenant_id={tid}: "
                        f"patients={result['patients']} "
                        f"queued_sms={result['queued']} "
                        f"worklist={result['worklist']} "
                        f"skipped={result['skipped']} "
                        f"errors={result['errors']}"
                    )
                )
