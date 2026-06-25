"""
Management command: assign_engagement_holdout

Assigns a deterministic holdout (control group) for causal engagement effect
measurement using a stepped-wedge design.

Algorithm
---------
For each active PatientLink in the given tenant:
  - Compute: hash(national_id) % 100 < holdout_pct  (deterministic; repeatable)
  - If TRUE and NOT already assigned → set engagement_holdout=TRUE,
    engagement_holdout_since=today (Tehran), engagement_holdout_until=today+90d.
  - If already assigned (engagement_holdout=TRUE) → skip (group stability).

Idempotency
-----------
Running the command twice DOES NOT re-assign already-assigned patients —
group membership must be stable across the stepped-wedge window.
Patients who were previously assigned and then manually cleared (holdout=FALSE)
are re-eligible for assignment on the next run.

Stepped-wedge design
--------------------
After `engagement_holdout_until` passes, the patient automatically transitions
back to the treated group on the next dispatch (dispatch_patient checks the date).
The manager can close the holdout early by clearing the flag manually.

⚠️ Consent gate (ROADMAP — pending legal/clinical approval):
   The patient-notification / consent policy for withholding automated reminders
   must be agreed with legal and the responsible physician before live use.
   This mechanism is ready; do NOT activate on production until that gate is cleared.

Clinical safety
---------------
ONLY dispatch_patient (automated engagement nudge) is suppressed for holdout
patients.  followup_engine.generate_for_patient, rule_engine.evaluate, visits,
prescriptions, and red-flag surfaces are NEVER affected.  Care is not denied.

Usage
-----
    python manage.py assign_engagement_holdout
    python manage.py assign_engagement_holdout --tenant-id 2
    python manage.py assign_engagement_holdout --holdout-pct 20
    python manage.py assign_engagement_holdout --window-days 180
    python manage.py assign_engagement_holdout --dry-run
"""
import hashlib
import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone as dj_timezone

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Assign a deterministic engagement holdout (control group) for causal "
        "effect measurement.  Idempotent: already-assigned patients are skipped. "
        "ONLY suppresses automated dispatch; clinical care is never denied."
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
            "--holdout-pct",
            type=int,
            default=15,
            help=(
                "Percentage of patients to assign to holdout (0–100, default 15). "
                "Uses hash(national_id) %% 100 < holdout_pct for determinism."
            ),
        )
        parser.add_argument(
            "--window-days",
            type=int,
            default=90,
            help=(
                "Duration of the holdout window in days (default 90). "
                "After this period the patient automatically returns to treated. "
                "Set to 0 for open-ended (engagement_holdout_until = NULL)."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help=(
                "Compute which patients WOULD be assigned without writing to the DB. "
                "Useful for auditing the assignment before a live run."
            ),
        )

    def handle(self, *args, **options):
        from clinical.models import PatientLink
        from accounting_port.port import get_patients_by_ids

        tenant_id: int | None = options["tenant_id"]
        holdout_pct: int = options["holdout_pct"]
        window_days: int = options["window_days"]
        dry_run: bool = options["dry_run"]
        verbosity: int = options.get("verbosity", 1)

        if not (0 <= holdout_pct <= 100):
            self.stderr.write(self.style.ERROR("--holdout-pct must be between 0 and 100."))
            return

        if dry_run and verbosity >= 1:
            self.stdout.write(self.style.WARNING("[dry-run] No DB writes will occur."))

        # Determine tenant(s) to process
        if tenant_id is not None:
            tenant_ids = [tenant_id]
        else:
            tenant_ids = list(
                PatientLink.objects.filter(is_active=True)
                .values_list("tenant_id", flat=True)
                .distinct()
            )
            if not tenant_ids:
                self.stdout.write(self.style.WARNING("No active tenants found."))
                return

        # Tehran date today — consistent with iran_now() convention
        today = dj_timezone.now().date()
        until = (today + timedelta(days=window_days)) if window_days > 0 else None

        for tid in tenant_ids:
            if verbosity >= 1:
                self.stdout.write(
                    f"Processing tenant_id={tid} "
                    f"(holdout_pct={holdout_pct}%, window={window_days}d) ..."
                )

            # Fetch ALL active patient links for this tenant
            links = list(
                PatientLink.objects.filter(tenant_id=tid, is_active=True)
                .values("id", "patient_id", "engagement_holdout")
            )

            if not links:
                if verbosity >= 1:
                    self.stdout.write(f"  tenant_id={tid}: no active patients.")
                continue

            # Fetch national_ids via the accounting Port for deterministic hashing
            patient_ids = [lnk["patient_id"] for lnk in links]
            try:
                dtos = get_patients_by_ids(patient_ids)
            except Exception as exc:
                self.stderr.write(
                    self.style.ERROR(
                        f"  tenant_id={tid}: failed to fetch patient demographics: {exc}"
                    )
                )
                logger.exception(
                    "assign_engagement_holdout: get_patients_by_ids failed tenant=%s", tid
                )
                continue

            # Map patient_id → national_id for hashing
            nat_id_map: dict[int, str] = {
                dto.id: (dto.national_id or str(dto.id))
                for dto in dtos
            }

            assigned_count = 0
            skipped_count = 0
            already_count = 0

            for lnk in links:
                pid = lnk["patient_id"]
                link_id = lnk["id"]
                already_in_holdout = bool(lnk["engagement_holdout"])

                # Idempotency: skip already-assigned patients (group stability)
                if already_in_holdout:
                    already_count += 1
                    continue

                national_id = nat_id_map.get(pid, str(pid))
                # Deterministic hash: SHA-256 of national_id → int → mod 100
                hash_int = int(
                    hashlib.sha256(national_id.encode("utf-8")).hexdigest(), 16
                ) % 100

                if hash_int < holdout_pct:
                    # Assign to holdout
                    if not dry_run:
                        PatientLink.objects.filter(
                            id=link_id, tenant_id=tid
                        ).update(
                            engagement_holdout=True,
                            engagement_holdout_since=today,
                            engagement_holdout_until=until,
                        )
                    assigned_count += 1
                    if verbosity >= 2:
                        self.stdout.write(
                            f"    link_id={link_id} national_id={national_id!r} "
                            f"hash%={hash_int} → ASSIGNED holdout"
                        )
                else:
                    skipped_count += 1

            prefix = "[dry-run] " if dry_run else ""
            if verbosity >= 1:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"{prefix}tenant_id={tid}: "
                        f"assigned={assigned_count} "
                        f"already_holdout={already_count} "
                        f"treated={skipped_count} "
                        f"total={len(links)}"
                    )
                )

            logger.info(
                "assign_engagement_holdout: tenant=%s assigned=%s "
                "already=%s treated=%s dry_run=%s",
                tid, assigned_count, already_count, skipped_count, dry_run,
            )
