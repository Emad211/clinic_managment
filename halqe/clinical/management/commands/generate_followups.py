"""
Management command: generate_followups

Runs clinical.followup_engine.generate_all(tenant_id) to populate the follow-up
worklist from fired monitoring / screening / vaccine rules.

This is the command the scheduler (Steps 16-18) and demo setup will invoke.
Idempotent: existing open tasks for the same source_rule are not duplicated.

Usage:
    python manage.py generate_followups
    python manage.py generate_followups --tenant-id 1
    python manage.py generate_followups --tenant-id 2 --verbosity 2
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Generate rule-driven follow-up tasks for all active patients. "
        "Idempotent — safe to run repeatedly."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant-id",
            type=int,
            default=None,
            help=(
                "Tenant ID to generate follow-ups for. Default: all active tenants "
                "(production scheduler runs cluster-wide, like run_engagement)."
            ),
        )

    def handle(self, *args, **options):
        # Import here (not at module level) to avoid circular imports at Django
        # startup and to keep the command importable without a live DB.
        from clinical.followup_engine import generate_all
        from platform_core.tenant_context import set_tenant_guc, clear_tenant_guc

        tenant_id = options["tenant_id"]
        verbosity: int = options.get("verbosity", 1)

        if tenant_id is not None:
            tenant_ids = [tenant_id]
        else:
            tenant_ids = self._discover_tenant_ids()
            if not tenant_ids:
                self.stdout.write(self.style.WARNING("No active tenants found."))
                return

        grand_total = 0
        for tid in tenant_ids:
            if verbosity >= 1:
                self.stdout.write(
                    self.style.NOTICE(f"Generating follow-up tasks for tenant={tid} ...")
                )

            # RLS: set the tenant GUC on the connection BEFORE any clinical query,
            # exactly as auth_bearer does in a request. Without this, in production
            # (least-privilege role, RLS fail-closed) generate_all sees ZERO rows and
            # the clinical worklist stays empty — "care never withheld" (step-51 finding).
            set_tenant_guc(tid)
            try:
                total = generate_all(tid)
            except Exception as exc:
                self.stderr.write(
                    self.style.ERROR(
                        f"generate_followups failed for tenant={tid}: {exc}"
                    )
                )
                raise
            finally:
                clear_tenant_guc()

            grand_total += total
            self.stdout.write(
                self.style.SUCCESS(
                    f"Done. Created {total} follow-up task(s) for tenant={tid}."
                )
            )
            if verbosity >= 2 and total == 0:
                self.stdout.write(
                    self.style.NOTICE(
                        "  0 tasks created — all due items are either recently handled "
                        "or no rules fired (this is normal on re-run)."
                    )
                )

        if tenant_id is None and verbosity >= 1:
            self.stdout.write(
                self.style.SUCCESS(
                    f"TOTAL: {grand_total} follow-up task(s) across "
                    f"{len(tenant_ids)} tenant(s)."
                )
            )

    # -----------------------------------------------------------------------
    # Tenant discovery — RLS-safe enumeration (mirrors run_engagement).
    # platform.tenants has a read-open SELECT policy (no tenant_id column → not
    # RLS-restricted by slice5), so it is enumerable before any GUC is set.
    # -----------------------------------------------------------------------
    def _discover_tenant_ids(self):
        from platform_core.models import Tenant
        try:
            return list(
                Tenant.objects.filter(is_active=True)
                .order_by("id")
                .values_list("id", flat=True)
            )
        except Exception:  # noqa: BLE001
            return []
