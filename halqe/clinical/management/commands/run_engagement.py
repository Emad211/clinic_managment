"""
Management command: run_engagement

Runs the engagement dispatcher for one or all tenants.
This is what the EXTERNAL scheduler (managed cron now; Celery beat later) calls to
drive automated outreach.  See docs/runbook_engagement.md for the scheduling runbook.

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

PRODUCTION HARDENING (Step 51)
------------------------------
1) NO-CONCURRENT-RUN: a global Postgres advisory lock (pg_try_advisory_lock) is
   acquired at the very start.  If another run already holds it the command logs a
   structured "skipped_locked" line and exits cleanly (exit 0) — it does NOT crash
   or wait.  The lock is held for the command's lifetime and released in finally.
   The engagement_dispatch ledger (UNIQUE constraint) is the idempotency backstop.

2) TENANT GUC (RLS): this command runs OUTSIDE the request cycle, so there is no
   JWTBearer to set app.current_tenant.  RLS (slice5) is fail-closed — without the
   GUC every clinical.* query would return ZERO rows.  We therefore set the tenant
   GUC per-tenant (set_tenant_guc(tid)) before processing each tenant — the same
   mechanism auth_bearer.py uses in a request — and clear it after.

3) OBSERVABILITY: a structured, single-line, PII-free summary is logged and printed
   per tenant and as a grand total (counts only: patients, queued, worklist,
   skipped + opt_out/cooldown breakdown, holdout, errors).

KAVENEGAR KYC GATE
------------------
The live Kavenegar API key returns code 430 (KYC not complete) until the
clinic owner finishes identity verification.  NullProvider is used in ALL
tests and in development.  No real SMS is sent until KYC is complete.  This
command NEVER sends SMS regardless — it only enqueues approvals.

Exit / status semantics
-----------------------
- Normal run            → exit 0, status="ok"
- Another run in progress → exit 0, status="skipped_locked" (clean skip, no work)
- The command never returns a non-zero exit just because a single tenant errored
  (per-tenant errors are caught, counted, and logged) — this keeps the cron job
  from alerting on a transient single-tenant issue.

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
        "NEVER sends real SMS — that requires physician approval via the API. "
        "Protected by a global advisory lock (no concurrent runs)."
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
        from clinical.advisory_lock import engagement_run_lock

        dry_run: bool = options["dry_run"]

        if dry_run and options.get("verbosity", 1) >= 1:
            self.stdout.write(self.style.WARNING("[dry-run] No DB writes will occur."))

        # ── No-concurrent-run guard (global advisory lock) ───────────────────
        with engagement_run_lock() as acquired:
            if not acquired:
                # Another engagement run holds the lock — skip cleanly (exit 0).
                logger.info(
                    "engagement_run_skipped status=skipped_locked "
                    "reason=another_run_in_progress"
                )
                self.stdout.write(
                    self.style.WARNING(
                        "skipped_locked: another engagement run is in progress — "
                        "nothing to do (exit 0)."
                    )
                )
                return

            self._run(options)

    # -----------------------------------------------------------------------
    # The actual run — only reached when the advisory lock was acquired.
    # -----------------------------------------------------------------------
    def _run(self, options):
        from clinical.engagement_service import run_all
        from clinical.models import PatientLink
        from platform_core.tenant_context import set_tenant_guc, clear_tenant_guc

        tenant_id = options["tenant_id"]
        dry_run = options["dry_run"]
        worklist_only = options["worklist_only"]
        verbosity = options.get("verbosity", 1)

        if tenant_id is not None:
            tenant_ids = [tenant_id]
        else:
            # Enumerate tenants to process.  This read runs before any per-tenant
            # GUC is set; see _discover_tenant_ids for why platform.tenants is the
            # RLS-safe source (it has no tenant_id column → slice5 did not RLS it).
            tenant_ids = self._discover_tenant_ids()
            if not tenant_ids:
                self.stdout.write(self.style.WARNING("No active tenants found."))
                logger.info(
                    "engagement_run_summary status=ok tenants=0 "
                    "reason=no_active_tenants dry_run=%s", dry_run,
                )
                return

        # Grand-total accumulator across all tenants processed.
        grand = {
            "tenants": 0, "patients": 0, "queued": 0, "worklist": 0,
            "skipped": 0, "opt_out_skipped": 0, "cooldown_skipped": 0,
            "holdout": 0, "errors": 0,
        }

        for tid in tenant_ids:
            if verbosity >= 1:
                self.stdout.write(f"Running engagement dispatcher for tenant_id={tid} ...")

            # RLS: set the tenant GUC on the connection BEFORE any clinical query,
            # exactly as auth_bearer does in a request.  Cleared in finally.
            set_tenant_guc(tid)
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
                grand["errors"] += 1
                continue
            finally:
                clear_tenant_guc()

            grand["tenants"] += 1
            for k in ("patients", "queued", "worklist", "skipped",
                      "opt_out_skipped", "cooldown_skipped", "holdout", "errors"):
                grand[k] += result.get(k, 0)

            if verbosity >= 1:
                prefix = "[dry-run] " if dry_run else ""
                self.stdout.write(
                    self.style.SUCCESS(
                        f"{prefix}tenant_id={tid}: "
                        f"patients={result['patients']} "
                        f"queued_sms={result['queued']} "
                        f"worklist={result['worklist']} "
                        f"skipped={result['skipped']} "
                        f"(opt_out={result.get('opt_out_skipped', 0)} "
                        f"cooldown={result.get('cooldown_skipped', 0)}) "
                        f"holdout={result.get('holdout', 0)} "
                        f"errors={result['errors']}"
                    )
                )

        # ── Grand-total structured summary (one machine-parseable line) ──────
        logger.info(
            "engagement_run_summary status=ok tenants=%s patients=%s queued=%s "
            "worklist=%s skipped=%s opt_out_skipped=%s cooldown_skipped=%s "
            "holdout=%s errors=%s dry_run=%s worklist_only=%s",
            grand["tenants"], grand["patients"], grand["queued"], grand["worklist"],
            grand["skipped"], grand["opt_out_skipped"], grand["cooldown_skipped"],
            grand["holdout"], grand["errors"], dry_run, worklist_only,
        )
        if verbosity >= 1:
            self.stdout.write(
                self.style.SUCCESS(
                    f"TOTAL: tenants={grand['tenants']} patients={grand['patients']} "
                    f"queued_sms={grand['queued']} worklist={grand['worklist']} "
                    f"skipped={grand['skipped']} holdout={grand['holdout']} "
                    f"errors={grand['errors']}"
                )
            )

    # -----------------------------------------------------------------------
    # Tenant discovery — RLS-safe enumeration of tenants with active patients.
    # -----------------------------------------------------------------------
    def _discover_tenant_ids(self):
        """
        Return the list of tenant_ids that have at least one active PatientLink.

        RLS NOTE: clinical.patient_links is RLS-protected and fail-closed.  With no
        GUC set, a query would return 0 rows.  platform.tenants, however, has a
        read-open SELECT policy (slice5/slice0) — so we enumerate ACTIVE tenants
        from platform.tenants (cluster-wide) and let run_all (under the per-tenant
        GUC) be a no-op for tenants that happen to have no active patients.

        This is correct: an empty tenant simply yields patients=0.
        """
        from platform_core.models import Tenant
        try:
            return list(
                Tenant.objects.filter(is_active=True)
                .order_by("id")
                .values_list("id", flat=True)
            )
        except Exception as exc:
            logger.warning(
                "run_engagement: tenant discovery via platform.tenants failed "
                "(%s); falling back to patient_links enumeration", exc,
            )
            from clinical.models import PatientLink
            return list(
                PatientLink.objects.filter(is_active=True)
                .values_list("tenant_id", flat=True)
                .distinct()
            )
