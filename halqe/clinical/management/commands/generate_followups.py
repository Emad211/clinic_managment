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
            default=1,
            help="Tenant ID to run follow-up generation for (default: 1).",
        )

    def handle(self, *args, **options):
        tenant_id: int = options["tenant_id"]
        verbosity: int = options.get("verbosity", 1)

        if verbosity >= 1:
            self.stdout.write(
                self.style.NOTICE(
                    f"Generating follow-up tasks for tenant={tenant_id} ..."
                )
            )

        # Import here (not at module level) to avoid circular imports at
        # Django startup and to keep the command importable without a live DB.
        from clinical.followup_engine import generate_all

        try:
            total = generate_all(tenant_id)
        except Exception as exc:
            self.stderr.write(
                self.style.ERROR(
                    f"generate_followups failed for tenant={tenant_id}: {exc}"
                )
            )
            raise

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Created {total} follow-up task(s) for tenant={tenant_id}."
            )
        )

        if verbosity >= 2 and total == 0:
            self.stdout.write(
                self.style.NOTICE(
                    "  0 tasks created — all due items are either recently handled "
                    "or no rules fired (this is normal on re-run)."
                )
            )
